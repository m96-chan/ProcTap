#!/usr/bin/env python3
"""Diagnose pipe issue between proctap and consumer."""

import sys
import subprocess
import threading
import time

def read_stream(stream, name, callback):
    """Read from a stream in a thread."""
    try:
        while True:
            line = stream.readline()
            if not line:
                break
            callback(name, line)
    except Exception as e:
        print(f"Error reading {name}: {e}", file=sys.stderr)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    args = parser.parse_args()

    print(f"Testing pipe with PID {args.pid}\n", file=sys.stderr)

    # Start proctap
    cmd = [sys.executable, '-m', 'proctap', '--pid', str(args.pid), '--stdout', '--verbose']
    print(f"Command: {' '.join(cmd)}\n", file=sys.stderr)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    stderr_lines = []
    def log_output(source, data):
        try:
            line = data.decode('utf-8', errors='replace').rstrip()
            stderr_lines.append(line)
            print(f"[{source}] {line}", file=sys.stderr)
        except:
            pass

    # Start stderr reader thread
    stderr_thread = threading.Thread(
        target=read_stream,
        args=(proc.stderr, 'STDERR', log_output),
        daemon=True
    )
    stderr_thread.start()

    print("Waiting for proctap to initialize...", file=sys.stderr)
    time.sleep(1)

    # Check if process is still alive
    if proc.poll() is not None:
        print(f"\n❌ Process died immediately with code: {proc.returncode}", file=sys.stderr)
        print("\nStderr output:", file=sys.stderr)
        for line in stderr_lines:
            print(f"  {line}", file=sys.stderr)
        return 1

    print("\nProcess is running. Reading from stdout...", file=sys.stderr)

    total_bytes = 0
    chunks = 0
    start_time = time.time()

    try:
        # Try to read for 5 seconds
        while time.time() - start_time < 5.0:
            # Check if process died
            if proc.poll() is not None:
                print(f"\n⚠️  Process terminated with code: {proc.returncode}", file=sys.stderr)
                break

            # Try reading with timeout
            import select
            import os

            # Non-blocking read attempt (Windows doesn't support select on pipes)
            try:
                # Read a small chunk
                chunk = proc.stdout.read(1024)
                if chunk:
                    total_bytes += len(chunk)
                    chunks += 1
                    elapsed = time.time() - start_time
                    rate = total_bytes / elapsed if elapsed > 0 else 0
                    print(f"\rBytes: {total_bytes:,} | Chunks: {chunks} | Rate: {rate:,.0f} B/s | Time: {elapsed:.1f}s",
                          end='', file=sys.stderr)
                else:
                    # No data available, short sleep
                    time.sleep(0.01)
            except Exception as e:
                print(f"\n❌ Read error: {e}", file=sys.stderr)
                break

    except KeyboardInterrupt:
        print("\n\nInterrupted by user", file=sys.stderr)

    # Cleanup
    print("\n\nTerminating proctap...", file=sys.stderr)
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except:
        proc.kill()

    # Summary
    elapsed = time.time() - start_time
    print(f"\n=== Summary ===", file=sys.stderr)
    print(f"Total bytes: {total_bytes:,}", file=sys.stderr)
    print(f"Chunks received: {chunks}", file=sys.stderr)
    print(f"Duration: {elapsed:.1f}s", file=sys.stderr)
    if elapsed > 0:
        print(f"Average rate: {total_bytes/elapsed:,.0f} bytes/sec", file=sys.stderr)

    if total_bytes == 0:
        print("\n❌ FAILED: No data received", file=sys.stderr)
        print("\nFull stderr log:", file=sys.stderr)
        for line in stderr_lines:
            print(f"  {line}", file=sys.stderr)
        return 1
    else:
        print(f"\n✓ SUCCESS: Received {total_bytes:,} bytes", file=sys.stderr)
        return 0

if __name__ == '__main__':
    sys.exit(main())
