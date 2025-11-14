from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional, AsyncIterator
import threading
import queue
import asyncio
import logging

from ._backend_wasapi import WASAPIProcessLoopback  # ← さっきコピーしたクラス

logger = logging.getLogger(__name__)

AudioCallback = Callable[[bytes, int], None]  # (pcm_bytes, num_frames)

@dataclass
class StreamConfig:
    sample_rate: int = 48000
    channels: int = 2
    # WASAPIProcessLoopback は「フレーム数の指定」はしてないので、
    # ここはあくまで「論理的なフレームサイズ」の扱いにしておく
    frames_per_buffer: int = 480  # 10ms @ 48kHz


class ProcessAudioTap:
    """
    High-level API wrapping WASAPIProcessLoopback.
    """

    def __init__(
        self,
        pid: int,
        config: StreamConfig | None = None,
        on_data: Optional[AudioCallback] = None,
    ) -> None:
        self._pid = pid
        self._cfg = config or StreamConfig()
        self._on_data = on_data

        self._loopback = WASAPIProcessLoopback(process_id=pid)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._async_queue: "queue.Queue[bytes]" = queue.Queue()

    # --- public API ---

    def start(self) -> None:
        if self._thread is not None:
            return

        ok = self._loopback.initialize()
        if not ok:
            raise RuntimeError("Failed to initialize WASAPI loopback")

        ok = self._loopback.start_capture()
        if not ok:
            raise RuntimeError("Failed to start WASAPI capture")

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        try:
            self._loopback.stop_capture()
        except Exception:
            logger.exception("Error while stopping capture")

        try:
            self._loopback.cleanup()
        except Exception:
            logger.exception("Error during WASAPI cleanup")

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
            chunk = await loop.run_in_executor(None, self._async_queue.get)
            if chunk is None:  # sentinel
                break
            yield chunk

    # --- worker thread ---

    def _worker(self) -> None:
        """
        Loop:
            data = loopback.read_data()
            -> callback
            -> async_queue
        """
        while not self._stop_event.is_set():
            try:
                data = self._loopback.read_data()
            except Exception:
                logger.exception("Error reading data from WASAPI")
                continue

            if not data:
                # no packet yet → small sleepも検討してもよい
                continue

            # callback
            if self._on_data is not None:
                try:
                    self._on_data(data, -1)  # frame count は backend から取れてないので -1
                except Exception:
                    logger.exception("Error in audio callback")

            # async queue
            try:
                self._async_queue.put_nowait(data)
            except queue.Full:
                # drop oldest or ignore; for now just drop
                pass

        # 終了シグナル
        try:
            self._async_queue.put_nowait(None)  # type: ignore[arg-type]
        except queue.Full:
            pass
