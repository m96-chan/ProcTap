"""
Performance benchmarks for audio format converter optimizations (Issue #9 Phase 1).

Benchmarks all three Python-level optimizations:
1.1: Format detection caching
1.2: Vectorized channel conversion
1.3: Optimized 24-bit PCM conversion

Target: <1ms per 10ms audio chunk (at 44.1kHz, 2ch, 16-bit = 1764 bytes)
"""

import time
import numpy as np
from proctap.backends.converter import AudioConverter, SampleFormat


def benchmark_format_detection_caching():
    """Benchmark format detection caching (Optimization 1.1)."""
    print("\n=== Benchmark 1.1: Format Detection Caching ===")

    converter = AudioConverter(
        src_rate=44100, src_channels=2, src_width=2,
        dst_rate=44100, dst_channels=2, dst_width=2,
        auto_detect_format=True
    )

    # Create 10ms of audio at 44.1kHz stereo (1764 bytes)
    num_samples = int(44100 * 0.01)
    audio = (np.sin(2 * np.pi * 440 * np.arange(num_samples) / 44100) * 32767).astype(np.int16)
    stereo = np.tile(audio, (2, 1)).T.flatten()
    pcm_bytes = stereo.tobytes()

    # Warmup
    for _ in range(10):
        converter.convert(pcm_bytes)

    # Benchmark: Process 1000 chunks (simulating 10 seconds of audio)
    num_iterations = 1000
    start_time = time.perf_counter()

    for _ in range(num_iterations):
        converter.convert(pcm_bytes)

    end_time = time.perf_counter()
    total_time = end_time - start_time
    avg_time_ms = (total_time / num_iterations) * 1000

    print(f"  Chunk size: {len(pcm_bytes)} bytes (10ms audio)")
    print(f"  Iterations: {num_iterations}")
    print(f"  Total time: {total_time:.4f} seconds")
    print(f"  Average time per chunk: {avg_time_ms:.4f} ms")
    print(f"  Target: <1.0 ms per chunk")
    print(f"  Status: {'✅ PASS' if avg_time_ms < 1.0 else '❌ FAIL'}")

    return avg_time_ms


def benchmark_channel_conversion():
    """Benchmark vectorized channel conversion (Optimization 1.2)."""
    print("\n=== Benchmark 1.2: Vectorized Channel Conversion ===")

    # Test multiple conversion scenarios
    scenarios = [
        ("Stereo -> Mono", 2, 1),
        ("Mono -> Stereo", 1, 2),
        ("Stereo -> 5.1", 2, 6),
        ("5.1 -> Stereo", 6, 2),
    ]

    results = {}

    for name, src_ch, dst_ch in scenarios:
        converter = AudioConverter(
            src_rate=44100, src_channels=src_ch, src_width=2,
            dst_rate=44100, dst_channels=dst_ch, dst_width=2,
            auto_detect_format=False
        )

        # Create 10ms of audio
        num_samples = int(44100 * 0.01)
        audio_mono = (np.sin(2 * np.pi * 440 * np.arange(num_samples) / 44100) * 32767).astype(np.int16)

        if src_ch == 1:
            pcm_bytes = audio_mono.tobytes()
        else:
            # Create multi-channel audio
            multi = np.tile(audio_mono, (src_ch, 1)).T.flatten()
            pcm_bytes = multi.tobytes()

        # Warmup
        for _ in range(10):
            converter.convert(pcm_bytes)

        # Benchmark
        num_iterations = 1000
        start_time = time.perf_counter()

        for _ in range(num_iterations):
            converter.convert(pcm_bytes)

        end_time = time.perf_counter()
        total_time = end_time - start_time
        avg_time_ms = (total_time / num_iterations) * 1000

        results[name] = avg_time_ms

        print(f"  {name}:")
        print(f"    Average time: {avg_time_ms:.4f} ms")
        print(f"    Status: {'✅ PASS' if avg_time_ms < 1.0 else '❌ FAIL'}")

    return results


def benchmark_24bit_conversion():
    """Benchmark optimized 24-bit PCM conversion (Optimization 1.3)."""
    print("\n=== Benchmark 1.3: Optimized 24-bit PCM Conversion ===")

    # Test both encoding and decoding
    scenarios = [
        ("16-bit -> 24-bit encoding", 2, 2, 3, SampleFormat.INT16, SampleFormat.INT24),
        ("24-bit -> 16-bit decoding", 2, 3, 2, SampleFormat.INT24, SampleFormat.INT16),
    ]

    results = {}

    for name, channels, src_width, dst_width, src_fmt, dst_fmt in scenarios:
        converter = AudioConverter(
            src_rate=44100, src_channels=channels, src_width=src_width,
            dst_rate=44100, dst_channels=channels, dst_width=dst_width,
            src_format=src_fmt, dst_format=dst_fmt,
            auto_detect_format=False
        )

        # Create 10ms of audio
        num_samples = int(44100 * 0.01) * channels

        if src_fmt == SampleFormat.INT16:
            audio = (np.sin(2 * np.pi * 440 * np.arange(num_samples) / 44100) * 32767).astype(np.int16)
            pcm_bytes = audio.tobytes()
        else:  # INT24
            # Create 24-bit audio
            audio_int = (np.sin(2 * np.pi * 440 * np.arange(num_samples) / 44100) * 8388607).astype(np.int32)
            pcm_bytes = bytearray()
            for val in audio_int:
                pcm_bytes.extend([
                    val & 0xFF,
                    (val >> 8) & 0xFF,
                    (val >> 16) & 0xFF
                ])
            pcm_bytes = bytes(pcm_bytes)

        # Warmup
        for _ in range(10):
            converter.convert(pcm_bytes)

        # Benchmark
        num_iterations = 1000
        start_time = time.perf_counter()

        for _ in range(num_iterations):
            converter.convert(pcm_bytes)

        end_time = time.perf_counter()
        total_time = end_time - start_time
        avg_time_ms = (total_time / num_iterations) * 1000

        results[name] = avg_time_ms

        print(f"  {name}:")
        print(f"    Average time: {avg_time_ms:.4f} ms")
        print(f"    Status: {'✅ PASS' if avg_time_ms < 1.0 else '❌ FAIL'}")

    return results


def benchmark_complex_conversion():
    """Benchmark complex conversion chain (resampling + channel conversion)."""
    print("\n=== Benchmark: Complex Conversion Chain ===")

    # Realistic scenario: 44.1kHz stereo 16-bit -> 48kHz mono 16-bit
    converter = AudioConverter(
        src_rate=44100, src_channels=2, src_width=2,
        dst_rate=48000, dst_channels=1, dst_width=2,
        auto_detect_format=False
    )

    # Create 10ms of audio
    num_samples = int(44100 * 0.01)
    audio = (np.sin(2 * np.pi * 440 * np.arange(num_samples) / 44100) * 32767).astype(np.int16)
    stereo = np.tile(audio, (2, 1)).T.flatten()
    pcm_bytes = stereo.tobytes()

    # Warmup
    for _ in range(10):
        converter.convert(pcm_bytes)

    # Benchmark
    num_iterations = 1000
    start_time = time.perf_counter()

    for _ in range(num_iterations):
        converter.convert(pcm_bytes)

    end_time = time.perf_counter()
    total_time = end_time - start_time
    avg_time_ms = (total_time / num_iterations) * 1000

    print(f"  Scenario: 44.1kHz stereo -> 48kHz mono (with resampling)")
    print(f"  Average time: {avg_time_ms:.4f} ms")
    print(f"  Target: <1.0 ms per chunk")
    print(f"  Status: {'✅ PASS' if avg_time_ms < 1.0 else '❌ FAIL'}")
    print(f"  Note: This includes resampling overhead, which is expected to be higher")

    return avg_time_ms


def main():
    """Run all benchmarks and print summary."""
    print("=" * 70)
    print("Audio Format Converter Optimization Benchmarks")
    print("Issue #9 Phase 1: Python-level Optimization")
    print("=" * 70)

    # Run benchmarks
    format_detection_time = benchmark_format_detection_caching()
    channel_conversion_results = benchmark_channel_conversion()
    bit24_conversion_results = benchmark_24bit_conversion()
    complex_conversion_time = benchmark_complex_conversion()

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print("\n1.1 Format Detection Caching:")
    print(f"  Average time: {format_detection_time:.4f} ms")
    print(f"  Target: <1.0 ms")
    print(f"  Status: {'✅ PASS' if format_detection_time < 1.0 else '❌ FAIL'}")

    print("\n1.2 Vectorized Channel Conversion:")
    for name, time_ms in channel_conversion_results.items():
        status = '✅ PASS' if time_ms < 1.0 else '❌ FAIL'
        print(f"  {name}: {time_ms:.4f} ms - {status}")

    print("\n1.3 Optimized 24-bit PCM Conversion:")
    for name, time_ms in bit24_conversion_results.items():
        status = '✅ PASS' if time_ms < 1.0 else '❌ FAIL'
        print(f"  {name}: {time_ms:.4f} ms - {status}")

    print("\nComplex Conversion Chain:")
    print(f"  Average time: {complex_conversion_time:.4f} ms")
    print(f"  Note: Includes resampling - expected to be higher than simple conversions")

    # Overall assessment
    print("\n" + "=" * 70)
    simple_conversions = [format_detection_time] + list(channel_conversion_results.values()) + list(bit24_conversion_results.values())
    max_simple_time = max(simple_conversions)

    if max_simple_time < 1.0:
        print("✅ SUCCESS: All simple conversions meet <1ms target!")
        print("Phase 1 Python-level optimizations are sufficient.")
    else:
        print("⚠️  Some conversions exceed 1ms target.")
        print("Consider Phase 2: C++ implementation if performance is critical.")

    print("=" * 70)


if __name__ == '__main__':
    main()
