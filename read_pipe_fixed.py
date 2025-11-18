#!/usr/bin/env python3
"""Continuous pipe reader with immediate stdin opening."""

import sys
import time
import os

# Ensure stdin is in binary mode and unbuffered
if hasattr(sys.stdin, 'buffer'):
    stdin = sys.stdin.buffer
else:
    stdin = sys.stdin

# On Windows, set binary mode
if sys.platform == 'win32':
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)

total = 0
start = time.time()
chunk_size = 4096
last_print = 0

print("Ready to read from stdin...", file=sys.stderr, flush=True)

# Give proctap time to start writing
time.sleep(0.1)

try:
    while True:
        data = stdin.read(chunk_size)
        if not data:
            # Check if we received any data at all
            if total == 0:
                print("No data received - stdin closed immediately", file=sys.stderr, flush=True)
            break

        total += len(data)
        elapsed = time.time() - start

        # Print every 0.5 seconds to avoid too much output
        if elapsed - last_print > 0.5:
            if elapsed > 0:
                rate = total / elapsed
                print(f"\rReceived: {total:,} bytes | Rate: {rate:,.0f} bytes/sec | Time: {elapsed:.1f}s",
                      end='', file=sys.stderr, flush=True)
                last_print = elapsed

except KeyboardInterrupt:
    print("\nInterrupted", file=sys.stderr, flush=True)
except Exception as e:
    print(f"\nError: {e}", file=sys.stderr, flush=True)
    import traceback
    traceback.print_exc(file=sys.stderr)

elapsed = time.time() - start
print(f"\n\nTotal: {total:,} bytes in {elapsed:.1f} seconds", file=sys.stderr, flush=True)
if elapsed > 0:
    print(f"Average rate: {total/elapsed:,.0f} bytes/sec", file=sys.stderr, flush=True)
