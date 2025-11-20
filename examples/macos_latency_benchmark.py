#!/usr/bin/env python3
"""
macOS Core Audio Process Tap latency benchmark.

⚠️  WARNING: This benchmark uses ARCHIVED experimental backend (archive/experimental-backends/macos.py)
This backend is not used in production and has AMFI limitations on Apple Silicon.

For production use, see examples/macos_basic.py which uses the recommended ScreenCaptureKit backend.

This script measures the latency of the Swift CLI helper approach
for audio capture on macOS.

Measurements:
- Helper startup time
- First audio chunk time
- Average chunk interval

Usage:
    python macos_latency_benchmark.py --duration 10
"""

import sys
import time
import subprocess
import statistics
from pathlib import Path

# Import from archived experimental backend
sys.path.insert(0, str(Path(__file__).parent.parent / "archive" / "experimental-backends"))

try:
    from macos import find_helper_binary  # type: ignore[import-not-found]
except ImportError as e:
    print("Error: Could not import archived experimental backend")
    print(f"Details: {e}")
    print("\nThis benchmark uses the archived experimental backend which is not installed by default.")
    print("For production use, see examples/macos_basic.py with ScreenCaptureKit backend.")
    sys.exit(1)


def benchmark_helper_startup():
    """Measure helper process startup time."""
    helper = find_helper_binary()
    if not helper:
        raise RuntimeError("Helper binary not found")

    print("=== Helper Startup Latency ===")

    startup_times = []
    for i in range(5):
        start = time.perf_counter()
        proc = subprocess.Popen(
            [str(helper), "--sample-rate", "48000", "--channels", "2"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        # Wait for first stderr output (indicates initialization)
        proc.stderr.readline()
        elapsed = time.perf_counter() - start
        startup_times.append(elapsed * 1000)  # Convert to ms

        proc.terminate()
        proc.wait()

    print(f"  Runs: {len(startup_times)}")
    print(f"  Min:  {min(startup_times):.2f} ms")
    print(f"  Max:  {max(startup_times):.2f} ms")
    print(f"  Avg:  {statistics.mean(startup_times):.2f} ms")
    print(f"  Std:  {statistics.stdev(startup_times):.2f} ms")
    print()

    return startup_times


def benchmark_chunk_latency(duration=10):
    """Measure time to first chunk and chunk intervals."""
    helper = find_helper_binary()
    if not helper:
        raise RuntimeError("Helper binary not found")

    print("=== Audio Chunk Latency ===")
    print(f"Duration: {duration} seconds")

    proc = subprocess.Popen(
        [str(helper), "--sample-rate", "48000", "--channels", "2"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0
    )

    # Wait for "Audio capture started" message
    start_time = time.perf_counter()
    while True:
        line = proc.stderr.readline().decode('utf-8', errors='ignore')
        if 'Audio capture started' in line:
            init_time = time.perf_counter() - start_time
            print(f"  Initialization: {init_time * 1000:.2f} ms")
            break
        if time.perf_counter() - start_time > 5:
            print("  ERROR: Timeout waiting for capture start")
            proc.terminate()
            return

    # Measure time to first audio chunk
    first_chunk_start = time.perf_counter()
    chunk_size = 48000 * 2 * 2 * 0.01  # 10ms chunks (48kHz, 2ch, 16-bit)
    chunk = proc.stdout.read(int(chunk_size))
    if chunk:
        first_chunk_time = time.perf_counter() - first_chunk_start
        print(f"  First chunk:    {first_chunk_time * 1000:.2f} ms")

    # Measure chunk intervals
    chunk_times = []
    chunks_received = 1
    last_time = time.perf_counter()
    end_time = time.perf_counter() + duration

    while time.perf_counter() < end_time:
        chunk = proc.stdout.read(int(chunk_size))
        if chunk:
            now = time.perf_counter()
            interval = now - last_time
            chunk_times.append(interval * 1000)  # ms
            last_time = now
            chunks_received += 1

    proc.terminate()
    proc.wait()

    if chunk_times:
        print(f"\n  Chunks received: {chunks_received}")
        print(f"  Interval min:    {min(chunk_times):.2f} ms")
        print(f"  Interval max:    {max(chunk_times):.2f} ms")
        print(f"  Interval avg:    {statistics.mean(chunk_times):.2f} ms")
        print(f"  Interval std:    {statistics.stdev(chunk_times):.2f} ms")
        print(f"\n  Expected interval: 10.00 ms (for 10ms chunks)")
        print(f"  Actual avg:        {statistics.mean(chunk_times):.2f} ms")
        jitter = statistics.stdev(chunk_times)
        print(f"  Jitter (stddev):   {jitter:.2f} ms")
    print()

    return {
        'init_time': init_time * 1000,
        'first_chunk_time': first_chunk_time * 1000,
        'chunk_intervals': chunk_times,
        'chunks_received': chunks_received
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark macOS audio capture latency")
    parser.add_argument('--duration', type=int, default=10,
                        help='Benchmark duration in seconds (default: 10)')
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("macOS Core Audio Process Tap Latency Benchmark")
    print("=" * 60)
    print()

    try:
        # Benchmark helper startup
        startup_times = benchmark_helper_startup()

        # Benchmark chunk latency
        chunk_data = benchmark_chunk_latency(duration=args.duration)

        # Summary
        print("=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"  Helper startup:     {statistics.mean(startup_times):.2f} ms")
        print(f"  Time to capture:    {chunk_data['init_time']:.2f} ms")
        print(f"  Time to first data: {chunk_data['first_chunk_time']:.2f} ms")
        print(f"  Average chunk time: {statistics.mean(chunk_data['chunk_intervals']):.2f} ms")
        print(f"  Jitter:             {statistics.stdev(chunk_data['chunk_intervals']):.2f} ms")
        print()

        total_latency = (statistics.mean(startup_times) +
                        chunk_data['init_time'] +
                        chunk_data['first_chunk_time'])
        print(f"  Total end-to-end latency: {total_latency:.2f} ms")
        print("=" * 60)
        print()

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
