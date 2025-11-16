"""
Test script for converter.py optimizations.
Tests INT24 vectorization, channel conversion, and resampling performance.
"""

import numpy as np
import time
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from proctap.backends.converter import AudioConverter, SampleFormat


def test_int24_packed_conversion():
    """Test INT24 packed format conversion (vectorized)."""
    print("\n=== Testing INT24 Packed Conversion ===")

    # Create test audio: 1 second at 44.1kHz stereo
    duration = 1.0
    sample_rate = 44100
    channels = 2
    num_samples = int(duration * sample_rate)

    # Generate sine wave
    t = np.linspace(0, duration, num_samples, dtype=np.float32)
    audio_float = np.sin(2 * np.pi * 440 * t)  # 440Hz tone

    # Convert to INT24 packed (3 bytes per sample)
    audio_int24 = (audio_float * 8388607.0).astype(np.int32)
    pcm_bytes = bytearray()
    for val in audio_int24:
        val_int = int(val)  # Convert numpy.int32 to Python int
        pcm_bytes.extend(val_int.to_bytes(3, byteorder='little', signed=True))
    pcm_bytes = bytes(pcm_bytes)

    print(f"Generated {len(pcm_bytes)} bytes of INT24 packed PCM")

    # Test conversion (INT24 -> float -> INT24)
    converter = AudioConverter(
        src_rate=sample_rate,
        src_channels=1,
        src_width=3,
        dst_rate=sample_rate,
        dst_channels=1,
        dst_width=3,
        src_format=SampleFormat.INT24,
        dst_format=SampleFormat.INT24,
        auto_detect_format=False
    )

    # Time the conversion
    start = time.time()
    iterations = 10
    for _ in range(iterations):
        result = converter.convert(pcm_bytes)
    elapsed = time.time() - start

    print(f"Converted {iterations} iterations in {elapsed:.4f}s ({elapsed/iterations*1000:.2f}ms per iteration)")
    print(f"Throughput: {len(pcm_bytes) * iterations / elapsed / 1024 / 1024:.2f} MB/s")

    # Verify output length
    assert len(result) == len(pcm_bytes), f"Length mismatch: {len(result)} != {len(pcm_bytes)}"
    print("[OK] Output length matches input")

    # Verify round-trip accuracy (should be very close)
    max_diff = 0
    for i in range(0, min(len(pcm_bytes), len(result)), 3):
        orig = int.from_bytes(pcm_bytes[i:i+3], byteorder='little', signed=True)
        conv = int.from_bytes(result[i:i+3], byteorder='little', signed=True)
        max_diff = max(max_diff, abs(orig - conv))

    print(f"[OK] Max sample difference: {max_diff} (should be < 10)")
    assert max_diff < 10, f"Too much error in round-trip: {max_diff}"


def test_channel_conversion():
    """Test channel conversion optimization."""
    print("\n=== Testing Channel Conversion ===")

    # Mono to stereo conversion
    duration = 1.0
    sample_rate = 48000
    num_samples = int(duration * sample_rate)

    # Generate mono audio
    t = np.linspace(0, duration, num_samples, dtype=np.float32)
    audio_mono = np.sin(2 * np.pi * 440 * t)
    audio_int16 = (audio_mono * 32767.0).astype(np.int16)
    pcm_bytes = audio_int16.tobytes()

    # Mono -> Stereo
    converter = AudioConverter(
        src_rate=sample_rate,
        src_channels=1,
        src_width=2,
        dst_rate=sample_rate,
        dst_channels=2,
        dst_width=2,
        src_format=SampleFormat.INT16,
        dst_format=SampleFormat.INT16,
        auto_detect_format=False
    )

    start = time.time()
    iterations = 100
    for _ in range(iterations):
        result = converter.convert(pcm_bytes)
    elapsed = time.time() - start

    print(f"Mono->Stereo: {iterations} iterations in {elapsed:.4f}s ({elapsed/iterations*1000:.2f}ms per iteration)")

    # Verify output
    assert len(result) == len(pcm_bytes) * 2, "Stereo output should be 2x mono size"
    print("[OK] Output size correct")

    # Stereo -> Mono (downmix)
    converter2 = AudioConverter(
        src_rate=sample_rate,
        src_channels=2,
        src_width=2,
        dst_rate=sample_rate,
        dst_channels=1,
        dst_width=2,
        src_format=SampleFormat.INT16,
        dst_format=SampleFormat.INT16,
        auto_detect_format=False
    )

    result2 = converter2.convert(result)
    assert len(result2) == len(pcm_bytes), "Downmixed mono should match original size"
    print("[OK] Round-trip mono->stereo->mono works")


def test_resampling_performance():
    """Test resampling performance."""
    print("\n=== Testing Resampling Performance ===")

    # 44.1kHz -> 48kHz conversion
    duration = 1.0
    src_rate = 44100
    dst_rate = 48000
    channels = 2
    num_samples = int(duration * src_rate)

    # Generate stereo test signal
    t = np.linspace(0, duration, num_samples, dtype=np.float32)
    left = np.sin(2 * np.pi * 440 * t)
    right = np.sin(2 * np.pi * 880 * t)
    audio_stereo = np.column_stack([left, right])
    audio_int16 = (audio_stereo * 32767.0).astype(np.int16)
    pcm_bytes = audio_int16.tobytes()

    print(f"Input: {src_rate}Hz stereo, {len(pcm_bytes)} bytes")

    converter = AudioConverter(
        src_rate=src_rate,
        src_channels=channels,
        src_width=2,
        dst_rate=dst_rate,
        dst_channels=channels,
        dst_width=2,
        src_format=SampleFormat.INT16,
        dst_format=SampleFormat.INT16,
        auto_detect_format=False
    )

    start = time.time()
    iterations = 10
    for _ in range(iterations):
        result = converter.convert(pcm_bytes)
    elapsed = time.time() - start

    expected_size = int(len(pcm_bytes) * dst_rate / src_rate)
    actual_size = len(result)

    print(f"Resampling {src_rate}Hz->{dst_rate}Hz: {iterations} iterations in {elapsed:.4f}s")
    print(f"  Per iteration: {elapsed/iterations*1000:.2f}ms")
    print(f"  Expected output size: {expected_size} bytes, actual: {actual_size} bytes")
    print(f"  Size ratio: {actual_size/len(pcm_bytes):.4f} (expected: {dst_rate/src_rate:.4f})")

    # Allow 1% tolerance for size
    assert abs(actual_size - expected_size) / expected_size < 0.01, "Output size incorrect"
    print("[OK] Resampling output size correct")


def test_combined_conversion():
    """Test combined conversion (format + channels + resample)."""
    print("\n=== Testing Combined Conversion ===")

    # INT24 44.1kHz stereo -> INT16 48kHz mono
    src_rate = 44100
    dst_rate = 48000
    duration = 0.5  # Shorter for combined test
    num_samples = int(duration * src_rate)

    # Generate stereo INT24 data
    t = np.linspace(0, duration, num_samples, dtype=np.float32)
    left = np.sin(2 * np.pi * 440 * t)
    right = np.sin(2 * np.pi * 880 * t)
    audio_stereo = np.column_stack([left, right]).flatten()

    # Convert to INT24 packed
    audio_int24 = (audio_stereo * 8388607.0).astype(np.int32)
    pcm_bytes = bytearray()
    for val in audio_int24:
        val_int = int(val)  # Convert numpy.int32 to Python int
        pcm_bytes.extend(val_int.to_bytes(3, byteorder='little', signed=True))
    pcm_bytes = bytes(pcm_bytes)

    print(f"Input: INT24 {src_rate}Hz stereo, {len(pcm_bytes)} bytes")

    converter = AudioConverter(
        src_rate=src_rate,
        src_channels=2,
        src_width=3,
        dst_rate=dst_rate,
        dst_channels=1,
        dst_width=2,
        src_format=SampleFormat.INT24,
        dst_format=SampleFormat.INT16,
        auto_detect_format=False
    )

    start = time.time()
    result = converter.convert(pcm_bytes)
    elapsed = time.time() - start

    expected_samples = int(num_samples * dst_rate / src_rate)
    actual_samples = len(result) // 2  # 2 bytes per INT16 sample

    print(f"Output: INT16 {dst_rate}Hz mono, {len(result)} bytes")
    print(f"Conversion time: {elapsed*1000:.2f}ms")
    print(f"Expected samples: {expected_samples}, actual: {actual_samples}")

    # Allow small tolerance
    assert abs(actual_samples - expected_samples) < 10, "Sample count mismatch"
    print("[OK] Combined conversion successful")


if __name__ == '__main__':
    print("Testing converter.py optimizations...")
    print("=" * 60)

    try:
        test_int24_packed_conversion()
        test_channel_conversion()
        test_resampling_performance()
        test_combined_conversion()

        print("\n" + "=" * 60)
        print("[SUCCESS] All tests passed!")
        print("=" * 60)

    except Exception as e:
        print(f"\nX Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
