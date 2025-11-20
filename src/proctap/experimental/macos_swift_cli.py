"""
macOS audio capture backend using Core Audio Process Tap API.

This module provides process-specific audio capture on macOS 14.4+ using
the Core Audio Process Tap API via a Swift CLI helper process.

Requirements:
- macOS 14.4 (Sonoma) or later
- Audio capture permission (NSAudioCaptureUsageDescription)
- Swift CLI helper binary (proctap-macos)

STATUS: Implemented for macOS 14.4+
"""

from __future__ import annotations

from typing import Optional
import logging
import subprocess
import os
import sys
import platform
import queue
import threading
import struct
from pathlib import Path

from .base import AudioBackend  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


def get_macos_version() -> tuple[int, int, int]:
    """
    Get macOS version as tuple (major, minor, patch).

    Returns:
        Tuple of (major, minor, patch) version numbers

    Example:
        (14, 4, 0) for macOS 14.4.0 Sonoma
    """
    try:
        version_str = platform.mac_ver()[0]
        parts = version_str.split('.')
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except Exception as e:
        logger.warning(f"Failed to parse macOS version: {e}")
        return (0, 0, 0)


def supports_process_tap() -> bool:
    """
    Check if the current macOS version supports Process Tap API.

    Returns:
        True if macOS 14.4+, False otherwise
    """
    major, minor, _ = get_macos_version()
    return major > 14 or (major == 14 and minor >= 4)


def find_helper_binary() -> Optional[Path]:
    """
    Find the proctap-macos Swift CLI helper binary.

    Searches in the following locations:
    1. Same directory as this module
    2. Package data directory
    3. System PATH

    Returns:
        Path to helper binary, or None if not found
    """
    # Try relative to this module
    module_dir = Path(__file__).parent
    candidates = [
        module_dir / "proctap-macos",
        module_dir.parent / "bin" / "proctap-macos",
        module_dir.parent.parent / "bin" / "proctap-macos",
    ]

    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            logger.debug(f"Found helper binary: {candidate}")
            return candidate

    # Try PATH
    import shutil
    path_binary = shutil.which("proctap-macos")
    if path_binary:
        logger.debug(f"Found helper binary in PATH: {path_binary}")
        return Path(path_binary)

    return None


class MacOSBackend(AudioBackend):
    """
    macOS implementation using Core Audio Process Tap API.

    This backend uses a Swift CLI helper (proctap-macos) that interfaces with
    Core Audio Process Tap API (macOS 14.4+) to capture audio from specific
    processes or all processes except excluded ones.

    The helper outputs raw PCM audio to stdout, which is read by this Python backend.

    Requirements:
    - macOS 14.4 (Sonoma) or later
    - Swift CLI helper binary (proctap-macos)
    - Audio capture permission

    Features:
    - Capture from specific PIDs (include_pids)
    - Exclude specific PIDs from capture (exclude_pids)
    - Support for multiple processes simultaneously

    Limitations:
    - Requires macOS 14.4+
    - Target process must be actively playing audio
    - Requires user permission for audio capture
    - Max 8 PIDs for include/exclude lists
    """

    def __init__(
        self,
        pid: int,
        sample_rate: int = 48000,
        channels: int = 2,
        sample_width: int = 2,
        include_pids: Optional[list[int]] = None,
        exclude_pids: Optional[list[int]] = None,
        device: Optional[str] = None,
    ) -> None:
        """
        Initialize macOS backend.

        Args:
            pid: Main process ID to capture audio from (for backward compatibility)
            sample_rate: Sample rate in Hz (default: 48000)
            channels: Number of channels (default: 2 for stereo)
            sample_width: Bytes per sample (default: 2 for 16-bit)
            include_pids: List of PIDs to include (optional, overrides pid if provided)
            exclude_pids: List of PIDs to exclude (optional)
            device: Output device UID or "default" (optional)

        Raises:
            RuntimeError: If macOS version < 14.4 or helper binary not found

        Examples:
            # Capture from specific process
            backend = MacOSBackend(pid=1234)

            # Capture from multiple processes
            backend = MacOSBackend(pid=1234, include_pids=[1234, 5678])

            # Capture all except specific processes
            backend = MacOSBackend(pid=0, exclude_pids=[5678])

            # Capture game + voice, exclude music
            backend = MacOSBackend(pid=1234, include_pids=[1234, 2222], exclude_pids=[5678])
        """
        super().__init__(pid)

        # Build include PIDs list
        if include_pids is not None:
            self._include_pids = include_pids
        elif pid > 0:
            # Backward compatibility: use pid as single include
            self._include_pids = [pid]
        else:
            # No include list: capture all processes
            self._include_pids = []

        self._exclude_pids = exclude_pids if exclude_pids is not None else []
        self._device = device

        # Check macOS version
        if not supports_process_tap():
            major, minor, patch = get_macos_version()
            raise RuntimeError(
                f"macOS {major}.{minor}.{patch} does not support Process Tap API. "
                "Requires macOS 14.4 (Sonoma) or later."
            )

        # Find helper binary
        self._helper_path = find_helper_binary()
        if self._helper_path is None:
            raise RuntimeError(
                "Swift CLI helper 'proctap-macos' not found. "
                "Please ensure the helper binary is installed and in PATH, "
                "or located in the package directory."
            )

        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_width = sample_width
        self._bits_per_sample = sample_width * 8

        self._process: Optional[subprocess.Popen] = None
        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False

        # Log configuration
        if self._include_pids:
            logger.info(
                f"Initialized MacOSBackend for PIDs {self._include_pids} "
                f"({sample_rate}Hz, {channels}ch, {self._bits_per_sample}bit)"
            )
        else:
            logger.info(
                f"Initialized MacOSBackend for all processes "
                f"({sample_rate}Hz, {channels}ch, {self._bits_per_sample}bit)"
            )

        if self._exclude_pids:
            logger.info(f"Excluding PIDs: {self._exclude_pids}")

    def start(self) -> None:
        """
        Start audio capture from the target process(es).

        Raises:
            RuntimeError: If capture fails to start
        """
        if self._is_running:
            logger.warning("Audio capture is already running")
            return

        try:
            # Build command to launch Swift helper
            cmd = [
                str(self._helper_path),
                "--sample-rate", str(self._sample_rate),
                "--channels", str(self._channels),
            ]

            # Add include PIDs if specified
            if self._include_pids:
                cmd.extend(["--include-pids", ",".join(map(str, self._include_pids))])

            # Add exclude PIDs if specified
            if self._exclude_pids:
                cmd.extend(["--exclude-pids", ",".join(map(str, self._exclude_pids))])

            # Add device if specified
            if self._device:
                cmd.extend(["--device", self._device])

            logger.debug(f"Launching helper: {' '.join(cmd)}")

            # Start helper process
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # Unbuffered
            )

            # Start reader thread
            self._stop_event.clear()
            self._reader_thread = threading.Thread(
                target=self._reader_worker,
                daemon=True
            )
            self._reader_thread.start()

            self._is_running = True
            logger.info(f"Started audio capture for PID {self._pid}")

        except Exception as e:
            self._is_running = False
            if self._process:
                self._process.terminate()
                self._process = None
            raise RuntimeError(f"Failed to start audio capture: {e}") from e

    def stop(self) -> None:
        """Stop audio capture."""
        if not self._is_running:
            return

        self._stop_event.set()
        self._is_running = False

        # Wait for reader thread
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)

        # Terminate helper process
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            finally:
                self._process = None

        logger.info("Stopped audio capture")

    def read(self) -> Optional[bytes]:
        """
        Read audio data from the capture buffer.

        Returns:
            PCM audio data as bytes, or None if no data is available
        """
        if not self._is_running:
            return None

        try:
            return self._audio_queue.get(timeout=0.1)
        except queue.Empty:
            return None

    def get_format(self) -> dict[str, int | object]:
        """
        Get audio format information.

        Returns:
            Dictionary with 'sample_rate', 'channels', 'bits_per_sample'
        """
        return {
            'sample_rate': self._sample_rate,
            'channels': self._channels,
            'bits_per_sample': self._bits_per_sample,
        }

    def close(self) -> None:
        """Clean up resources."""
        self.stop()

    def __del__(self) -> None:
        """Destructor to ensure cleanup."""
        try:
            self.close()
        except:
            pass

    def _reader_worker(self) -> None:
        """
        Worker thread that reads PCM data from helper process stdout.

        Reads audio in chunks and puts them into the queue.
        """
        if not self._process or not self._process.stdout:
            logger.error("Helper process not started")
            return

        try:
            # Calculate chunk size (10ms of audio)
            chunk_frames = int(self._sample_rate * 0.01)  # 10ms
            chunk_bytes = chunk_frames * self._channels * self._sample_width

            logger.debug(f"Reader worker started (chunk size: {chunk_bytes} bytes)")

            while not self._stop_event.is_set():
                try:
                    # Read chunk from stdout
                    chunk = self._process.stdout.read(chunk_bytes)

                    if not chunk:
                        # EOF or process terminated
                        logger.debug("Helper process output ended")
                        break

                    if len(chunk) == chunk_bytes:
                        # Put chunk in queue
                        try:
                            self._audio_queue.put_nowait(chunk)
                        except queue.Full:
                            # Drop old frames if queue is full
                            try:
                                self._audio_queue.get_nowait()
                                self._audio_queue.put_nowait(chunk)
                            except:
                                pass

                except Exception as e:
                    if not self._stop_event.is_set():
                        logger.error(f"Error reading audio data: {e}")
                    break

            logger.debug("Reader worker stopped")

        except Exception as e:
            logger.error(f"Reader worker error: {e}")

        finally:
            # Check for errors from helper process
            if self._process and self._process.poll() is not None and self._process.stderr:
                stderr_output = self._process.stderr.read().decode('utf-8', errors='ignore')
                if stderr_output:
                    logger.error(f"Helper process error: {stderr_output}")


# Development notes:
#
# This implementation uses a Swift CLI helper binary that wraps Core Audio Process Tap API.
# The helper is a separate executable built with SwiftPM.
#
# Swift helper responsibilities:
# - Use kAudioHardwarePropertyTranslatePIDToProcessObject to get process object
# - Create CATapDescription with target process
# - Call AudioHardwareCreateProcessTap to create tap
# - Set up audio output format (16-bit PCM)
# - Stream PCM to stdout in continuous chunks
#
# Python backend responsibilities:
# - Launch helper process with appropriate arguments
# - Read PCM from helper's stdout
# - Buffer audio in queue for consumption
# - Handle process lifecycle and cleanup
#
# Advantages of this approach:
# - Clean separation of Swift/ObjC code from Python
# - No need for PyObjC or ctypes complexity
# - Helper can be code-signed independently
# - Easy to test Swift code separately
#
# Future improvements:
# - Add support for dynamic format negotiation
# - Implement error recovery and reconnection
# - Add metrics and monitoring
# - Optimize buffer management
