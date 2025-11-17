"""
Contrib modules for ProcessAudioCapture.

This package contains optional integrations and utilities that extend
ProcessAudioCapture's functionality.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__: list[str] = []

# Use lazy imports to avoid RuntimeWarning when running modules with -m flag
# This prevents the module from being imported twice during execution

try:
    from .discord_source import ProcessAudioSource
    __all__.append("ProcessAudioSource")
except ImportError:
    # discord.py is not installed
    pass

# Don't import whisper_transcribe at package init to avoid sys.modules conflict
# when running with `python -m proctap.contrib.whisper_transcribe`
if TYPE_CHECKING:
    from .whisper_transcribe import RealtimeTranscriber
else:
    # Provide lazy import through __getattr__ for runtime usage
    def __getattr__(name: str) -> object:
        if name == "RealtimeTranscriber":
            try:
                from .whisper_transcribe import RealtimeTranscriber
                __all__.append("RealtimeTranscriber")
                return RealtimeTranscriber
            except ImportError:
                raise AttributeError(
                    f"module {__name__!r} has no attribute {name!r}. "
                    "faster-whisper is not installed."
                )
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
