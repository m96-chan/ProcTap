"""
Audio format definitions for ProcessAudioTap.

This module defines the standardized audio format used across the library.
All audio data output from ProcessAudioCapture is guaranteed to be in this format.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from enum import Enum


class ResamplingQuality(Enum):
    """
    Audio resampling quality settings.

    Controls the trade-off between latency and audio quality:
    - LOW_LATENCY: Linear interpolation with SIMD optimization (fastest, minimal latency)
    - HIGH_QUALITY: libsamplerate with SINC interpolation (best quality, slightly higher latency)

    Both modes use SIMD optimization (AVX2/AVX/SSE2) for maximum performance.
    """
    LOW_LATENCY = "low_latency"     # Linear interpolation (fastest)
    HIGH_QUALITY = "high_quality"   # libsamplerate SINC (best quality)


@dataclass(frozen=True)
class AudioFormat:
    """
    Standardized audio format specification.

    All audio data from ProcessAudioCapture is converted to this format:
    - Sample rate: 48000 Hz (industry standard for voice processing)
    - Channels: 2 (stereo, preserves spatial audio)
    - Sample format: float32, normalized to [-1.0, 1.0]

    This ensures consistent output regardless of the native backend format.
    """
    sample_rate: int          # Hz (e.g., 48000)
    channels: int             # Number of channels (e.g., 2 for stereo)
    sample_format: Literal["f32"]  # float32, normalized to [-1.0, 1.0]


# Fixed output format for all ProcessAudioCapture instances
FIXED_AUDIO_FORMAT = AudioFormat(
    sample_rate=48000,
    channels=2,
    sample_format="f32"
)


def get_bytes_per_frame() -> int:
    """
    Calculate bytes per frame for the fixed audio format.

    Returns:
        Bytes per frame (channels * bytes_per_sample)
        For 48kHz/2ch/float32: 2 * 4 = 8 bytes/frame
    """
    return FIXED_AUDIO_FORMAT.channels * 4  # 4 bytes per float32 sample


def get_frame_count(data: bytes) -> int:
    """
    Calculate number of frames in audio data.

    Args:
        data: Raw PCM audio data in fixed format

    Returns:
        Number of frames
    """
    bytes_per_frame = get_bytes_per_frame()
    return len(data) // bytes_per_frame


__all__ = [
    'AudioFormat',
    'FIXED_AUDIO_FORMAT',
    'ResamplingQuality',
    'get_bytes_per_frame',
    'get_frame_count',
]
