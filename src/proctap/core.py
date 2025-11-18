from __future__ import annotations

from typing import Callable, Optional, AsyncIterator
import threading
import queue
import asyncio
import logging

logger = logging.getLogger(__name__)

# -------------------------------
# Backend import (platform-specific)
# -------------------------------

from .backends import get_backend
from .backends.base import AudioBackend
from .format import ResamplingQuality, FIXED_AUDIO_FORMAT, get_frame_count

AudioCallback = Callable[[bytes, int], None]  # (pcm_bytes, num_frames)


class ProcessAudioCapture:
    """
    High-level API for process-specific audio capture.

    All audio output is standardized to:
    - Sample rate: 48,000 Hz
    - Channels: 2 (stereo)
    - Format: float32, normalized to [-1.0, 1.0]

    Supports multiple platforms:
    - Windows: WASAPI Process Loopback (fully implemented)
    - Linux: PulseAudio/PipeWire (fully implemented)
    - macOS: Core Audio Process Tap (experimental)

    Usage:
    - Callback mode: start(on_data=callback)
    - Async mode: async for chunk in tap.iter_chunks()
    """

    def __init__(
        self,
        pid: int,
        on_data: Optional[AudioCallback] = None,
    ) -> None:
        self._pid = pid
        self._on_data = on_data

        # All audio is converted to the standardized format
        logger.debug(f"Using standardized audio format: {FIXED_AUDIO_FORMAT.sample_rate}Hz, {FIXED_AUDIO_FORMAT.channels}ch, {FIXED_AUDIO_FORMAT.sample_format}")
        
        # Get platform-specific backend with fixed format
        self._backend = get_backend(
            pid=pid,
            sample_rate=FIXED_AUDIO_FORMAT.sample_rate,
            channels=FIXED_AUDIO_FORMAT.channels,
            sample_width=4,  # 4 bytes for float32
            sample_format=FIXED_AUDIO_FORMAT.sample_format,
        )

        logger.debug(f"Using backend: {type(self._backend).__name__}")

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._async_queue: "queue.Queue[bytes | None]" = queue.Queue()

    # --- public API -----------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            # すでに start 済みなら何もしない
            logger.debug("Already started, skipping")
            return

        logger.debug("Starting ProcessAudioCapture...")

        # Start platform-specific backend
        self._backend.start()

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

        logger.debug(f"Worker thread started: {self._thread.name}, is_alive: {self._thread.is_alive()}")

    def stop(self) -> None:
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        try:
            self._backend.stop()
        except Exception:
            logger.exception("Error while stopping capture")

    def close(self) -> None:
        self.stop()

    def __enter__(self) -> "ProcessAudioCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --- properties -----------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Check if audio capture is currently running."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def pid(self) -> int:
        """Get the target process ID."""
        return self._pid

    # --- utility methods ------------------------------------------------

    def set_callback(self, callback: Optional[AudioCallback]) -> None:
        """
        Change the audio data callback.

        Args:
            callback: New callback function, or None to remove callback
        """
        self._on_data = callback

    def get_format(self) -> dict[str, int | str]:
        """
        Get audio format information.

        Returns:
            Dictionary with standardized format information:
            - 'sample_rate': 48000 Hz
            - 'channels': 2 (stereo)
            - 'sample_format': 'f32' (float32)
            - 'bits_per_sample': 32
        """
        return {
            'sample_rate': FIXED_AUDIO_FORMAT.sample_rate,
            'channels': FIXED_AUDIO_FORMAT.channels,
            'sample_format': FIXED_AUDIO_FORMAT.sample_format,
            'bits_per_sample': 32,  # float32
        }

    def read(self, timeout: float = 1.0) -> Optional[bytes]:
        """
        Synchronous API: Read one audio chunk (blocking).

        Args:
            timeout: Maximum time to wait for data in seconds

        Returns:
            PCM audio data as bytes, or None if timeout or no data

        Note:
            This is a simple synchronous alternative to the async API.
            The capture must be started first with start().
        """
        if not self.is_running:
            raise RuntimeError("Capture is not running. Call start() first.")

        try:
            return self._async_queue.get(timeout=timeout)
        except queue.Empty:
            return None

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
            data = backend.read()
            -> callback
            -> async_queue
        """
        logger.debug(f"Worker thread started, on_data callback is {'set' if self._on_data else 'None'}")
        while not self._stop_event.is_set():
            try:
                data = self._backend.read()
            except Exception:
                logger.exception("Error reading data from backend")
                continue

            if not data:
                # パケットがまだ無いケース。短時間 sleep してCPU消費を抑える
                import time
                time.sleep(0.01)  # 10ms sleep
                continue

            logger.debug(f"Received {len(data)} bytes from backend")

            # callback
            if self._on_data is not None:
                try:
                    # Calculate frames using standardized format
                    frames = get_frame_count(data)
                    logger.debug(f"Calling on_data callback with {len(data)} bytes ({frames} frames)")
                    self._on_data(data, frames)
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
