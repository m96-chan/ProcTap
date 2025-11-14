from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("processaudiotap")
except PackageNotFoundError:
    # 開発中の editable install やビルド前など
    __version__ = "0.0.0"

from .core import ProcessAudioTap, StreamConfig

__all__ = ["ProcessAudioTap", "StreamConfig", "__version__"]