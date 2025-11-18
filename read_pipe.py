#!/usr/bin/env python3
"""Continuous pipe reader for testing proctap."""

import sys
import time

total = 0
start = time.time()
chunk_size = 4096

print("Reading from stdin...", file=sys.stderr)

try:
    while True:
        data = sys.stdin.buffer.read(chunk_size)
        if not data:
            break
        total += len(data)
        elapsed = time.time() - start
        if elapsed > 0:
            rate = total / elapsed
            print(f"\rReceived: {total:,} bytes | Rate: {rate:,.0f} bytes/sec | Time: {elapsed:.1f}s",
                  end='', file=sys.stderr)
except KeyboardInterrupt:
    pass

elapsed = time.time() - start
print(f"\n\nTotal: {total:,} bytes in {elapsed:.1f} seconds", file=sys.stderr)
print(f"Average rate: {total/elapsed:,.0f} bytes/sec", file=sys.stderr)
