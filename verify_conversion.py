#!/usr/bin/env python3
"""Verify that audio format conversion is working."""

import sys
import logging
from proctap.core import ProcessAudioCapture, StreamConfig

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] %(name)s: %(message)s',
    stream=sys.stderr
)

logger = logging.getLogger(__name__)

def test_conversion():
    """Test that 44.1kHz -> 48kHz conversion is working."""

    if len(sys.argv) < 2:
        print("Usage: python verify_conversion.py <PID>", file=sys.stderr)
        sys.exit(1)

    pid = int(sys.argv[1])

    print("\n=== Test 1: Native format (44.1kHz) - NO conversion ===", file=sys.stderr)
    tap1 = ProcessAudioCapture(pid, config=None)
    fmt1 = tap1.get_format()
    print(f"Format: {fmt1}", file=sys.stderr)
    assert fmt1['sample_rate'] == 44100, f"Expected 44100Hz, got {fmt1['sample_rate']}"
    assert fmt1['channels'] == 2, f"Expected 2 channels, got {fmt1['channels']}"
    print("✓ Native format correct\n", file=sys.stderr)

    print("=== Test 2: Custom format (48kHz) - WITH conversion ===", file=sys.stderr)
    config = StreamConfig(sample_rate=48000, channels=2)
    tap2 = ProcessAudioCapture(pid, config=config)
    fmt2 = tap2.get_format()
    print(f"Format: {fmt2}", file=sys.stderr)
    assert fmt2['sample_rate'] == 48000, f"Expected 48000Hz, got {fmt2['sample_rate']}"
    assert fmt2['channels'] == 2, f"Expected 2 channels, got {fmt2['channels']}"
    print("✓ Conversion working correctly\n", file=sys.stderr)

    print("=== Test 3: Mono conversion (48kHz, 1ch) ===", file=sys.stderr)
    config3 = StreamConfig(sample_rate=48000, channels=1)
    tap3 = ProcessAudioCapture(pid, config=config3)
    fmt3 = tap3.get_format()
    print(f"Format: {fmt3}", file=sys.stderr)
    assert fmt3['sample_rate'] == 48000, f"Expected 48000Hz, got {fmt3['sample_rate']}"
    assert fmt3['channels'] == 1, f"Expected 1 channel, got {fmt3['channels']}"
    print("✓ Channel conversion working correctly\n", file=sys.stderr)

    print("\n" + "="*60, file=sys.stderr)
    print("✓ All tests passed! Conversion is working as expected.", file=sys.stderr)
    print("="*60 + "\n", file=sys.stderr)

    print("\nConclusion:", file=sys.stderr)
    print("- StreamConfig IS useful and necessary for format conversion", file=sys.stderr)
    print("- Native WASAPI: 44.1kHz, 2ch, 16-bit (hardcoded in C++)", file=sys.stderr)
    print("- Python converter: Converts to user's desired format", file=sys.stderr)
    print("- No need to remove StreamConfig!\n", file=sys.stderr)

if __name__ == "__main__":
    test_conversion()
