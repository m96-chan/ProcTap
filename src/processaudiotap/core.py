from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional, AsyncIterator
import threading
import queue
import asyncio
import struct

from . import _native  # C++拡張

AudioCallback = Callable[[bytes, int], None]  # (pcm_bytes, num_frames)


@dataclass
class StreamConfig:
  sample_rate: int = 48000
  channels: int = 2
  frames_per_buffer: int = 480  # 10ms @ 48kHz


class ProcessAudioTap:
    """
    High-level API for per-process WASAPI loopback capture.

    - pid: 対象プロセスID（推奨）
    - on_data: コールバック。pcm_bytes, num_frames を受け取る
    """

    def __init__(
        self,
        pid: int,
        config: StreamConfig | None = None,
        on_data: Optional[AudioCallback] = None,
    ) -> None:
        if config is None:
            config = StreamConfig()
        self._pid = pid
        self._cfg = config
        self._on_data = on_data

        self._handle: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # async 用キュー
        self._async_queue: "queue.Queue[bytes]" = queue.Queue()

    # --- public API ---

    def start(self) -> None:
        if self._handle is not None:
            return

        self._handle = _native.open_stream(
            self._pid,
            self._cfg.sample_rate,
            self._cfg.channels,
            self._cfg.frames_per_buffer,
        )

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        if self._handle is not None:
            _native.close_stream(self._handle)
            self._handle = None

    def close(self) -> None:
        self.stop()

    def __enter__(self) -> "ProcessAudioTap":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --- async interface ---

    async def iter_chunks(self) -> AsyncIterator[bytes]:
        """
        Async generator that yields PCM chunks as bytes.
        """
        loop = asyncio.get_running_loop()

        while True:
            # blocking queue.get() をスレッドプールで回す
            chunk = await loop.run_in_executor(None, self._async_queue.get)
            if chunk is None:  # sentinel
                break
            yield chunk

    # --- internal worker ---

    def _worker(self) -> None:
        assert self._handle is not None
        while not self._stop_event.is_set():
            pcm = _native.read_stream(self._handle, self._cfg.frames_per_buffer)
            if not pcm:
                continue

            # callback
            if self._on_data is not None:
                try:
                    self._on_data(pcm, self._cfg.frames_per_buffer)
                except Exception:
                    # ログは呼び出し側で差し込む余地を残す
                    pass

            # async 用にも流しておく
            try:
                self._async_queue.put_nowait(pcm)
            except queue.Full:
                # 落とす（リアルタイム重視）
                pass

        # 終了シグナル
        try:
            self._async_queue.put_nowait(None)  # type: ignore[arg-type]
        except queue.Full:
            pass