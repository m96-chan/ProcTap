"""
macOS PID-based Process Tap backend.

Captures audio from a specific PID using the Core Audio Process Tap API via the
signed Swift helper (``swift/proctap-helper``). Unlike the ScreenCaptureKit
backend (which is bundleID-based), this matches the Windows/Linux per-PID
semantics.

Key detail: the Process Tap *audio content* is gated by Screen Recording
permission granted to the process that runs the tap. Executing the helper as a
child of Python inherits the parent's TCC identity and yields silence, so the
helper is launched via LaunchServices (``open``) as its OWN responsible process.
Because ``open`` cannot pipe stdout, PCM is streamed back through a FIFO.

Requirements:
- macOS 14.4+ (Process Tap API), verified on macOS 15.6 / Apple Silicon
- The helper built + Developer ID signed (``swift/proctap-helper/build.sh``)
- Screen Recording permission enabled for ``proctap-helper`` (one-time, in
  System Settings › Privacy & Security › Screen Recording)
"""

from __future__ import annotations

import logging
import os
import platform
import queue
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

from .base import (
    AudioBackend,
    STANDARD_SAMPLE_RATE,
    STANDARD_CHANNELS,
    STANDARD_FORMAT,
    STANDARD_SAMPLE_WIDTH,
)
from .converter import AudioConverter, SampleFormat

log = logging.getLogger(__name__)

# The Process Tap negotiates this native format (see helper "Tap format" log).
TAP_SAMPLE_RATE = 44100
TAP_CHANNELS = 2
TAP_SAMPLE_WIDTH = 4  # float32
_CHUNK_MS = 10


def find_processtap_app() -> Optional[Path]:
    """Locate the signed proctap-helper.app bundle (bundled first, then dev build)."""
    pkg_dir = Path(__file__).parent.parent  # src/proctap
    bundled = pkg_dir / "bin" / "proctap-helper.app"
    if bundled.is_dir():
        return bundled

    helper_root = pkg_dir / "swift" / "proctap-helper"
    build_dir = helper_root / ".build"
    if build_dir.is_dir():
        for arch_dir in build_dir.glob("*-apple-macosx"):
            app = arch_dir / "release" / "proctap-helper.app"
            if app.is_dir():
                return app
    return None


def is_available() -> bool:
    """True on macOS with the built helper app present."""
    if platform.system() != "Darwin":
        return False
    try:
        major = int(platform.mac_ver()[0].split(".")[0])
    except (ValueError, IndexError):
        return False
    if major < 14:
        return False
    return find_processtap_app() is not None


class ProcessTapBackend(AudioBackend):
    """PID-based macOS capture via the Core Audio Process Tap Swift helper."""

    def __init__(self, pid: int, resample_quality: str = "best") -> None:
        super().__init__(pid)

        self.app_bundle = find_processtap_app()
        if not self.app_bundle:
            raise RuntimeError(
                "proctap-helper.app not found. Build it with "
                "swift/proctap-helper/build.sh (Developer ID signing required)."
            )
        self._exe = self.app_bundle / "Contents" / "MacOS" / "proctap-helper"
        # Wheels don't preserve the executable bit on package_data; restore it.
        try:
            if self._exe.is_file() and not os.access(self._exe, os.X_OK):
                self._exe.chmod(0o755)
        except OSError:
            pass

        self._tmpdir: Optional[str] = None
        self._fifo_path: Optional[str] = None
        self._helper_pid: Optional[int] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue = queue.Queue(maxsize=100)
        self._running = False

        # Tap is 44.1kHz/2ch/float32 -> convert to standard 48kHz/2ch/float32.
        self._converter = AudioConverter(
            src_rate=TAP_SAMPLE_RATE,
            src_channels=TAP_CHANNELS,
            src_width=TAP_SAMPLE_WIDTH,
            src_format=SampleFormat.FLOAT32,
            dst_rate=STANDARD_SAMPLE_RATE,
            dst_channels=STANDARD_CHANNELS,
            dst_width=STANDARD_SAMPLE_WIDTH,
            dst_format=SampleFormat.FLOAT32,
            resample_quality=resample_quality,  # type: ignore[arg-type]
            auto_detect_format=False,
        )

    def start(self) -> None:
        if self._running:
            log.warning("Already running")
            return

        self._tmpdir = tempfile.mkdtemp(prefix="proctap-")
        self._fifo_path = os.path.join(self._tmpdir, "pcm.fifo")
        os.mkfifo(self._fifo_path)

        # Launch via LaunchServices so the helper is its own TCC responsible
        # process (required for Screen-Recording-gated tap content).
        log.info(f"Launching proctap-helper (open) for PID {self._pid}")
        subprocess.run(
            ["open", str(self.app_bundle), "--args", str(self._pid), self._fifo_path],
            check=True,
        )

        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_worker, daemon=True)
        self._reader_thread.start()
        self._helper_pid = self._find_helper_pid()

    def _find_helper_pid(self) -> Optional[int]:
        try:
            out = subprocess.run(
                ["pgrep", "-f", f"proctap-helper.*{self._fifo_path}"],
                capture_output=True, text=True, timeout=2,
            )
            pids = [int(p) for p in out.stdout.split()]
            return pids[0] if pids else None
        except Exception:
            return None

    def _reader_worker(self) -> None:
        chunk_bytes = int(TAP_SAMPLE_RATE * TAP_CHANNELS * TAP_SAMPLE_WIDTH * _CHUNK_MS / 1000)
        try:
            # Opening the FIFO for read rendezvouses with the helper's write end.
            with open(self._fifo_path, "rb") as fifo:  # type: ignore[arg-type]
                while self._running:
                    data = fifo.read(chunk_bytes)
                    if not data:
                        log.debug("FIFO EOF (helper exited)")
                        break
                    try:
                        data = self._converter.convert(data)
                    except Exception as e:
                        log.error(f"Error converting tap audio: {e}")
                        continue
                    try:
                        self._audio_queue.put(data, block=False)
                    except queue.Full:
                        log.warning("Audio queue full, dropping samples")
        except Exception as e:
            if self._running:
                log.error(f"Error in reader thread: {e}")

    def read(self, num_frames: int = 1024) -> bytes:
        bytes_per_frame = STANDARD_CHANNELS * STANDARD_SAMPLE_WIDTH
        total = num_frames * bytes_per_frame
        result = bytearray(total)
        got = 0
        while got < total:
            try:
                chunk = self._audio_queue.get(timeout=1.0)
                n = min(len(chunk), total - got)
                result[got:got + n] = chunk[:n]
                got += n
            except queue.Empty:
                if not self._running:
                    break
                continue
        return bytes(result[:got])

    def iter_chunks(self):
        while self._running or not self._audio_queue.empty():
            try:
                yield self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                if not self._running:
                    break
                continue

    def stop(self) -> None:
        if not self._running:
            return
        log.info("Stopping proctap-helper capture")
        self._running = False

        # The helper is detached (launched via open); terminate it by PID.
        pid = self._helper_pid or self._find_helper_pid()
        if pid:
            try:
                os.kill(pid, 15)  # SIGTERM
            except ProcessLookupError:
                pass
            except Exception as e:
                log.debug(f"Could not terminate helper {pid}: {e}")

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1)

        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
            self._fifo_path = None

        log.info("proctap-helper capture stopped")

    def get_format(self) -> dict[str, int | str]:
        return {
            "sample_rate": STANDARD_SAMPLE_RATE,
            "channels": STANDARD_CHANNELS,
            "bits_per_sample": STANDARD_SAMPLE_WIDTH * 8,
            "sample_format": STANDARD_FORMAT,
        }

    def __del__(self) -> None:
        try:
            self.stop()
        except Exception:
            pass
