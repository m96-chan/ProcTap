from __future__ import annotations

from typing import Callable, Optional, AsyncIterator, Literal
import threading
import queue
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# -------------------------------
# Backend import (platform-specific)
# -------------------------------

from .backends import get_backend
from .backends.base import (
    AudioBackend,
    STANDARD_SAMPLE_RATE,
    STANDARD_CHANNELS,
    STANDARD_FORMAT,
    STANDARD_SAMPLE_WIDTH,
)

AudioCallback = Callable[[bytes, int], None]  # (pcm_bytes, num_frames)

# Resample quality modes
ResampleQuality = Literal['best', 'medium', 'fast']


class ProcessAudioCapture:
    """
    High-level API for process-specific audio capture.

    All captured audio is returned in standard format:
    - Sample rate: 48000 Hz
    - Channels: 2 (stereo)
    - Sample format: float32 (IEEE 754, normalized to [-1.0, 1.0])

    Supports multiple platforms:
    - Windows: WASAPI Process Loopback (fully implemented)
    - Linux: PulseAudio/PipeWire (experimental)
    - macOS: Core Audio (experimental)

    Usage:
    - Callback mode: start(on_data=callback)
    - Async mode: async for chunk in tap.iter_chunks()
    """

    def __init__(
        self,
        pid: int,
        on_data: Optional[AudioCallback] = None,
        resample_quality: ResampleQuality = 'best',
    ) -> None:
        """
        Initialize process audio capture.

        Args:
            pid: Process ID to capture audio from
            on_data: Optional callback for audio data (callback mode)
            resample_quality: Resampling quality mode when format conversion is needed
                - 'best': Highest quality, ~1.3-1.4ms latency (default)
                - 'medium': Medium quality, ~0.7-0.9ms latency
                - 'fast': Lowest quality, ~0.3-0.5ms latency
        """
        self._pid = pid
        self._on_data = on_data
        self._resample_quality = resample_quality

        # Get platform-specific backend (always returns standard format)
        self._backend: AudioBackend = get_backend(pid=pid, resample_quality=resample_quality)

        logger.debug(f"Using backend: {type(self._backend).__name__}")
        logger.debug(f"Standard format: {STANDARD_SAMPLE_RATE}Hz, {STANDARD_CHANNELS}ch, {STANDARD_FORMAT}")

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._async_queue: "queue.Queue[bytes | None]" = queue.Queue()

    # --- public API -----------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            # すでに start 済みなら何もしない
            return

        # Start platform-specific backend
        self._backend.start()

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

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

    def __exit__(self, _exc_type, _exc, _tb) -> None:
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

    @property
    def format(self) -> dict[str, int | str]:
        """
        Get the audio format information (always returns standard format).

        Returns:
            Dictionary with:
            - 'sample_rate': 48000
            - 'channels': 2
            - 'bits_per_sample': 32
            - 'sample_format': 'float32'
        """
        return {
            'sample_rate': STANDARD_SAMPLE_RATE,
            'channels': STANDARD_CHANNELS,
            'bits_per_sample': STANDARD_SAMPLE_WIDTH * 8,
            'sample_format': STANDARD_FORMAT,
        }

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
        Get audio format information from the backend.

        Returns:
            Dictionary with keys:
            - 'sample_rate': 48000
            - 'channels': 2
            - 'bits_per_sample': 32
            - 'sample_format': 'float32'
        """
        return self._backend.get_format()

    def read(self, timeout: float = 1.0) -> Optional[bytes]:
        """
        Synchronous API: Read one audio chunk (blocking).

        Args:
            timeout: Maximum time to wait for data in seconds

        Returns:
            PCM audio data as bytes (48kHz/2ch/float32), or None if timeout or no data

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
        All chunks are in standard format: 48kHz/2ch/float32.
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
        while not self._stop_event.is_set():
            try:
                data = self._backend.read()
            except Exception:
                logger.exception("Error reading data from backend")
                continue

            if not data:
                # No data available yet, sleep briefly to reduce CPU usage
                time.sleep(0.001)  # 1ms sleep
                continue

            # callback
            if self._on_data is not None:
                try:
                    # frames 数は backend から直接取れないので、とりあえず -1 を渡す。
                    # TODO: calculate frame count from data length and format
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
