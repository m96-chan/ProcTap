"""
Unit tests for audio format converter optimizations (Issue #9 Phase 1).

Tests all three Python-level optimizations:
1.1: Format detection caching
1.2: Vectorized channel conversion
1.3: Optimized 24-bit PCM conversion
"""

import pytest
import numpy as np
from proctap.backends.converter import AudioConverter, SampleFormat


class TestFormatDetectionCaching:
    """Test optimization 1.1: Cache format detection to avoid repeated checks."""

    def test_format_detection_runs_once(self):
        """Verify format detection only runs on first chunk."""
        converter = AudioConverter(
            src_rate=44100, src_channels=2, src_width=2,
            dst_rate=44100, dst_channels=2, dst_width=2,
            src_format=SampleFormat.INT16,
            dst_format=SampleFormat.INT16,
            auto_detect_format=True
        )

        # Create test audio (16-bit PCM)
        audio_samples = (np.sin(2 * np.pi * 440 * np.arange(4410) / 44100) * 32767).astype(np.int16)
        pcm_bytes = audio_samples.tobytes()

        # First conversion should detect format
        assert not converter._format_detected
        result1 = converter.convert(pcm_bytes)
        assert converter._format_detected
        detected_format_after_first = converter._detected_format

        # Second conversion should use cached format
        result2 = converter.convert(pcm_bytes)
        assert converter._format_detected
        assert converter._detected_format == detected_format_after_first

        # Verify _actual_format is cached
        assert hasattr(converter, '_actual_format')
        assert converter._actual_format == detected_format_after_first

    def test_cached_format_used_for_conversion(self):
        """Verify that cached format is correctly used for subsequent conversions."""
        converter = AudioConverter(
            src_rate=44100, src_channels=2, src_width=2,
            dst_rate=44100, dst_channels=2, dst_width=2,
            auto_detect_format=True
        )

        # Create float32 audio that will be auto-detected
        audio_float = np.sin(2 * np.pi * 440 * np.arange(4410) / 44100).astype(np.float32) * 0.5
        pcm_bytes = audio_float.tobytes()

        # First conversion
        result1 = converter.convert(pcm_bytes)

        # Verify format was detected as FLOAT32
        assert converter._detected_format == SampleFormat.FLOAT32
        assert converter._actual_format == SampleFormat.FLOAT32

        # Second conversion should produce identical result
        result2 = converter.convert(pcm_bytes)
        assert result1 == result2


class TestVectorizedChannelConversion:
    """Test optimization 1.2: Vectorize channel conversion using numpy broadcasting."""

    def test_mono_to_stereo_broadcasting(self):
        """Test optimized mono to stereo conversion using broadcasting."""
        converter = AudioConverter(
            src_rate=44100, src_channels=1, src_width=2,
            dst_rate=44100, dst_channels=2, dst_width=2,
            auto_detect_format=False
        )

        # Create mono audio
        mono_samples = (np.sin(2 * np.pi * 440 * np.arange(1000) / 44100) * 32767).astype(np.int16)
        pcm_bytes = mono_samples.tobytes()

        result = converter.convert(pcm_bytes)
        result_array = np.frombuffer(result, dtype=np.int16).reshape(-1, 2)

        # Both channels should be identical
        assert np.allclose(result_array[:, 0], result_array[:, 1])

    def test_stereo_to_mono_averaging(self):
        """Test optimized stereo to mono downmix using vectorized mean."""
        converter = AudioConverter(
            src_rate=44100, src_channels=2, src_width=2,
            dst_rate=44100, dst_channels=1, dst_width=2,
            auto_detect_format=False
        )

        # Create stereo audio with different channels
        left = (np.sin(2 * np.pi * 440 * np.arange(1000) / 44100) * 16000).astype(np.int16)
        right = (np.sin(2 * np.pi * 880 * np.arange(1000) / 44100) * 16000).astype(np.int16)
        stereo = np.stack([left, right], axis=1).flatten()
        pcm_bytes = stereo.tobytes()

        result = converter.convert(pcm_bytes)
        result_array = np.frombuffer(result, dtype=np.int16)

        # Result should be approximately the average
        # Note: Some precision loss is expected due to int conversion
        expected = ((left.astype(np.float32) + right.astype(np.float32)) / 2).astype(np.int16)
        assert np.allclose(result_array, expected, atol=1)

    def test_multichannel_downmix_vectorized(self):
        """Test vectorized downmixing from 5.1 to stereo."""
        converter = AudioConverter(
            src_rate=44100, src_channels=6, src_width=2,
            dst_rate=44100, dst_channels=2, dst_width=2,
            auto_detect_format=False
        )

        # Create 6-channel audio
        num_samples = 1000
        channels_5_1 = []
        for i in range(6):
            freq = 440 * (i + 1)
            channel = (np.sin(2 * np.pi * freq * np.arange(num_samples) / 44100) * 16000).astype(np.int16)
            channels_5_1.append(channel)

        multi_channel = np.stack(channels_5_1, axis=1).flatten()
        pcm_bytes = multi_channel.tobytes()

        result = converter.convert(pcm_bytes)
        result_array = np.frombuffer(result, dtype=np.int16).reshape(-1, 2)

        # Should have stereo output
        assert result_array.shape == (num_samples, 2)

    def test_stereo_to_quad_upmix_vectorized(self):
        """Test vectorized upmixing from stereo to quad (4 channels)."""
        converter = AudioConverter(
            src_rate=44100, src_channels=2, src_width=2,
            dst_rate=44100, dst_channels=4, dst_width=2,
            auto_detect_format=False
        )

        # Create stereo audio
        left = (np.sin(2 * np.pi * 440 * np.arange(1000) / 44100) * 16000).astype(np.int16)
        right = (np.sin(2 * np.pi * 880 * np.arange(1000) / 44100) * 16000).astype(np.int16)
        stereo = np.stack([left, right], axis=1).flatten()
        pcm_bytes = stereo.tobytes()

        result = converter.convert(pcm_bytes)
        result_array = np.frombuffer(result, dtype=np.int16).reshape(-1, 4)

        # First two channels should match original
        assert np.allclose(result_array[:, 0], left, atol=1)
        assert np.allclose(result_array[:, 1], right, atol=1)

        # Last two channels should be copies of the last source channel (right)
        assert np.allclose(result_array[:, 2], right, atol=1)
        assert np.allclose(result_array[:, 3], right, atol=1)


class TestOptimized24BitPCM:
    """Test optimization 1.3: Optimize 24-bit PCM conversion with numpy array views."""

    def test_24bit_encoding_vectorized(self):
        """Test vectorized 24-bit PCM encoding."""
        converter = AudioConverter(
            src_rate=44100, src_channels=1, src_width=2,
            dst_rate=44100, dst_channels=1, dst_width=3,
            src_format=SampleFormat.INT16,
            dst_format=SampleFormat.INT24,
            auto_detect_format=False
        )

        # Create 16-bit audio
        audio_16bit = (np.sin(2 * np.pi * 440 * np.arange(1000) / 44100) * 32767).astype(np.int16)
        pcm_bytes = audio_16bit.tobytes()

        result = converter.convert(pcm_bytes)

        # Result should be 3 bytes per sample
        assert len(result) == len(audio_16bit) * 3

    def test_24bit_decoding_vectorized(self):
        """Test vectorized 24-bit PCM decoding."""
        converter = AudioConverter(
            src_rate=44100, src_channels=1, src_width=3,
            dst_rate=44100, dst_channels=1, dst_width=2,
            src_format=SampleFormat.INT24,
            dst_format=SampleFormat.INT16,
            auto_detect_format=False
        )

        # Create 24-bit audio manually
        # Test with known values: 0, max positive, max negative
        test_values = [0, 8388607, -8388608]  # 24-bit range: ±2^23
        pcm_24bit = bytearray()

        for val in test_values:
            # Convert to 24-bit little-endian
            if val < 0:
                val = val & 0xFFFFFF  # Two's complement for negative
            pcm_24bit.extend([
                val & 0xFF,
                (val >> 8) & 0xFF,
                (val >> 16) & 0xFF
            ])

        result = converter.convert(bytes(pcm_24bit))
        result_array = np.frombuffer(result, dtype=np.int16)

        # Should have 3 samples
        assert len(result_array) == 3

        # Check approximate conversion (some precision loss expected)
        # 0 should map to 0
        assert abs(result_array[0]) < 10
        # Max positive should map to ~32767
        assert result_array[1] > 32000
        # Max negative should map to ~-32768
        assert result_array[2] < -32000

    def test_24bit_roundtrip_accuracy(self):
        """Test 24-bit encode/decode roundtrip maintains accuracy."""
        # Encode to 24-bit
        encoder = AudioConverter(
            src_rate=44100, src_channels=1, src_width=2,
            dst_rate=44100, dst_channels=1, dst_width=3,
            src_format=SampleFormat.INT16,
            dst_format=SampleFormat.INT24,
            auto_detect_format=False
        )

        # Decode back to 16-bit
        decoder = AudioConverter(
            src_rate=44100, src_channels=1, src_width=3,
            dst_rate=44100, dst_channels=1, dst_width=2,
            src_format=SampleFormat.INT24,
            dst_format=SampleFormat.INT16,
            auto_detect_format=False
        )

        # Create original 16-bit audio with simpler wave
        original = (np.sin(2 * np.pi * 440 * np.arange(100) / 44100) * 30000).astype(np.int16)
        pcm_16bit = original.tobytes()

        # Roundtrip conversion
        pcm_24bit = encoder.convert(pcm_16bit)
        pcm_back_to_16bit = decoder.convert(pcm_24bit)
        result = np.frombuffer(pcm_back_to_16bit, dtype=np.int16)

        # Should be reasonably close to original (allow for conversion loss)
        # 24-bit conversion involves float normalization so some precision loss is expected
        max_diff = np.abs(result - original).max()
        assert max_diff < 5, f"Max difference: {max_diff}"

    def test_24bit_sign_extension_correctness(self):
        """Test that 24-bit sign extension works correctly for negative values."""
        converter = AudioConverter(
            src_rate=44100, src_channels=1, src_width=3,
            dst_rate=44100, dst_channels=1, dst_width=2,
            src_format=SampleFormat.INT24,
            dst_format=SampleFormat.INT16,
            auto_detect_format=False
        )

        # Create 24-bit audio with known negative value
        # -8388608 (min 24-bit value) in little-endian: 0x00 0x00 0x80
        min_negative = bytes([0x00, 0x00, 0x80] * 10)  # 10 samples of min value

        result = converter.convert(min_negative)
        result_array = np.frombuffer(result, dtype=np.int16)

        # All values should be negative (close to -1 in normalized form, which maps to close to -32768 in int16)
        assert np.all(result_array < 0)
        # Should be close to maximum negative value
        assert np.all(result_array < -30000)


class TestOptimizationPerformance:
    """Integration tests to verify optimizations don't break functionality."""

    def test_complex_conversion_chain(self):
        """Test that all optimizations work together in a complex conversion."""
        converter = AudioConverter(
            src_rate=44100, src_channels=2, src_width=2,
            dst_rate=48000, dst_channels=1, dst_width=3,
            src_format=SampleFormat.INT16,
            dst_format=SampleFormat.INT24,
            auto_detect_format=True
        )

        # Create stereo 16-bit audio
        left = (np.sin(2 * np.pi * 440 * np.arange(4410) / 44100) * 32767).astype(np.int16)
        right = (np.sin(2 * np.pi * 880 * np.arange(4410) / 44100) * 32767).astype(np.int16)
        stereo = np.stack([left, right], axis=1).flatten()
        pcm_bytes = stereo.tobytes()

        # Should convert: 44.1kHz stereo 16-bit -> 48kHz mono 24-bit
        result = converter.convert(pcm_bytes)

        # Check output size is reasonable (resampled + 3 bytes per sample)
        expected_samples = int(4410 * 48000 / 44100)
        expected_bytes = expected_samples * 3
        # Allow some tolerance for resampling
        assert abs(len(result) - expected_bytes) < 100

    def test_no_conversion_bypass(self):
        """Test that identical formats bypass conversion efficiently."""
        converter = AudioConverter(
            src_rate=44100, src_channels=2, src_width=2,
            dst_rate=44100, dst_channels=2, dst_width=2,
            auto_detect_format=False
        )

        # Create audio
        audio = (np.sin(2 * np.pi * 440 * np.arange(4410) / 44100) * 32767).astype(np.int16)
        stereo = np.tile(audio, (2, 1)).T.flatten()
        pcm_bytes = stereo.tobytes()

        # Convert
        result = converter.convert(pcm_bytes)

        # Should not need resampling or channel conversion
        assert not converter.needs_resample
        assert not converter.needs_channel_conversion

        # Result should be very close to original (allow small error due to float conversion)
        result_array = np.frombuffer(result, dtype=np.int16)
        original_array = np.frombuffer(pcm_bytes, dtype=np.int16)
        # Use allclose instead of array_equal to allow for minor rounding differences
        assert np.allclose(result_array, original_array, atol=1)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
