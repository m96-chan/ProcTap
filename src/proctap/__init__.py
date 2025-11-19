from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("proc-tap")
except PackageNotFoundError:
    # 開発中の editable install やビルド前など
    __version__ = "0.0.0"

from .core import ProcessAudioCapture, ResampleQuality
from .backends.base import (
    STANDARD_SAMPLE_RATE,
    STANDARD_CHANNELS,
    STANDARD_FORMAT,
    STANDARD_SAMPLE_WIDTH,
)

__all__ = [
    "ProcessAudioCapture",
    "ResampleQuality",
    "STANDARD_SAMPLE_RATE",
    "STANDARD_CHANNELS",
    "STANDARD_FORMAT",
    "STANDARD_SAMPLE_WIDTH",
    "__version__"
]