#!/usr/bin/env python3
"""
macOS Core Audio Process Tap native extension latency benchmark (Phase 4).

⚠️  WARNING: This benchmark uses ARCHIVED experimental backend (archive/experimental-backends/macos_native.py)
This backend is not used in production and has AMFI limitations on Apple Silicon.

For production use, see examples/macos_basic.py which uses the recommended ScreenCaptureKit backend.

This script measures the latency of the native C extension approach
vs the Swift CLI helper approach (Phase 3).

Target: <500ms initial latency (vs 625ms with Swift CLI)

Measurements:
- Native extension initialization time
- First audio chunk time
- Average chunk interval
- Comparison with Swift CLI helper

Usage:
    python macos_native_benchmark.py --duration 10
"""

import sys
import time
import statistics
from pathlib import Path

# Import from archived experimental backend
sys.path.insert(0, str(Path(__file__).parent.parent / "archive" / "experimental-backends"))

def benchmark_native_initialization():
    """Measure native extension initialization time."""
    try:
        from macos_native import MacOSNativeBackend, is_available  # type: ignore[import-not-found]
    except ImportError as e:
        print("Error: Could not import archived experimental backend")
        print(f"Details: {e}")
        print("\nThis benchmark uses the archived experimental backend which is not installed by default.")
        print("For production use, see examples/macos_basic.py with ScreenCaptureKit backend.")
        sys.exit(1)

    if not is_available():
        raise RuntimeError("Native macOS backend not available")

    print("=== Native Extension Initialization Latency ===")

    init_times = []
    for i in range(5):
        start = time.perf_counter()

        # Create backend with a dummy PID (won't actually capture)
        # This measures just the initialization overhead
        try:
            backend = MacOSNativeBackend(pid=1, sample_rate=48000, channels=2)
            # Note: start() will be called separately to measure capture startup
            backend.stop()  # Clean up immediately
        except Exception as e:
            print(f"  Run {i+1} failed: {e}")
            continue

        elapsed = time.perf_counter() - start
        init_times.append(elapsed * 1000)  # Convert to ms

    if init_times:
        print(f"  Runs: {len(init_times)}")
        print(f"  Min:  {min(init_times):.2f} ms")
        print(f"  Max:  {max(init_times):.2f} ms")
        print(f"  Avg:  {statistics.mean(init_times):.2f} ms")
        print(f"  Std:  {statistics.stdev(init_times):.2f} ms" if len(init_times) > 1 else "  Std:  N/A")
    else:
        print("  ERROR: No successful runs")
    print()

    return init_times


def benchmark_capture_startup():
    """Measure time to start capture and receive first data."""
    try:
        from macos_native import MacOSNativeBackend, is_available  # type: ignore[import-not-found]
    except ImportError as e:
        print("Error: Could not import archived experimental backend")
        print(f"Details: {e}")
        sys.exit(1)

    if not is_available():
        raise RuntimeError("Native macOS backend not available")

    print("=== Capture Startup Latency ===")

    # Use system audio (PID 0 for global capture)
    backend = MacOSNativeBackend(pid=0, sample_rate=48000, channels=2)

    # Measure time to start capture
    start_time = time.perf_counter()
    backend.start()
    startup_time = time.perf_counter() - start_time
    print(f"  Capture startup: {startup_time * 1000:.2f} ms")

    # Measure time to first data
    first_data_start = time.perf_counter()
    max_wait = 5.0  # 5 second timeout
    first_data_time = None

    while (time.perf_counter() - first_data_start) < max_wait:
        data = backend.read(max_bytes=8192)
        if data and len(data) > 0:
            first_data_time = time.perf_counter() - first_data_start
            print(f"  First data:      {first_data_time * 1000:.2f} ms")
            print(f"  First data size: {len(data)} bytes")
            break
        time.sleep(0.001)  # 1ms poll interval

    if first_data_time is None:
        print("  ERROR: No data received within timeout")
        backend.stop()
        return None

    # Measure chunk intervals
    chunk_times = []
    chunks_received = 1
    last_time = time.perf_counter()
    duration = 5.0  # 5 seconds of measurement

    while (time.perf_counter() - first_data_start) < duration:
        data = backend.read(max_bytes=8192)
        if data and len(data) > 0:
            now = time.perf_counter()
            interval = now - last_time
            chunk_times.append(interval * 1000)  # ms
            last_time = now
            chunks_received += 1

    backend.stop()

    if chunk_times:
        print(f"\n  Chunks received: {chunks_received}")
        print(f"  Interval min:    {min(chunk_times):.2f} ms")
        print(f"  Interval max:    {max(chunk_times):.2f} ms")
        print(f"  Interval avg:    {statistics.mean(chunk_times):.2f} ms")
        print(f"  Interval std:    {statistics.stdev(chunk_times):.2f} ms")
        print(f"  Jitter (stddev): {statistics.stdev(chunk_times):.2f} ms")
    print()

    return {
        'startup_time': startup_time * 1000,
        'first_data_time': first_data_time * 1000,
        'chunk_intervals': chunk_times,
        'chunks_received': chunks_received
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark macOS native extension latency (Phase 4)")
    parser.add_argument('--duration', type=int, default=5,
                        help='Benchmark duration in seconds (default: 5)')
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("macOS Core Audio Process Tap Native Extension Benchmark (Phase 4)")
    print("Target: <500ms initial latency (vs 625ms Phase 3 Swift CLI)")
    print("=" * 70)
    print()

    try:
        # Benchmark initialization
        init_times = benchmark_native_initialization()

        # Benchmark capture startup
        capture_data = benchmark_capture_startup()

        if not init_times or not capture_data:
            print("ERROR: Benchmark failed")
            return 1

        # Summary
        print("=" * 70)
        print("Phase 4 Results Summary")
        print("=" * 70)
        avg_init = statistics.mean(init_times)
        startup = capture_data['startup_time']
        first_data = capture_data['first_data_time']
        avg_interval = statistics.mean(capture_data['chunk_intervals'])
        jitter = statistics.stdev(capture_data['chunk_intervals'])

        print(f"  Initialization:     {avg_init:.2f} ms")
        print(f"  Capture startup:    {startup:.2f} ms")
        print(f"  Time to first data: {first_data:.2f} ms")
        print(f"  Average chunk time: {avg_interval:.2f} ms")
        print(f"  Jitter:             {jitter:.2f} ms")
        print()

        total_latency = avg_init + startup + first_data
        print(f"  **Total end-to-end latency: {total_latency:.2f} ms**")
        print()

        # Comparison with Phase 3
        phase3_latency = 625.34  # From Phase 3 benchmark
        improvement = phase3_latency - total_latency
        improvement_pct = (improvement / phase3_latency) * 100

        print("=" * 70)
        print("Comparison with Phase 3 (Swift CLI)")
        print("=" * 70)
        print(f"  Phase 3 (Swift CLI):     {phase3_latency:.2f} ms")
        print(f"  Phase 4 (Native C):      {total_latency:.2f} ms")
        print(f"  Improvement:             {improvement:.2f} ms ({improvement_pct:.1f}%)")
        print()

        if total_latency < 500:
            print(f"  ✅ TARGET ACHIEVED: {total_latency:.2f}ms < 500ms")
        else:
            print(f"  ⚠️  Target not met: {total_latency:.2f}ms >= 500ms")
            print(f"     (Still {total_latency - 500:.2f}ms over target)")
        print()

        print("=" * 70)
        print()

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
