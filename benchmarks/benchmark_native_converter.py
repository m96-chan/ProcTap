#!/usr/bin/env python3
"""
Benchmark the native SIMD audio converter (Windows only).

Example:
    python benchmarks/benchmark_native_converter.py --quality high --seconds 5 --iterations 25
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from proctap.converter_native import NativeAudioConverter, HAS_NATIVE_CONVERTER
from proctap.format import ResamplingQuality, FIXED_AUDIO_FORMAT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark native SIMD converter")
    parser.add_argument("--rate", type=int, default=44100, help="Source sample rate (Hz)")
    parser.add_argument("--channels", type=int, default=2, choices=[1, 2], help="Source channel count")
    parser.add_argument("--seconds", type=float, default=10.0, help="Duration of synthetic audio per iteration")
    parser.add_argument("--iterations", type=int, default=25, help="Benchmark iterations")
    parser.add_argument(
        "--quality",
        choices=["low", "high"],
        default="low",
        help="Resampling quality (low=linear, high=libsamplerate)",
    )
    parser.add_argument("--seed", type=int, default=1337, help="Random seed for reproducible data")
    return parser.parse_args()


def main() -> int:
    if not HAS_NATIVE_CONVERTER:
        print("Native converter is not available on this platform/build.", file=sys.stderr)
        return 1

    args = parse_args()
    quality = (
        ResamplingQuality.HIGH_QUALITY if args.quality == "high" else ResamplingQuality.LOW_LATENCY
    )

    converter = NativeAudioConverter(quality=quality)
    if quality == ResamplingQuality.HIGH_QUALITY and converter.quality != ResamplingQuality.HIGH_QUALITY:
        print("libsamplerate not detected – falling back to low-latency mode.", file=sys.stderr)

    frame_count = int(args.seconds * args.rate)
    total_samples = frame_count * args.channels
    rng = np.random.default_rng(args.seed)
    src_int16 = rng.integers(-32768, 32767, size=total_samples, dtype=np.int16).tobytes()

    print("=" * 72)
    print(" Native SIMD Converter Benchmark ")
    print("=" * 72)
    print(f"Source: {args.rate} Hz | {args.channels} ch | {args.seconds:.2f}s per iteration")
    print(f"Iterations: {args.iterations}")
    print(f"Native quality: {converter.quality.name.lower()}")  # type: ignore[attr-defined]
    print(f"Target format: {FIXED_AUDIO_FORMAT.sample_rate} Hz | "
          f"{FIXED_AUDIO_FORMAT.channels} ch | float32")

    # Warmup
    converter.convert_to_fixed_format(src_int16, args.rate, args.channels, "int16")

    start = time.perf_counter()
    for _ in range(args.iterations):
        converter.convert_to_fixed_format(src_int16, args.rate, args.channels, "int16")
    elapsed = time.perf_counter() - start

    processed_audio = args.seconds * args.iterations
    realtime_factor = processed_audio / elapsed if elapsed > 0 else float("inf")
    throughput_mb = (len(src_int16) * args.iterations) / (1024 * 1024) / elapsed if elapsed > 0 else 0.0

    print("\nResults:")
    print(f"  Total time:      {elapsed:.3f} s")
    print(f"  Audio processed: {processed_audio:.2f} s")
    print(f"  Realtime factor: {realtime_factor:.1f}x")
    print(f"  Throughput:      {throughput_mb:.1f} MB/s")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(main())
