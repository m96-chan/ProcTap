"""
Audio format converter for PCM data.

Handles:
- Sample rate conversion (resampling)
- Channel conversion (mono/stereo)
- Bit depth conversion (16-bit, 24-bit, 32-bit)
- Automatic format detection (int16 vs float32)
"""

from __future__ import annotations
import numpy as np
import logging
import struct
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from scipy import signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    logger.warning("scipy not available - audio format conversion will not work")

# Try to import samplerate for higher quality resampling (optional)
try:
    import samplerate
    HAS_SAMPLERATE = True
    logger.debug("libsamplerate available - using high-quality resampling")
except ImportError:
    HAS_SAMPLERATE = False
    logger.debug("libsamplerate not available - using scipy polyphase resampling")


class SampleFormat:
    """Sample format specification."""
    INT16 = 'int16'          # 16-bit signed integer
    INT24 = 'int24'          # 24-bit signed integer (3-byte packed)
    INT24_32 = 'int24_32'    # 24-bit in 32-bit container (padded)
    INT32 = 'int32'          # 32-bit signed integer
    FLOAT32 = 'float32'      # 32-bit IEEE float


class AudioConverter:
    """
    Converts PCM audio data between different formats.

    Supports:
    - Sample rate conversion: 44.1kHz, 48kHz, 96kHz, 192kHz, etc.
    - Channel conversion: 1-8 channels (mono to 7.1 surround)
    - Bit depth conversion:
      - 16-bit PCM (int16)
      - 24-bit PCM (3-byte packed)
      - 24-in-32-bit PCM (32-bit container, 24-bit effective)
      - 32-bit PCM (int32)
      - 32-bit IEEE float
    - Automatic format detection (int16 vs float32)
    """

    def __init__(
        self,
        src_rate: int,
        src_channels: int,
        src_width: int,  # bytes per sample
        dst_rate: int,
        dst_channels: int,
        dst_width: int,
        src_format: str = SampleFormat.INT16,
        dst_format: str = SampleFormat.INT16,
        auto_detect_format: bool = True,
    ):
        """
        Initialize audio converter.

        Args:
            src_rate: Source sample rate in Hz (e.g., 44100, 48000, 96000, 192000)
            src_channels: Source channel count (1-8)
            src_width: Source sample width in bytes (2=16bit, 3=24bit, 4=32bit/float)
            dst_rate: Destination sample rate in Hz
            dst_channels: Destination channel count (1-8)
            dst_width: Destination sample width in bytes
            src_format: Source sample format (int16, int24, int24_32, int32, float32)
            dst_format: Destination sample format
            auto_detect_format: If True, automatically detect if source is int16 or float32
        """
        if not HAS_SCIPY:
            raise RuntimeError("scipy is required for audio format conversion. Install with: pip install scipy")

        self.src_rate = src_rate
        self.src_channels = src_channels
        self.src_width = src_width
        self.src_format = src_format
        self.dst_rate = dst_rate
        self.dst_channels = dst_channels
        self.dst_width = dst_width
        self.dst_format = dst_format
        self.auto_detect_format = auto_detect_format

        # Format detection state
        self._format_detected = False
        self._detected_format: Optional[str] = None

        # Validate parameters
        if src_width not in (2, 3, 4):
            raise ValueError(f"Unsupported source sample width: {src_width} bytes")
        if dst_width not in (2, 3, 4):
            raise ValueError(f"Unsupported destination sample width: {dst_width} bytes")
        if src_channels < 1 or src_channels > 8:
            raise ValueError(f"Unsupported source channel count: {src_channels} (must be 1-8)")
        if dst_channels < 1 or dst_channels > 8:
            raise ValueError(f"Unsupported destination channel count: {dst_channels} (must be 1-8)")

        # Calculate conversion flags
        self.needs_resample = (src_rate != dst_rate)
        self.needs_channel_conversion = (src_channels != dst_channels)
        self.needs_bit_conversion = (src_width != dst_width)

        logger.info(
            f"AudioConverter initialized: {src_rate}Hz/{src_channels}ch/{src_width*8}bit "
            f"-> {dst_rate}Hz/{dst_channels}ch/{dst_width*8}bit "
            f"(resample={self.needs_resample}, channels={self.needs_channel_conversion}, "
            f"bits={self.needs_bit_conversion})"
        )

    def _detect_pcm_format(self, pcm_bytes: bytes) -> str:
        """
        Detect if PCM data is int16 or float32.

        WASAPI may return 32-bit float despite requesting 16-bit PCM.

        Args:
            pcm_bytes: Raw PCM data

        Returns:
            Detected format: SampleFormat.INT16 or SampleFormat.FLOAT32
        """
        if len(pcm_bytes) < 400:  # Need at least 100 samples for reliable detection
            return self.src_format

        try:
            # First try 32-bit float interpretation (most common WASAPI mismatch)
            if len(pcm_bytes) % 4 == 0:
                sample_count = min(len(pcm_bytes) // 4, 100)
                floats = np.frombuffer(pcm_bytes[:sample_count * 4], dtype=np.float32)

                # Check for NaN/Inf
                has_nan = np.isnan(floats).any()
                has_inf = np.isinf(floats).any()

                if not has_nan and not has_inf:
                    max_abs = np.abs(floats).max()

                    # Valid float32 audio is typically in [-1.0, 1.0] but allow up to 10.0
                    # Reference: discord_source.py uses 0.0 < max_abs <= 10.0
                    if 0.0 < max_abs <= 10.0:
                        logger.info(f"Auto-detected 32-bit float PCM format (max_abs={max_abs:.6f})")
                        return SampleFormat.FLOAT32
                else:
                    logger.debug(f"Float32 interpretation invalid (nan={has_nan}, inf={has_inf})")

            # Try int16 interpretation
            sample_count = min(len(pcm_bytes) // 2, 100)
            int16_samples = np.frombuffer(pcm_bytes[:sample_count * 2], dtype=np.int16)
            int16_max = np.abs(int16_samples).max()

            if int16_max > 100:  # Has significant signal (>100 to avoid false positives)
                logger.info(f"Auto-detected 16-bit PCM format (max={int16_max})")
                return SampleFormat.INT16

            # If signal is very weak, default to the specified format
            logger.debug(f"Format detection inconclusive (int16_max={int16_max}), using specified format")
            return self.src_format

        except Exception as e:
            logger.warning(f"Format detection failed: {e}, using specified format")
            return self.src_format

    def convert(self, pcm_bytes: bytes) -> bytes:
        """
        Convert PCM data from source format to destination format.

        Args:
            pcm_bytes: Raw PCM data in source format

        Returns:
            Converted PCM data in destination format
        """
        if not pcm_bytes:
            return pcm_bytes

        # Auto-detect format on first chunk if enabled
        if self.auto_detect_format and not self._format_detected:
            self._detected_format = self._detect_pcm_format(pcm_bytes)
            self._format_detected = True
            if self._detected_format != self.src_format:
                logger.info(f"Format changed from {self.src_format} to {self._detected_format}")

        # Use detected format if available
        actual_format = self._detected_format if self._detected_format else self.src_format

        # Step 1: bytes -> numpy array (normalized float32)
        audio = self._bytes_to_float(pcm_bytes, actual_format, self.src_channels)

        # Step 2: Channel conversion (before resampling for better quality)
        if self.needs_channel_conversion:
            audio = self._convert_channels(audio, self.src_channels, self.dst_channels)

        # Step 3: Resample
        if self.needs_resample:
            audio = self._resample(audio, self.src_rate, self.dst_rate)

        # Step 4: Convert to destination format
        pcm_out = self._float_to_bytes(audio, self.dst_format)

        return pcm_out

    def _bytes_to_float(self, pcm_bytes: bytes, sample_format: str, channels: int) -> np.ndarray:
        """
        Convert PCM bytes to float32 numpy array normalized to [-1.0, 1.0].

        Args:
            pcm_bytes: Raw PCM data
            sample_format: Format (int16, int24, int24_32, int32, float32)
            channels: Number of channels

        Returns:
            Shape: (num_frames, channels) for multi-channel, (num_frames,) for mono
        """
        if sample_format == SampleFormat.INT16:
            # 16-bit signed PCM
            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        elif sample_format == SampleFormat.INT24:
            # 24-bit signed PCM (3-byte packed) - VECTORIZED
            num_samples = len(pcm_bytes) // 3
            # Convert bytes to uint8 array and reshape to (num_samples, 3)
            data = np.frombuffer(pcm_bytes, dtype=np.uint8).reshape(num_samples, 3)
            # Combine 3 bytes into int32 with sign extension
            # Little-endian: byte0 | byte1<<8 | byte2<<16
            audio_int32 = (data[:, 0].astype(np.int32) |
                          (data[:, 1].astype(np.int32) << 8) |
                          (data[:, 2].astype(np.int32) << 16))
            # Sign-extend from 24-bit to 32-bit
            # If bit 23 is set (negative), set upper 8 bits to 1 (0xFF000000)
            # Use bitwise operations with proper numpy int32 handling
            sign_bit = (audio_int32 & 0x800000) != 0
            # Create sign extension mask as int32
            sign_ext = np.where(sign_bit, np.int32(-16777216), np.int32(0))  # -16777216 = 0xFF000000 as signed int32
            audio_int32 = audio_int32 | sign_ext
            audio = audio_int32.astype(np.float32) / 8388608.0  # 2^23

        elif sample_format == SampleFormat.INT24_32:
            # 24-bit in 32-bit container (upper 24 bits used)
            audio_int32 = np.frombuffer(pcm_bytes, dtype=np.int32)
            # Shift right 8 bits to get 24-bit value, then normalize
            audio = (audio_int32.astype(np.float32) / 256.0) / 8388608.0  # divide by 2^8 then 2^23

        elif sample_format == SampleFormat.INT32:
            # 32-bit signed PCM
            audio = np.frombuffer(pcm_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0  # 2^31

        elif sample_format == SampleFormat.FLOAT32:
            # 32-bit IEEE float (already normalized, typically)
            audio = np.frombuffer(pcm_bytes, dtype=np.float32)

            # Check for NaN/Inf and replace with zeros
            if np.any(~np.isfinite(audio)):
                nan_count = np.isnan(audio).sum()
                inf_count = np.isinf(audio).sum()
                logger.warning(f"NaN/Inf detected in float32 audio: {nan_count} NaNs, {inf_count} Infs - replacing with zeros")
                audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)

            # Clip to [-1.0, 1.0] in case it's not normalized
            audio = np.clip(audio, -1.0, 1.0)

        else:
            raise ValueError(f"Unsupported sample format: {sample_format}")

        # Reshape to (num_frames, channels) for multi-channel
        if channels > 1:
            audio = audio.reshape(-1, channels)

        return audio

    def _float_to_bytes(self, audio: np.ndarray, sample_format: str) -> bytes:
        """
        Convert float32 numpy array to PCM bytes.

        Args:
            audio: Shape (num_frames, channels) or (num_frames,)
            sample_format: Target format (int16, int24, int24_32, int32, float32)
        """
        # Flatten if multi-channel
        if audio.ndim == 2:
            audio = audio.flatten()

        # Clip to [-1.0, 1.0] for safety
        audio = np.clip(audio, -1.0, 1.0)

        if sample_format == SampleFormat.INT16:
            # 16-bit signed PCM
            audio_int = (audio * 32767.0).astype(np.int16)
            return audio_int.tobytes()

        elif sample_format == SampleFormat.INT24:
            # 24-bit signed PCM (3-byte packed) - VECTORIZED
            audio_int = (audio * 8388607.0).astype(np.int32)
            # Extract 3 bytes from each int32 (little-endian)
            num_samples = len(audio_int)
            pcm_bytes = np.zeros(num_samples * 3, dtype=np.uint8)
            pcm_bytes[0::3] = audio_int & 0xFF           # byte 0
            pcm_bytes[1::3] = (audio_int >> 8) & 0xFF    # byte 1
            pcm_bytes[2::3] = (audio_int >> 16) & 0xFF   # byte 2
            return pcm_bytes.tobytes()

        elif sample_format == SampleFormat.INT24_32:
            # 24-bit in 32-bit container (upper 24 bits)
            audio_int24 = (audio * 8388607.0).astype(np.int32)
            # Shift left 8 bits to place in upper 24 bits of 32-bit container
            audio_int32 = (audio_int24 * 256).astype(np.int32)
            return audio_int32.tobytes()

        elif sample_format == SampleFormat.INT32:
            # 32-bit signed PCM
            audio_int = (audio * 2147483647.0).astype(np.int32)
            return audio_int.tobytes()

        elif sample_format == SampleFormat.FLOAT32:
            # 32-bit IEEE float (already float32, just ensure dtype)
            return audio.astype(np.float32).tobytes()

        else:
            raise ValueError(f"Unsupported sample format: {sample_format}")

    def _convert_channels(self, audio: np.ndarray, src_ch: int, dst_ch: int) -> np.ndarray:
        """
        Convert between different channel counts (1-8 channels).

        Supports:
        - Upmixing: mono -> stereo/surround (duplicate channels)
        - Downmixing: stereo/surround -> mono (average all channels)
        - Stereo <-> surround: basic channel mapping

        Args:
            audio: Shape (num_frames, src_ch) for multi-channel, (num_frames,) for mono
        """
        if src_ch == dst_ch:
            return audio

        # Ensure audio is 2D
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)

        num_frames = audio.shape[0]

        # Downmix to mono (average all channels)
        if dst_ch == 1:
            # Return as 1D array for mono (resample expects this)
            return audio.mean(axis=1)

        # Upmix from mono
        if src_ch == 1:
            # Duplicate mono channel to all destination channels
            return np.tile(audio, (1, dst_ch))

        # General case: map src channels to dst channels - OPTIMIZED
        result = np.zeros((num_frames, dst_ch), dtype=np.float32)

        if dst_ch < src_ch:
            # Downmixing: take first dst_ch channels and average the rest
            result[:, :dst_ch] = audio[:, :dst_ch]
            if src_ch > dst_ch:
                # Average remaining channels into the last channel
                result[:, -1] = audio[:, dst_ch:].mean(axis=1)
        else:
            # Upmixing: copy src channels, duplicate last channel to fill - VECTORIZED
            result[:, :src_ch] = audio
            # Fill remaining channels by repeating the last source channel
            if dst_ch > src_ch:
                # Use broadcasting to duplicate the last channel
                result[:, src_ch:] = audio[:, -1:].repeat(dst_ch - src_ch, axis=1)

        return result

    def _resample(self, audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        """
        Resample audio using high-quality methods.

        Priority order:
        1. libsamplerate (if available) - Professional quality resampling
        2. scipy.signal.resample_poly - High-quality polyphase filtering
        3. Fallback to scipy.signal.resample - FFT-based (lowest quality)

        Args:
            audio: Shape (num_frames, channels) or (num_frames,)
        """
        if src_rate == dst_rate:
            return audio

        ratio = dst_rate / src_rate

        # Method 1: Use libsamplerate if available (highest quality)
        if HAS_SAMPLERATE:
            logger.debug(f"Resampling with libsamplerate: {src_rate}Hz -> {dst_rate}Hz (ratio={ratio:.4f})")
            try:
                # samplerate works with both mono and stereo
                # Shape: (num_frames,) for mono, (num_frames, channels) for stereo
                resampled = samplerate.resample(
                    audio,
                    ratio,
                    converter_type='sinc_best'  # Highest quality mode
                )
                return resampled.astype(np.float32)
            except Exception as e:
                logger.warning(f"libsamplerate failed, falling back to scipy: {e}")
                # Fall through to scipy method

        # Method 2: Use scipy polyphase filtering (good quality, fast) - OPTIMIZED
        try:
            from math import gcd
            ratio_gcd = gcd(src_rate, dst_rate)
            up = dst_rate // ratio_gcd      # Upsampling factor
            down = src_rate // ratio_gcd    # Downsampling factor

            logger.debug(f"Resampling with scipy.resample_poly: {src_rate}Hz -> {dst_rate}Hz (up={up}, down={down})")

            if audio.ndim == 1:
                # Mono
                return signal.resample_poly(audio, up, down).astype(np.float32)
            else:
                # Multi-channel: process along axis=0 (time axis), vectorized per-channel
                # Note: resample_poly doesn't support multi-channel directly, so we still need a loop
                # but we optimize by pre-allocating and avoiding redundant calculations
                num_samples = audio.shape[0]
                new_num_samples = int(num_samples * ratio)
                num_channels = audio.shape[1]
                resampled = np.empty((new_num_samples, num_channels), dtype=np.float32)

                # Process all channels (optimized with pre-allocation)
                for ch in range(num_channels):
                    resampled[:, ch] = signal.resample_poly(audio[:, ch], up, down)

                return resampled
        except Exception as e:
            logger.warning(f"scipy.resample_poly failed, falling back to FFT method: {e}")

        # Method 3: Fallback to FFT-based resampling (lowest quality but most robust)
        logger.debug(f"Resampling with scipy.resample (FFT): {src_rate}Hz -> {dst_rate}Hz")
        num_samples = audio.shape[0]
        new_num_samples = int(num_samples * ratio)

        if audio.ndim == 1:
            return signal.resample(audio, new_num_samples).astype(np.float32)
        else:
            resampled = np.zeros((new_num_samples, audio.shape[1]), dtype=np.float32)
            for ch in range(audio.shape[1]):
                resampled[:, ch] = signal.resample(audio[:, ch], new_num_samples)
            return resampled.astype(np.float32)


def is_conversion_needed(
    src_rate: int, src_channels: int, src_width: int,
    dst_rate: int, dst_channels: int, dst_width: int
) -> bool:
    """
    Check if audio format conversion is needed.

    Returns:
        True if any conversion is required, False if formats match
    """
    return (
        src_rate != dst_rate or
        src_channels != dst_channels or
        src_width != dst_width
    )


__all__ = ['AudioConverter', 'SampleFormat', 'is_conversion_needed']
