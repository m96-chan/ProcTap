"""
High-performance audio converter using C++ SIMD extension.

This module provides Python wrappers around the C++ SIMD-optimized audio converter.
Falls back to pure Python implementation if the native extension is not available.
"""

from __future__ import annotations
from typing import Optional
import logging
import os
import sys
from pathlib import Path

from .format import ResamplingQuality, FIXED_AUDIO_FORMAT

logger = logging.getLogger(__name__)

_LIBSAMPLERATE_SETUP = False


def _add_dll_directory(path: Path) -> None:
    """Add directory to DLL search path on Windows."""
    if not path.exists():
        return

    directory = path if path.is_dir() else path.parent
    if not directory.exists():
        return

    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(directory))
    else:
        os.environ["PATH"] = f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"


def _ensure_libsamplerate_search_path() -> None:
    """Ensure libsamplerate DLL can be discovered on Windows."""
    global _LIBSAMPLERATE_SETUP
    if _LIBSAMPLERATE_SETUP or sys.platform != "win32":
        return

    _LIBSAMPLERATE_SETUP = True

    env_path = os.environ.get("LIBSAMPLERATE_PATH")
    if env_path:
        _add_dll_directory(Path(env_path))

    try:
        import samplerate  # type: ignore

        samplerate_path = Path(samplerate.__file__).resolve()
        _add_dll_directory(samplerate_path)
        logger.debug(f"Added libsamplerate search path: {samplerate_path.parent}")
    except Exception:
        logger.debug("samplerate package not available for DLL path discovery")


# Configure DLL search path before importing native extension
_ensure_libsamplerate_search_path()

# Try to import native C++ extension
try:
    from . import _audio_converter  # type: ignore
    HAS_NATIVE_CONVERTER = True
    logger.info(f"Native audio converter loaded with SIMD support: {_audio_converter.get_cpu_features()}")
except ImportError as e:
    HAS_NATIVE_CONVERTER = False
    logger.warning(f"Native audio converter not available: {e}")
    logger.warning("Falling back to pure Python converter (slower)")


class NativeAudioConverter:
    """
    High-performance audio format converter using C++ SIMD optimization.

    Features:
    - int16 → float32 conversion with AVX2/SSE2
    - Resampling with configurable quality (Linear or libsamplerate)
    - Automatic CPU feature detection and best implementation selection
    """

    def __init__(self, quality: ResamplingQuality = ResamplingQuality.LOW_LATENCY):
        """
        Initialize native audio converter.

        Args:
            quality: Resampling quality mode (LOW_LATENCY or HIGH_QUALITY)

        Raises:
            RuntimeError: If native converter is not available
        """
        if not HAS_NATIVE_CONVERTER:
            raise RuntimeError(
                "Native audio converter not available. "
                "Please rebuild the package with: pip install -e . --force-reinstall"
            )

        self.quality = quality
        self.quality_str = quality.value
        if (
            self.quality == ResamplingQuality.HIGH_QUALITY
            and not self.has_high_quality_backend()
        ):
            logger.warning(
                "High-quality resampling requested but libsamplerate backend "
                "is not available. Falling back to low-latency mode."
            )
            self.quality = ResamplingQuality.LOW_LATENCY
            self.quality_str = self.quality.value

        logger.debug(f"NativeAudioConverter initialized with quality={self.quality_str}")

    @staticmethod
    def is_available() -> bool:
        """Check if native converter is available."""
        return HAS_NATIVE_CONVERTER

    @staticmethod
    def get_cpu_features() -> dict[str, bool]:
        """
        Get detected CPU features.

        Returns:
            Dictionary with 'sse2', 'avx', 'avx2' boolean values
        """
        if HAS_NATIVE_CONVERTER:
            return _audio_converter.get_cpu_features()
        return {"sse2": False, "avx": False, "avx2": False}

    @staticmethod
    def has_high_quality_backend() -> bool:
        """Return True if libsamplerate backend is available."""
        if not HAS_NATIVE_CONVERTER:
            return False

        checker = getattr(_audio_converter, "is_high_quality_available", None)
        if checker is None:
            return False

        try:
            return bool(checker())
        except Exception:
            logger.debug("Failed to query libsamplerate availability", exc_info=True)
            return False

    @staticmethod
    def detect_format(data: bytes) -> str:
        """
        Detect audio format from PCM data.

        Analyzes first few samples to determine if data is int16 or float32.
        This is needed because WASAPI may return different formats than requested.

        Args:
            data: PCM audio data (at least 400 bytes recommended)

        Returns:
            "int16", "float32", or "unknown"
        """
        if not HAS_NATIVE_CONVERTER:
            raise RuntimeError("Native converter not available")

        if len(data) < 400:
            logger.warning(f"Format detection with only {len(data)} bytes may be unreliable")

        return _audio_converter.detect_format(data)

    def convert_int16_to_float32(self, data: bytes) -> bytes:
        """
        Convert int16 PCM to float32 PCM with SIMD optimization.

        Args:
            data: int16 PCM data (2 bytes per sample)

        Returns:
            float32 PCM data normalized to [-1.0, 1.0] (4 bytes per sample)

        Raises:
            ValueError: If input size is invalid
        """
        if not HAS_NATIVE_CONVERTER:
            raise RuntimeError("Native converter not available")

        if len(data) % 2 != 0:
            raise ValueError(f"Input data size must be multiple of 2, got {len(data)}")

        return _audio_converter.convert_int16_to_float32(data)

    def resample(
        self,
        data: bytes,
        src_rate: int,
        dst_rate: int,
        channels: int,
    ) -> bytes:
        """
        Resample float32 PCM audio data.

        Args:
            data: float32 PCM data (4 bytes per sample)
            src_rate: Source sample rate in Hz
            dst_rate: Destination sample rate in Hz
            channels: Number of channels (interleaved)

        Returns:
            Resampled float32 PCM data

        Raises:
            ValueError: If input size is invalid
        """
        if not HAS_NATIVE_CONVERTER:
            raise RuntimeError("Native converter not available")

        if len(data) % (channels * 4) != 0:
            raise ValueError(
                f"Input data size must be multiple of {channels * 4}, got {len(data)}"
            )

        return _audio_converter.resample_audio(
            data, src_rate, dst_rate, channels, self.quality_str
        )

    def convert_to_fixed_format(
        self,
        data: bytes,
        src_rate: int,
        src_channels: int,
        src_format: str = "int16",
    ) -> bytes:
        """
        Convert audio to fixed output format (48kHz, 2ch, float32).

        This is a high-level convenience function that combines format conversion
        and resampling in a single call.

        Args:
            data: Source PCM data
            src_rate: Source sample rate in Hz
            src_channels: Source channel count
            src_format: Source format ("int16" or "float32")

        Returns:
            PCM data in fixed format (48kHz, 2ch, float32)
        """
        # Step 1: Convert to float32 if needed
        if src_format == "int16":
            data_float = self.convert_int16_to_float32(data)
        elif src_format == "float32":
            data_float = data
        else:
            raise ValueError(f"Unsupported source format: {src_format}")

        # Step 2: Resample if needed
        if src_rate != FIXED_AUDIO_FORMAT.sample_rate:
            data_float = self.resample(
                data_float,
                src_rate,
                FIXED_AUDIO_FORMAT.sample_rate,
                src_channels,
            )

        # Step 3: Channel conversion if needed
        if src_channels != FIXED_AUDIO_FORMAT.channels:
            # TODO: Implement channel conversion in C++
            # For now, just log a warning
            logger.warning(
                f"Channel conversion not yet implemented in native converter: "
                f"{src_channels}ch → {FIXED_AUDIO_FORMAT.channels}ch"
            )

        return data_float


__all__ = ["NativeAudioConverter", "HAS_NATIVE_CONVERTER"]
