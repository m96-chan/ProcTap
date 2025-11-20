"""
Backend selection module for ProcTap.

Automatically selects the appropriate audio capture backend based on the
current operating system.
"""

from __future__ import annotations

import sys
import platform
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import AudioBackend


def get_backend(
    pid: int,
    sample_rate: int = 44100,
    channels: int = 2,
    sample_width: int = 2,
) -> "AudioBackend":
    """
    Get the appropriate audio capture backend for the current platform.

    Args:
        pid: Process ID to capture audio from
        sample_rate: Sample rate in Hz (default: 44100)
        channels: Number of channels (default: 2 for stereo)
        sample_width: Bytes per sample (default: 2 for 16-bit)

    Returns:
        Platform-specific AudioBackend implementation

    Raises:
        NotImplementedError: If the current platform is not supported
        ImportError: If the backend for the current platform cannot be loaded

    Note:
        Windows backend now supports format conversion. The native WASAPI
        captures at 44100Hz/2ch/16-bit, but will convert to the specified format.
    """
    system = platform.system()

    if system == "Windows":
        from .windows import WindowsBackend
        return WindowsBackend(
            pid=pid,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )

    elif system == "Linux":
        from .linux import LinuxBackend
        return LinuxBackend(
            pid=pid,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
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
                return ScreenCaptureBackend(
                    pid=pid,
                    sample_rate=sample_rate,
                    channels=channels,
                    sample_width=sample_width,
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
                    sample_rate=sample_rate,
                    channels=channels,
                    sample_width=sample_width,
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
