"""
macOS ScreenCaptureKit Backend for ProcTap

Uses ScreenCaptureKit API (macOS 13+) for bundleID-based audio capture.
This is the recommended approach for Apple Silicon Macs.

Requirements:
- macOS 13.0 (Ventura) or later
- Screen Recording permission (TCC)
- Swift helper binary (screencapture-audio)

IMPORTANT: Always returns audio in standard format (48kHz/2ch/float32)
"""

import subprocess
import queue
import threading
import logging
from pathlib import Path
from typing import Optional, Callable

from .base import (
    AudioBackend,
    STANDARD_SAMPLE_RATE,
    STANDARD_CHANNELS,
    STANDARD_FORMAT,
    STANDARD_SAMPLE_WIDTH,
    STANDARD_DTYPE,
)

log = logging.getLogger(__name__)


def find_screencapture_binary() -> Optional[Path]:
    """
    Find the screencapture-audio Swift helper binary.

    Search order:
    1. Bundled binary in package (src/proctap/bin/screencapture-audio) - for pip installs
    2. Development build: src/proctap/swift/screencapture-audio/.build/arm64-apple-macosx/release/
    3. Development build: src/proctap/swift/screencapture-audio/.build/arm64-apple-macosx/debug/
    4. Development build: src/proctap/swift/screencapture-audio/.build/x86_64-apple-macosx/release/ (Intel)
    5. Development build: src/proctap/swift/screencapture-audio/.build/x86_64-apple-macosx/debug/ (Intel)

    Returns:
        Path to binary if found, None otherwise
    """
    # First, check for bundled binary (package installation)
    bundled_binary = Path(__file__).parent.parent / "bin" / "screencapture-audio"
    if bundled_binary.exists() and bundled_binary.is_file():
        log.debug(f"Found bundled screencapture-audio at: {bundled_binary}")
        return bundled_binary

    # Get proctap package directory (assuming this file is at src/proctap/backends/)
    proctap_dir = Path(__file__).parent.parent

    # Check development builds (prioritize release builds for better performance)
    search_paths = [
        proctap_dir / "swift/screencapture-audio/.build/arm64-apple-macosx/release/screencapture-audio",
        proctap_dir / "swift/screencapture-audio/.build/arm64-apple-macosx/debug/screencapture-audio",
        proctap_dir / "swift/screencapture-audio/.build/x86_64-apple-macosx/release/screencapture-audio",
        proctap_dir / "swift/screencapture-audio/.build/x86_64-apple-macosx/debug/screencapture-audio",
    ]

    for path in search_paths:
        if path.exists() and path.is_file():
            log.debug(f"Found screencapture-audio at: {path}")
            return path

    log.error("screencapture-audio binary not found. Please build it first:")
    log.error("  cd src/proctap/swift/screencapture-audio && swift build")
    return None


def is_available() -> bool:
    """
    Check if ScreenCaptureKit backend is available.

    Returns:
        True if macOS 13+ and Swift helper binary exists
    """
    import platform
    import sys

    # Check macOS version
    if sys.platform != "darwin":
        return False

    # macOS 13.0 = Darwin 22.0
    darwin_version = int(platform.release().split(".")[0])
    if darwin_version < 22:
        log.debug(f"ScreenCaptureKit requires macOS 13+ (Darwin 22+), found Darwin {darwin_version}")
        return False

    # Check binary exists
    binary = find_screencapture_binary()
    return binary is not None


class ScreenCaptureBackend(AudioBackend):
    """
    ScreenCaptureKit backend for macOS 13+.

    Captures audio from applications by bundleID instead of PID.
    This is more stable and works on Apple Silicon without AMFI/SIP hacks.

    This backend always returns audio in the standard format:
    - 48000 Hz
    - 2 channels (stereo)
    - float32 (IEEE 754, normalized to [-1.0, 1.0])

    Note: bundleID is inferred from PID at initialization time.
    """

    def __init__(self, pid: int, resample_quality: str = 'best') -> None:
        """
        Initialize ScreenCaptureKit backend.

        Args:
            pid: Process ID (used to find bundleID)
            resample_quality: Resampling quality mode (unused, kept for API compatibility)

        Raises:
            ValueError: If bundleID cannot be determined for the given PID
            RuntimeError: If Swift helper binary is not found
        """
        super().__init__(pid)

        # Find bundleID from PID
        self.bundle_id = self._get_bundle_id_from_pid(pid)
        if not self.bundle_id:
            raise ValueError(f"Could not determine bundleID for PID {pid}")

        log.info(f"Using bundleID: {self.bundle_id} for PID {pid}")

        # Find Swift helper binary
        self.binary_path = find_screencapture_binary()
        if not self.binary_path:
            raise RuntimeError("screencapture-audio binary not found")

        # Subprocess and threading state
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue = queue.Queue(maxsize=100)
        self._callback: Optional[Callable[[bytes], None]] = None
        self._running = False

        log.info(
            f"ScreenCaptureKit backend initialized: "
            f"Native format is already standard (48kHz/2ch/float32) - no conversion needed"
        )

    def _get_bundle_id_from_pid(self, pid: int) -> Optional[str]:
        """
        Get application bundleID from process ID using lsappinfo.

        Args:
            pid: Process ID

        Returns:
            Bundle identifier string, or None if not found
        """
        try:
            # Use lsappinfo to get bundle ID
            result = subprocess.run(
                ["lsappinfo", "info", "-only", "bundleid", str(pid)],
                capture_output=True,
                text=True,
                timeout=2,
            )

            if result.returncode == 0:
                # Parse output formats:
                # - "bundleid="com.apple.Safari""  (old format)
                # - "CFBundleIdentifier"="com.hnc.Discord"  (new format)
                output = result.stdout.strip()

                # Try new format first
                if '"CFBundleIdentifier"=' in output:
                    bundle_id = output.split('"CFBundleIdentifier"=')[-1].strip('"')
                    if bundle_id and bundle_id != "NULL":
                        log.debug(f"Found bundleID via CFBundleIdentifier: {bundle_id}")
                        return bundle_id

                # Try old format
                if "bundleid=" in output:
                    bundle_id = output.split("bundleid=")[-1].strip('"')
                    if bundle_id and bundle_id != "NULL":
                        log.debug(f"Found bundleID via bundleid: {bundle_id}")
                        return bundle_id

            # Fallback: use ps + grep approach for command line apps
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True,
                text=True,
                timeout=2,
            )

            if result.returncode == 0:
                comm = result.stdout.strip()
                # Try to construct bundleID from executable name
                # This is a heuristic and may not always work
                if "/" in comm:
                    # Extract app name from path like /Applications/Safari.app/Contents/MacOS/Safari
                    if ".app/" in comm:
                        app_name = comm.split(".app/")[0].split("/")[-1]
                        # Common pattern: com.company.AppName
                        return f"com.apple.{app_name}"

            log.warning(f"Could not determine bundleID for PID {pid}")
            return None

        except Exception as e:
            log.error(f"Error getting bundleID for PID {pid}: {e}")
            return None

    def get_format(self) -> dict[str, int | str]:
        """
        Get audio format (always returns standard format).

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

    def _reader_worker(self):
        """
        Background thread that reads float32 PCM data from subprocess stdout.

        Reads raw float32 PCM data and either:
        - Calls the callback function directly (callback mode)
        - Puts data into queue (async iteration mode)
        """
        if not self._process or not self._process.stdout:
            return

        try:
            # Read in chunks (10ms of audio at a time for low latency)
            # Formula: bytes_per_chunk = sample_rate * channels * sample_width * duration
            chunk_duration_ms = 10
            bytes_per_chunk = int(
                STANDARD_SAMPLE_RATE * STANDARD_CHANNELS * STANDARD_SAMPLE_WIDTH * chunk_duration_ms / 1000
            )

            while self._running:
                data = self._process.stdout.read(bytes_per_chunk)
                if not data:
                    log.debug("EOF reached on stdout")
                    break

                # Call callback or enqueue
                if self._callback:
                    try:
                        self._callback(data)
                    except Exception as e:
                        log.error(f"Error in callback: {e}")
                else:
                    try:
                        self._audio_queue.put(data, block=False)
                    except queue.Full:
                        log.warning("Audio queue full, dropping samples")

        except Exception as e:
            if self._running:
                log.error(f"Error in reader thread: {e}")

    def start(self, on_data: Optional[Callable[[bytes, int], None]] = None):
        """
        Start audio capture.

        Args:
            on_data: Optional callback function(data: bytes, frame_count: int)
        """
        if self._running:
            log.warning("Already running")
            return

        # Store callback (calculate frame_count using standard format)
        if on_data:
            self._callback = lambda data: on_data(
                data,
                len(data) // (STANDARD_CHANNELS * STANDARD_SAMPLE_WIDTH)
            )

        # Verify bundle_id and binary_path are available
        if not self.bundle_id:
            raise RuntimeError("Bundle ID not set")
        if not self.binary_path:
            raise RuntimeError("Binary path not set")

        # Build command with standard format parameters
        cmd = [
            str(self.binary_path),
            self.bundle_id,
            str(STANDARD_SAMPLE_RATE),
            str(STANDARD_CHANNELS),
        ]

        log.info(f"Starting screencapture-audio: {' '.join(cmd)}")

        # Calculate chunk size for buffering (10ms of audio)
        chunk_duration_ms = 10
        chunk_bytes = int(
            STANDARD_SAMPLE_RATE * STANDARD_CHANNELS * STANDARD_SAMPLE_WIDTH * chunk_duration_ms / 1000
        )

        # Start subprocess
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=chunk_bytes,  # Buffer one chunk to reduce system calls
        )

        self._running = True

        # Start reader thread
        self._reader_thread = threading.Thread(target=self._reader_worker, daemon=True)
        self._reader_thread.start()

        log.info("ScreenCaptureKit capture started")

    def stop(self):
        """Stop audio capture."""
        if not self._running:
            return

        log.info("Stopping ScreenCaptureKit capture")
        self._running = False

        # Terminate subprocess
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                log.warning("Process did not terminate, killing")
                self._process.kill()
                self._process.wait()

            # Log stderr output for debugging
            if self._process.stderr:
                stderr_output = self._process.stderr.read().decode("utf-8", errors="ignore")
                if stderr_output:
                    log.debug(f"Swift helper stderr:\n{stderr_output}")

        # Wait for reader thread
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1)

        log.info("ScreenCaptureKit capture stopped")

    def read(self, num_frames: int = 1024) -> bytes:
        """
        Read audio data (blocking).

        Args:
            num_frames: Number of audio frames to read (default: 1024)

        Returns:
            float32 PCM audio data as bytes in standard format
        """
        bytes_per_frame = STANDARD_CHANNELS * STANDARD_SAMPLE_WIDTH
        total_bytes_needed = num_frames * bytes_per_frame

        chunks = []
        bytes_read = 0

        while bytes_read < total_bytes_needed:
            try:
                chunk = self._audio_queue.get(timeout=1.0)
                chunks.append(chunk)
                bytes_read += len(chunk)
            except queue.Empty:
                if not self._running:
                    break
                continue

        data = b"".join(chunks)
        return data[:total_bytes_needed]

    def iter_chunks(self):
        """
        Iterate over audio chunks (async generator).

        Yields:
            bytes: PCM audio data chunks
        """
        while self._running or not self._audio_queue.empty():
            try:
                chunk = self._audio_queue.get(timeout=0.1)
                yield chunk
            except queue.Empty:
                if not self._running:
                    break
                continue
