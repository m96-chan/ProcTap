"""
Backend selection module for ProcTap.

Automatically selects the appropriate audio capture backend based on the
current operating system.

All backends return audio in standard format: 48kHz/2ch/float32
"""

from __future__ import annotations

import platform
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .base import AudioBackend

ResampleQuality = Literal['best', 'medium', 'fast']


def get_backend(pid: int, resample_quality: ResampleQuality = 'best') -> "AudioBackend":
    """
    Get the appropriate audio capture backend for the current platform.

    All backends return audio in the standard format:
    - Sample rate: 48000 Hz
    - Channels: 2 (stereo)
    - Sample format: float32 (IEEE 754, normalized to [-1.0, 1.0])

    Args:
        pid: Process ID to capture audio from
        resample_quality: Resampling quality mode ('best', 'medium', 'fast')

    Returns:
        Platform-specific AudioBackend implementation

    Raises:
        NotImplementedError: If the current platform is not supported
        ImportError: If the backend for the current platform cannot be loaded
    """
    system = platform.system()

    if system == "Windows":
        from .windows import WindowsBackend
        return WindowsBackend(pid=pid, resample_quality=resample_quality)

    elif system == "Linux":
        from .linux import LinuxBackend
        # LinuxBackend now returns standard format (48kHz/2ch/float32)
        return LinuxBackend(
            pid=pid,
            sample_rate=44100,  # Native format (will be converted to 48kHz)
            channels=2,
            sample_width=2,  # Native format: 16-bit int (will be converted to float32)
            resample_quality=resample_quality,
        )

    elif system == "Darwin":  # macOS
        # macOS Backend Selection (in order of preference):
        # 1. ScreenCaptureKit (macOS 13+, bundleID-based, Apple Silicon compatible)
        # 2. Swift CLI Helper (macOS 14.4+, PID-based, requires AMFI disable on Apple Silicon)
        # 3. PyObjC (fallback, has IOProc callback issues)

        import logging
        log = logging.getLogger(__name__)

        # Try ScreenCaptureKit first (RECOMMENDED - macOS 13+, works on Apple Silicon)
        try:
            from .macos_screencapture import ScreenCaptureBackend, is_available as sc_available
            if sc_available():
                log.info("Using ScreenCaptureKit backend (Recommended - macOS 13+)")
                # ScreenCaptureKit already returns standard format (48kHz/2ch/float32)
                return ScreenCaptureBackend(
                    pid=pid,
                    resample_quality=resample_quality,
                )
        except ImportError as e:
            log.debug(f"ScreenCaptureKit backend not available: {e}")

        # Fallback to PyObjC backend (experimental - has callback issues)
        try:
            from .macos_pyobjc import MacOSNativeBackend, is_available as pyobjc_available
            if pyobjc_available():
                log.warning(
                    "Using PyObjC backend (Fallback - IOProc callbacks may not work). "
                    "Consider building ScreenCaptureKit backend for better stability."
                )
                return MacOSNativeBackend(
                    pid=pid,
                    sample_rate=48000,  # Native format (will be converted if needed)
                    channels=2,
                    sample_width=2,  # Native format: 16-bit int (will be converted to float32)
                )
        except ImportError:
            log.debug("PyObjC backend not available")

        # No backend available
        raise RuntimeError(
            "No macOS backend available.\n"
            "Option 1 (Recommended): Build ScreenCaptureKit backend:\n"
            "  cd src/proctap/swift/screencapture-audio && swift build\n"
            "  Requires: macOS 13+ (Ventura), Screen Recording permission\n"
            "Option 2 (Fallback): Install PyObjC:\n"
            "  pip install pyobjc-core pyobjc-framework-CoreAudio\n"
            "  Requires: macOS 14.4+ (Sonoma)"
        )

    else:
        raise NotImplementedError(
            f"Platform '{system}' is not supported. "
            "Supported platforms: Windows (stable), Linux (stable), macOS (experimental)"
        )


__all__ = ["get_backend", "AudioBackend"]
