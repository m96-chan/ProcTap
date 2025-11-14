from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, AsyncIterator
import threading
import queue
import asyncio
import logging

logger = logging.getLogger(__name__)

# -------------------------------
# Native backend import
# -------------------------------

try:
    # C++ extension backend (required)
    from ._native import ProcessLoopback as _NativeLoopback  # type: ignore[attr-defined]
except ImportError as e:
    raise ImportError(
        "Native extension (_native) could not be imported. "
        "Please build the extension with: pip install -e .\n"
        f"Original error: {e}"
    ) from e

AudioCallback = Callable[[bytes, int], None]  # (pcm_bytes, num_frames)


@dataclass
class StreamConfig:
    sample_rate: int = 48000
    channels: int = 2
    # NOTE:
    # 現状 backend 側でバッファサイズは制御していないので
    # frames_per_buffer は「論理的なサイズ」として扱うだけ。
    frames_per_buffer: int = 480  # 10ms @ 48kHz


class _BackendWrapper:
    """
    C++ native backend への薄いラッパー。

    提供するインターフェース:
        - initialize() -> bool
        - start_capture() -> bool
        - stop_capture() -> bool
        - cleanup() -> None
        - read_data() -> bytes
    """

    def __init__(self, pid: int) -> None:
        self._pid = pid
        logger.debug("Using native backend ProcessLoopback (C++ extension)")
        self._backend = _NativeLoopback(pid)

    def initialize(self) -> bool:
        # C++ 側は __init__ の時点で初期化が済んでいる前提なので True を返すだけ
        return True

    def start_capture(self) -> bool:
        self._backend.start()
        return True

    def stop_capture(self) -> bool:
        self._backend.stop()
        return True

    def cleanup(self) -> None:
        # C++ 側は dealloc で後片付けされるので特に何もしない
        pass

    def read_data(self) -> bytes:
        """
        ネイティブバックエンドからデータを読み取る。
        データがない場合は空のbytesを返す。
        """
        data = self._backend.read()
        if not data:
            return b""
        return data


class ProcessAudioTap:
    """
    High-level API wrapping WASAPI process loopback capture.

    - プロセスID単位でのループバックキャプチャ
    - コールバック登録 or async イテレータで PCM を受け取る
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

        self._backend = _BackendWrapper(pid)

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._async_queue: "queue.Queue[bytes | None]" = queue.Queue()

    # --- public API -----------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            # すでに start 済みなら何もしない
            return

        ok = self._backend.initialize()
        if not ok:
            raise RuntimeError("Failed to initialize WASAPI backend")

        ok = self._backend.start_capture()
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
            self._backend.stop_capture()
        except Exception:
            logger.exception("Error while stopping capture")

        try:
            self._backend.cleanup()
        except Exception:
            logger.exception("Error during backend cleanup")

    def close(self) -> None:
        self.stop()

    def __enter__(self) -> "ProcessAudioTap":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --- async interface ------------------------------------------------

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

    # --- worker thread --------------------------------------------------

    def _worker(self) -> None:
        """
        Loop:
            data = backend.read_data()
            -> callback
            -> async_queue
        """
        while not self._stop_event.is_set():
            try:
                data = self._backend.read_data()
            except Exception:
                logger.exception("Error reading data from backend")
                continue

            if not data:
                # パケットがまだ無いケース。ここで sleep 入れるかは後で調整。
                continue

            # callback
            if self._on_data is not None:
                try:
                    # frames 数は backend から直接取れないので、とりあえず -1 を渡す。
                    # TODO: _backend.get_format() を見て frame 数を計算する改善余地あり。
                    self._on_data(data, -1)
                except Exception:
                    logger.exception("Error in audio callback")

            # async queue
            try:
                self._async_queue.put_nowait(data)
            except queue.Full:
                # リアルタイム性重視なので捨てる
                pass

        # 終了シグナル
        try:
            self._async_queue.put_nowait(None)
        except queue.Full:
            pass
