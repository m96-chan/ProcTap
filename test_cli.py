#!/usr/bin/env python3
"""Test CLI functionality with detailed logging."""

import sys
import subprocess
import time
import argparse

def main():
    parser = argparse.ArgumentParser(description='Test CLI with subprocess')
    parser.add_argument('--pid', type=int, required=True, help='Process ID')
    parser.add_argument('--duration', type=float, default=5.0, help='Duration in seconds')
    args = parser.parse_args()

    print(f"Testing proctap CLI for PID {args.pid}...\n", file=sys.stderr)

    # Start proctap as subprocess
    cmd = [sys.executable, '-m', 'proctap', '--pid', str(args.pid), '--stdout', '--verbose']

    print(f"Command: {' '.join(cmd)}", file=sys.stderr)
    print("Starting subprocess...\n", file=sys.stderr)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,  # Unbuffered
        )

        total_bytes = 0
        start_time = time.time()
        stderr_output = []

        print("Reading data...", file=sys.stderr)

        # Read for specified duration
        while time.time() - start_time < args.duration:
            # Check if process is still alive
            if proc.poll() is not None:
                print(f"\n⚠️  Process terminated early with code: {proc.returncode}", file=sys.stderr)
                break

            # Try to read some data
            try:
                data = proc.stdout.read(1024)
                if data:
                    total_bytes += len(data)
                    print(f"  Read {len(data)} bytes (total: {total_bytes})", file=sys.stderr)
            except Exception as e:
                print(f"  Error reading stdout: {e}", file=sys.stderr)
                break

            time.sleep(0.01)

        # Terminate the process
        print("\nTerminating subprocess...", file=sys.stderr)
        proc.terminate()
        proc.wait(timeout=2.0)

        # Read any remaining stderr
        stderr_data = proc.stderr.read()
        if stderr_data:
            print("\n=== STDERR Output ===", file=sys.stderr)
            print(stderr_data.decode('utf-8', errors='replace'), file=sys.stderr)
            print("=== End STDERR ===\n", file=sys.stderr)

        # Summary
        print(f"Total bytes received: {total_bytes}", file=sys.stderr)

        if total_bytes == 0:
            print("\n❌ FAILED: No data received from proctap CLI", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"\n✓ SUCCESS: Received {total_bytes} bytes in {args.duration} seconds", file=sys.stderr)
            print(f"  Average rate: {total_bytes / args.duration:.0f} bytes/sec", file=sys.stderr)

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
