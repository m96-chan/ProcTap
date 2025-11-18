from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("proc-tap")
except PackageNotFoundError:
    # 開発中の editable install やビルド前など
    __version__ = "0.0.0"

from .core import ProcessAudioCapture
from .format import ResamplingQuality, FIXED_AUDIO_FORMAT

__all__ = ["ProcessAudioCapture", "ResamplingQuality", "FIXED_AUDIO_FORMAT", "__version__"]
