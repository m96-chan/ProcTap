"""
macOS audio capture backend using native C extension (Phase 4).

This backend uses a native Objective-C extension for maximum performance,
targeting <500ms initial latency.

Optimizations:
- No subprocess overhead (~37ms saved)
- Pre-allocated ring buffers
- Optimized aggregate device creation
- Lock-free queue for audio data

Requirements:
- macOS 14.4+ (Sonoma)
- Native _native_macos extension module

Performance Target: <500ms initial latency (vs 625ms with Swift CLI)
"""

from __future__ import annotations

from typing import Optional, Callable
import logging
import time

from .base import AudioBackend

logger = logging.getLogger(__name__)

# Try to import native extension
try:
    import proctap._native_macos as _native  # type: ignore[import-untyped]
    NATIVE_AVAILABLE = True
except ImportError:
    NATIVE_AVAILABLE = False
    logger.warning("Native macOS extension not available")


# Type alias for audio callback
AudioCallback = Callable[[bytes, int], None]


class MacOSNativeBackend(AudioBackend):
    """
    macOS native backend using C extension for Core Audio Process Tap.

    This backend provides the lowest latency audio capture on macOS by
    directly calling Core Audio APIs from native code.
    """

    def __init__(
        self,
        pid: int,
        sample_rate: int = 48000,
        channels: int = 2,
        sample_width: int = 2,
        include_pids: Optional[list[int]] = None,
        exclude_pids: Optional[list[int]] = None,
    ) -> None:
        """
        Initialize macOS native backend.

        Args:
            pid: Target process ID (added to include_pids if not already specified)
            sample_rate: Sample rate in Hz (default: 48000)
            channels: Number of channels (1=mono, 2=stereo, default: 2)
            sample_width: Bytes per sample (default: 2 for 16-bit)
            include_pids: List of PIDs to capture (if None, captures from pid)
            exclude_pids: List of PIDs to exclude from capture
        """
        if not NATIVE_AVAILABLE:
            raise RuntimeError(
                "Native macOS extension not available. "
                "Please rebuild with: pip install -e . --force-reinstall"
            )

        super().__init__(pid)

        # Store audio format parameters
        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_width = sample_width

        # Build include PIDs list
        if include_pids is not None:
            self._include_pids = include_pids
        elif pid > 0:
            self._include_pids = [pid]
        else:
            self._include_pids = []

        self._exclude_pids = exclude_pids if exclude_pids is not None else []

        # Native state
        self._tap_handle = None
        self._is_capturing = False
        self._callback: Optional[AudioCallback] = None

        logger.info(
            f"MacOSNativeBackend initialized: {sample_rate}Hz, {channels}ch, "
            f"include_pids={self._include_pids}, exclude_pids={self._exclude_pids}"
        )

    def start(self, on_data: Optional[AudioCallback] = None) -> None:
        """
        Start audio capture.

        Args:
            on_data: Optional callback for audio data. Signature: (data: bytes, frame_count: int) -> None
                     If None, use read() method to retrieve data.
        """
        if self._is_capturing:
            logger.warning("Already capturing")
            return

        self._callback = on_data

        # Track initialization time for benchmarking
        start_time = time.perf_counter()

        try:
            # Create process tap (optimized C implementation)
            bits_per_sample = self._sample_width * 8
            self._tap_handle = _native.create_tap(
                include_pids=self._include_pids,
                exclude_pids=self._exclude_pids,
                sample_rate=self._sample_rate,
                channels=self._channels,
                bits_per_sample=bits_per_sample,
            )

            # Start audio capture
            _native.start_tap(self._tap_handle)
            self._is_capturing = True

            init_time = (time.perf_counter() - start_time) * 1000
            logger.info(f"Audio capture started (initialization: {init_time:.2f}ms)")

            # If callback mode, start reading thread
            if self._callback:
                import threading

                self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
                self._reader_thread.start()

        except Exception as e:
            logger.error(f"Failed to start capture: {e}")
            if self._tap_handle:
                try:
                    _native.destroy_tap(self._tap_handle)
                except:
                    pass
                self._tap_handle = None
            raise

    def _reader_loop(self) -> None:
        """Background thread for callback mode."""
        logger.debug("Reader loop started")

        while self._is_capturing and self._callback:
            try:
                # Read available data (non-blocking)
                data = _native.read_tap(self._tap_handle, max_bytes=8192)

                if data and len(data) > 0:
                    # Calculate frame count
                    bytes_per_frame = self._channels * self._sample_width
                    frame_count = len(data) // bytes_per_frame

                    # Call user callback
                    self._callback(data, frame_count)
                else:
                    # No data available, sleep briefly to avoid busy-waiting
                    time.sleep(0.001)  # 1ms

            except Exception as e:
                logger.error(f"Error in reader loop: {e}")
                break

        logger.debug("Reader loop stopped")

    def stop(self) -> None:
        """Stop audio capture and cleanup resources."""
        if not self._is_capturing:
            return

        logger.info("Stopping audio capture...")
        self._is_capturing = False

        if self._tap_handle:
            try:
                _native.stop_tap(self._tap_handle)
                _native.destroy_tap(self._tap_handle)
            except Exception as e:
                logger.error(f"Error stopping tap: {e}")
            finally:
                self._tap_handle = None

        logger.info("Audio capture stopped")

    def read(self, max_bytes: int = 8192) -> bytes:
        """
        Read captured audio data.

        Args:
            max_bytes: Maximum bytes to read

        Returns:
            Audio data as bytes (empty if no data available)

        Raises:
            RuntimeError: If not currently capturing
        """
        if not self._is_capturing:
            raise RuntimeError("Not currently capturing")

        if not self._tap_handle:
            return b""

        try:
            return _native.read_tap(self._tap_handle, max_bytes=max_bytes)
        except Exception as e:
            logger.error(f"Error reading data: {e}")
            return b""

    def get_format(self) -> dict:
        """
        Get current audio format.

        Returns:
            Dictionary with format info: {sample_rate, channels, bits_per_sample}
        """
        if self._tap_handle:
            try:
                return _native.get_format(self._tap_handle)
            except Exception as e:
                logger.error(f"Error getting format: {e}")

        # Fallback to configured values
        return {
            "sample_rate": self._sample_rate,
            "channels": self._channels,
            "bits_per_sample": self._sample_width * 8,
        }

    def __del__(self) -> None:
        """Cleanup on deletion."""
        if self._is_capturing:
            self.stop()


def is_available() -> bool:
    """
    Check if native macOS backend is available.

    Returns:
        True if native extension is available and macOS version is supported
    """
    if not NATIVE_AVAILABLE:
        return False

    # Check macOS version (requires 14.4+)
    import platform

    version = platform.mac_ver()[0]
    if not version:
        return False

    try:
        major, minor = map(int, version.split(".")[:2])
        if major < 14 or (major == 14 and minor < 4):
            logger.warning(f"macOS {version} detected, requires 14.4+")
            return False
    except:
        return False

    return True
