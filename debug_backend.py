#!/usr/bin/env python3
"""Debug script to test backend initialization and data flow."""

import sys
import argparse
import time

def main():
    parser = argparse.ArgumentParser(description='Debug backend initialization')
    parser.add_argument('--pid', type=int, required=True, help='Process ID')
    args = parser.parse_args()

    print(f"=== Testing ProcTap Backend for PID {args.pid} ===\n", file=sys.stderr)

    # Test 1: Import backend
    print("1. Testing backend import...", file=sys.stderr)
    try:
        from proctap.backends import get_backend
        print("   ✓ Backend import successful", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ Backend import failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Test 2: Create backend instance
    print("\n2. Creating backend instance...", file=sys.stderr)
    try:
        backend = get_backend(
            pid=args.pid,
            sample_rate=48000,
            channels=2,
            sample_width=2,
        )
        print(f"   ✓ Backend created: {backend.__class__.__name__}", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ Backend creation failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    # Test 3: Get format
    print("\n3. Getting audio format...", file=sys.stderr)
    try:
        fmt = backend.get_format()
        print(f"   ✓ Format: {fmt}", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ get_format() failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)

    # Test 4: Start capture
    print("\n4. Starting capture...", file=sys.stderr)
    try:
        backend.start()
        print("   ✓ Capture started", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ start() failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    # Test 5: Read data
    print("\n5. Reading data (5 second test)...", file=sys.stderr)
    total_bytes = 0
    read_count = 0
    empty_count = 0
    start_time = time.time()

    while time.time() - start_time < 5.0:
        try:
            data = backend.read()
            read_count += 1

            if data:
                total_bytes += len(data)
                print(f"   → Read {len(data)} bytes (total: {total_bytes}, reads: {read_count})", file=sys.stderr)
            else:
                empty_count += 1
                if empty_count % 100 == 0:
                    print(f"   → Empty reads: {empty_count}", file=sys.stderr)

            time.sleep(0.01)  # 10ms polling

        except Exception as e:
            print(f"   ✗ read() error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            break

    # Test 6: Stop capture
    print("\n6. Stopping capture...", file=sys.stderr)
    try:
        backend.stop()
        print("   ✓ Capture stopped", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ stop() failed: {e}", file=sys.stderr)

    # Summary
    print("\n=== Summary ===", file=sys.stderr)
    print(f"Total bytes received: {total_bytes}", file=sys.stderr)
    print(f"Total read calls: {read_count}", file=sys.stderr)
    print(f"Empty reads: {empty_count}", file=sys.stderr)

    if total_bytes == 0:
        print("\n⚠️  WARNING: No audio data captured!", file=sys.stderr)
        print("Possible reasons:", file=sys.stderr)
        print("  1. Process is not currently playing audio", file=sys.stderr)
        print("  2. Process doesn't have audio output permissions", file=sys.stderr)
        print("  3. Wrong platform (running in WSL instead of native Windows)", file=sys.stderr)
        print("  4. Windows version too old (requires Windows 10 20H1+)", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\n✓ SUCCESS: Captured {total_bytes} bytes in 5 seconds", file=sys.stderr)
        print(f"  Average rate: {total_bytes / 5:.0f} bytes/sec", file=sys.stderr)

        # Expected rate for 48kHz stereo 16-bit: 192000 bytes/sec
        expected_rate = 48000 * 2 * 2
        actual_rate = total_bytes / 5
        print(f"  Expected rate: {expected_rate} bytes/sec (48kHz stereo 16-bit)", file=sys.stderr)
        print(f"  Actual/Expected ratio: {actual_rate / expected_rate * 100:.1f}%", file=sys.stderr)

if __name__ == '__main__':
    main()
