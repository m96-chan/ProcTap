"""
Backend selection module for ProcTap.

Automatically selects the appropriate audio capture backend based on the
current operating system.
"""

from __future__ import annotations

import sys
import platform
from typing import TYPE_CHECKING

from ..format import ResamplingQuality

if TYPE_CHECKING:
    from .base import AudioBackend


def get_backend(
    pid: int,
    sample_rate: int = 48000,
    channels: int = 2,
    sample_width: int = 4,
    sample_format: str = "f32",
    resample_quality: ResamplingQuality | None = None,
    use_native_converter: bool = False,
) -> "AudioBackend":
    """
    Get the appropriate audio capture backend for the current platform.

    Args:
        pid: Process ID to capture audio from
        sample_rate: Sample rate in Hz (default: 48000)
        channels: Number of channels (default: 2 for stereo)
        sample_width: Bytes per sample (default: 4 for float32)
        sample_format: Sample format (default: "f32" for float32)
        resample_quality: Resampling quality setting
        use_native_converter: Whether to use native converter (Windows only)

    Returns:
        Platform-specific AudioBackend implementation

    Raises:
        NotImplementedError: If the current platform is not supported
        ImportError: If the backend for the current platform cannot be loaded
    """
    system = platform.system()

    if system == "Windows":
        from .windows import WindowsBackend
        return WindowsBackend(
            pid=pid,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            sample_format=sample_format,
            resample_quality=resample_quality,
            use_native_converter=use_native_converter,
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
        from .macos import MacOSBackend
        return MacOSBackend(
            pid=pid,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )

    else:
        raise NotImplementedError(
            f"Platform '{system}' is not supported. "
            "Supported platforms: Windows (stable), Linux (stable), macOS (experimental)"
        )


__all__ = ["get_backend", "AudioBackend"]
