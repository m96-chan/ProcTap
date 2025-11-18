#!/usr/bin/env python3
"""Test script to verify audio capture from a process."""

import sys
import argparse
from proctap import ProcessAudioCapture

def main():
    parser = argparse.ArgumentParser(description='Test audio capture')
    parser.add_argument('--pid', type=int, required=True, help='Process ID to capture')
    parser.add_argument('--duration', type=float, default=2.0, help='Capture duration in seconds')
    args = parser.parse_args()

    print(f"Testing capture from PID {args.pid}...", file=sys.stderr)

    total_bytes = 0

    def on_data(data, frames):
        nonlocal total_bytes
        total_bytes += len(data)
        print(f"Received {len(data)} bytes (total: {total_bytes})", file=sys.stderr)

    try:
        tap = ProcessAudioCapture(args.pid, on_data=on_data)
        print(f"Backend: {tap._backend.__class__.__name__}", file=sys.stderr)
        print(f"Platform: {sys.platform}", file=sys.stderr)

        tap.start()

        import time
        time.sleep(args.duration)

        tap.stop()

        print(f"\nTotal captured: {total_bytes} bytes", file=sys.stderr)

        if total_bytes == 0:
            print("\n⚠️  No audio data captured!", file=sys.stderr)
            print("Possible reasons:", file=sys.stderr)
            print("  1. Process is not playing audio", file=sys.stderr)
            print("  2. Wrong platform (WSL cannot capture Windows processes)", file=sys.stderr)
            print("  3. Insufficient permissions", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"\n✓ Successfully captured {total_bytes} bytes", file=sys.stderr)

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
