from __future__ import annotations

from dataclasses import dataclass
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

AudioCallback = Callable[[bytes, int], None]  # (pcm_bytes, num_frames)


@dataclass
class StreamConfig:
    sample_rate: int = 44100   # Hz
    channels: int = 2
    sample_width: int = 2  # Bytes per sample (2 = 16-bit)
    # NOTE:
    # 現状 backend 側でバッファサイズは制御していないので
    # frames_per_buffer は「論理的なサイズ」として扱うだけ。
    frames_per_buffer: int = 480  # 10ms @ 48kHz


class ProcessAudioCapture:
    """
    High-level API for process-specific audio capture.

    Supports multiple platforms:
    - Windows: WASAPI Process Loopback (fully implemented)
    - Linux: PulseAudio/PipeWire (under development)
    - macOS: Core Audio (planned, not yet implemented)

    Usage:
    - Callback mode: start(on_data=callback)
    - Async mode: async for chunk in tap.iter_chunks()
    """

    def __init__(
        self,
        pid: int,
        config: StreamConfig | None = None,
        on_data: Optional[AudioCallback] = None,
    ) -> None:
        self._pid = pid
        self._on_data = on_data

        # Declare backend type
        self._backend: AudioBackend

        # If config is None, backend will use native format (no conversion)
        # Otherwise, backend will convert to the specified format
        if config is None:
            # Create a temporary backend to get native format
            temp_backend = get_backend(
                pid=pid,
                sample_rate=44100,  # Default values (will be replaced)
                channels=2,
                sample_width=2,
            )
            native_format = temp_backend.get_format()

            # Extract and validate format values
            sample_rate_val = native_format['sample_rate']
            channels_val = native_format['channels']
            bits_per_sample_val = native_format['bits_per_sample']

            # Type guard: ensure we have int values
            assert isinstance(sample_rate_val, int), f"Expected int for sample_rate, got {type(sample_rate_val)}"
            assert isinstance(channels_val, int), f"Expected int for channels, got {type(channels_val)}"
            assert isinstance(bits_per_sample_val, int), f"Expected int for bits_per_sample, got {type(bits_per_sample_val)}"

            sample_rate = sample_rate_val
            channels = channels_val
            bits_per_sample = bits_per_sample_val

            # Create StreamConfig from native format
            self._cfg = StreamConfig(
                sample_rate=sample_rate,
                channels=channels,
                frames_per_buffer=int(sample_rate * 0.01),  # 10ms
            )

            # Re-create backend with native format (no conversion needed)
            self._backend = get_backend(
                pid=pid,
                sample_rate=self._cfg.sample_rate,
                channels=self._cfg.channels,
                sample_width=bits_per_sample // 8,
            )
            logger.debug(
                f"Using native format: {self._cfg.sample_rate}Hz, "
                f"{self._cfg.channels}ch, {native_format['bits_per_sample']}bit"
            )
        else:
            self._cfg = config
            # Get platform-specific backend with specified format
            self._backend = get_backend(
                pid=pid,
                sample_rate=self._cfg.sample_rate,
                channels=self._cfg.channels,
                sample_width=2,  # 16-bit = 2 bytes
            )

        logger.debug(f"Using backend: {type(self._backend).__name__}")

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

    @property
    def config(self) -> StreamConfig:
        """Get the stream configuration (note: does not affect native backend)."""
        return self._cfg

    # --- utility methods ------------------------------------------------

    def set_callback(self, callback: Optional[AudioCallback]) -> None:
        """
        Change the audio data callback.

        Args:
            callback: New callback function, or None to remove callback
        """
        self._on_data = callback

    def get_format(self) -> dict[str, int]:
        """
        Get audio format information from the native backend.

        Returns:
            Dictionary with keys:
            - 'sample_rate': Sample rate in Hz (e.g., 44100)
            - 'channels': Number of channels (e.g., 2 for stereo)
            - 'bits_per_sample': Bits per sample (e.g., 16)
        """
        fmt = self._backend.get_format()

        # Extract and validate format values
        sample_rate_val = fmt['sample_rate']
        channels_val = fmt['channels']
        bits_per_sample_val = fmt['bits_per_sample']

        # Type guard: ensure we have int values
        assert isinstance(sample_rate_val, int), f"Expected int for sample_rate, got {type(sample_rate_val)}"
        assert isinstance(channels_val, int), f"Expected int for channels, got {type(channels_val)}"
        assert isinstance(bits_per_sample_val, int), f"Expected int for bits_per_sample, got {type(bits_per_sample_val)}"

        # Return only int values for basic format info
        return {
            'sample_rate': sample_rate_val,
            'channels': channels_val,
            'bits_per_sample': bits_per_sample_val,
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
        while not self._stop_event.is_set():
            try:
                data = self._backend.read()
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
