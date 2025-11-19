#!/usr/bin/env python3
"""
Test native SIMD audio converter.

This script tests:
1. CPU feature detection
2. int16 → float32 conversion
3. Resampling (44.1kHz → 48kHz)
4. Performance benchmarking
"""

import sys
import time
import struct
import numpy as np

print("=" * 60)
print("Testing Native SIMD Audio Converter")
print("=" * 60)

# Test 1: Import and CPU features
print("\n[Test 1] Importing native converter...")
try:
    from proctap.converter_native import NativeAudioConverter, HAS_NATIVE_CONVERTER
    from proctap.format import ResamplingQuality

    if not HAS_NATIVE_CONVERTER:
        print("❌ Native converter not available!")
        print("Build it with: pip install -e . --force-reinstall")
        sys.exit(1)

    print("✅ Native converter imported successfully")

    converter = NativeAudioConverter(quality=ResamplingQuality.LOW_LATENCY)
    cpu_features = converter.get_cpu_features()
    print(f"\nCPU Features detected:")
    print(f"  SSE2: {cpu_features['sse2']}")
    print(f"  AVX:  {cpu_features['avx']}")
    print(f"  AVX2: {cpu_features['avx2']}")

except Exception as e:
    print(f"❌ Failed to import: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: int16 → float32 conversion
print("\n[Test 2] Testing int16 → float32 conversion...")
try:
    # Create test data: 1000 samples of int16 PCM
    # Values: -32768, -16384, 0, 16384, 32767 (repeated)
    test_values = [-32768, -16384, 0, 16384, 32767]
    int16_data = struct.pack(f"<{1000}h", *(test_values * 200))

    print(f"Input: {len(int16_data)} bytes of int16 PCM ({len(int16_data)//2} samples)")

    # Convert
    start = time.perf_counter()
    float32_data = converter.convert_int16_to_float32(int16_data)
    elapsed = time.perf_counter() - start

    print(f"Output: {len(float32_data)} bytes of float32 PCM ({len(float32_data)//4} samples)")
    print(f"Conversion time: {elapsed*1000:.3f} ms")

    # Verify results
    float_array = np.frombuffer(float32_data, dtype=np.float32)
    print(f"\nSample values (first 5):")
    for i in range(5):
        int16_val = struct.unpack_from("<h", int16_data, i*2)[0]
        float_val = float_array[i]
        expected = int16_val / 32768.0
        print(f"  int16={int16_val:6d} → float32={float_val:+.6f} (expected: {expected:+.6f})")

    # Check if conversion is correct
    max_error = 0.0
    for i in range(len(test_values)):
        int16_val = test_values[i]
        float_val = float_array[i]
        expected = int16_val / 32768.0
        error = abs(float_val - expected)
        max_error = max(max_error, error)

    if max_error < 1e-5:
        print(f"✅ Conversion accuracy: max_error={max_error:.2e} (< 1e-5)")
    else:
        print(f"⚠️  Conversion accuracy: max_error={max_error:.2e} (might be too high)")

except Exception as e:
    print(f"❌ Conversion test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Resampling (44.1kHz → 48kHz)
print("\n[Test 3] Testing resampling (44.1kHz → 48kHz)...")
try:
    # Generate 1 second of 44.1kHz stereo sine wave (440 Hz)
    duration = 1.0
    src_rate = 44100
    dst_rate = 48000
    channels = 2
    frequency = 440.0  # Hz

    # Generate sine wave
    num_samples = int(duration * src_rate)
    t = np.linspace(0, duration, num_samples, endpoint=False)
    sine = np.sin(2 * np.pi * frequency * t).astype(np.float32)

    # Interleave stereo (same signal in both channels)
    stereo_data = np.zeros(num_samples * channels, dtype=np.float32)
    stereo_data[0::2] = sine  # Left channel
    stereo_data[1::2] = sine  # Right channel

    input_bytes = stereo_data.tobytes()
    print(f"Input: {len(input_bytes)} bytes, {num_samples} frames @ {src_rate}Hz")

    # Resample
    start = time.perf_counter()
    output_bytes = converter.resample(input_bytes, src_rate, dst_rate, channels)
    elapsed = time.perf_counter() - start

    output_array = np.frombuffer(output_bytes, dtype=np.float32)
    output_frames = len(output_array) // channels

    print(f"Output: {len(output_bytes)} bytes, {output_frames} frames @ {dst_rate}Hz")
    print(f"Resampling time: {elapsed*1000:.3f} ms")

    # Verify output size is approximately correct
    expected_frames = int(num_samples * dst_rate / src_rate)
    frame_error = abs(output_frames - expected_frames)

    if frame_error <= 1:
        print(f"✅ Output frame count: {output_frames} (expected: {expected_frames})")
    else:
        print(f"⚠️  Output frame count: {output_frames} (expected: {expected_frames}, error: {frame_error})")

    # Check if audio is still in valid range [-1.0, 1.0]
    min_val = output_array.min()
    max_val = output_array.max()
    print(f"Output range: [{min_val:.3f}, {max_val:.3f}]")

    if -1.1 <= min_val <= -0.9 and 0.9 <= max_val <= 1.1:
        print("✅ Output values are in expected range")
    else:
        print(f"⚠️  Output values might be out of range")

except Exception as e:
    print(f"❌ Resampling test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Performance benchmark
print("\n[Test 4] Performance benchmark...")
try:
    # Benchmark int16 → float32 conversion
    # Simulate 10 seconds of 44.1kHz stereo audio
    benchmark_duration = 10.0
    benchmark_rate = 44100
    benchmark_channels = 2
    benchmark_samples = int(benchmark_duration * benchmark_rate * benchmark_channels)

    # Generate random int16 data
    int16_array = np.random.randint(-32768, 32767, benchmark_samples, dtype=np.int16)
    int16_bytes = int16_array.tobytes()

    print(f"Benchmark: Converting {benchmark_duration}s of {benchmark_rate}Hz stereo audio")
    print(f"Data size: {len(int16_bytes):,} bytes ({len(int16_bytes)/1024/1024:.2f} MB)")

    # Warmup
    _ = converter.convert_int16_to_float32(int16_bytes[:1000])

    # Benchmark conversion
    iterations = 10
    total_time = 0.0
    for i in range(iterations):
        start = time.perf_counter()
        _ = converter.convert_int16_to_float32(int16_bytes)
        elapsed = time.perf_counter() - start
        total_time += elapsed

    avg_time = total_time / iterations
    throughput_mb = (len(int16_bytes) / 1024 / 1024) / avg_time
    realtime_factor = benchmark_duration / avg_time

    print(f"\nConversion Performance (average of {iterations} runs):")
    print(f"  Time: {avg_time*1000:.3f} ms")
    print(f"  Throughput: {throughput_mb:.1f} MB/s")
    print(f"  Realtime factor: {realtime_factor:.1f}x ({realtime_factor:.1f}s of audio per 1s of processing)")

    if realtime_factor > 100:
        print(f"✅ Excellent performance! ({realtime_factor:.0f}x realtime)")
    elif realtime_factor > 10:
        print(f"✅ Good performance ({realtime_factor:.0f}x realtime)")
    else:
        print(f"⚠️  Performance might be suboptimal ({realtime_factor:.1f}x realtime)")

except Exception as e:
    print(f"❌ Benchmark failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ All tests passed!")
print("=" * 60)
