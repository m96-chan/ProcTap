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
        # TODO: Update LinuxBackend to return standard format
        return LinuxBackend(
            pid=pid,
            sample_rate=48000,
            channels=2,
            sample_width=4,
        )

    elif system == "Darwin":  # macOS
        from .macos import MacOSBackend
        # TODO: Update MacOSBackend to return standard format
        return MacOSBackend(pid)

    else:
        raise NotImplementedError(
            f"Platform '{system}' is not supported. "
            "Supported platforms: Windows, Linux (experimental), macOS (experimental)"
        )


__all__ = ["get_backend", "AudioBackend"]
