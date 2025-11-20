#!/usr/bin/env python3
"""
ScreenCaptureKit Backend Test for macOS 13+

This example demonstrates bundleID-based audio capture using ScreenCaptureKit.

Requirements:
- macOS 13.0 (Ventura) or later
- Screen Recording permission enabled for Terminal
- Swift helper binary built: cd src/proctap/swift/screencapture-audio && swift build

Usage:
    python examples/macos_screencapture_test.py --bundle-id com.apple.Safari --duration 5 --output output.wav
    python examples/macos_screencapture_test.py --pid 1234 --duration 5 --output output.wav
"""

import argparse
import sys
import wave
import logging
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from proctap import ProcessAudioCapture
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def get_pid_from_bundle_id(bundle_id: str) -> int:
    """
    Get first running PID for a given bundle identifier.

    Args:
        bundle_id: Application bundle identifier (e.g., com.apple.Safari)

    Returns:
        Process ID

    Raises:
        RuntimeError: If no running process found
    """
    import subprocess

    try:
        # Use pgrep to find process by name
        # Note: This is a heuristic, may need adjustment
        result = subprocess.run(
            ["pgrep", "-x", bundle_id.split(".")[-1]],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0 and result.stdout.strip():
            pid = int(result.stdout.strip().split("\n")[0])
            log.info(f"Found PID {pid} for bundle ID {bundle_id}")
            return pid

        # Try lsappinfo approach
        result = subprocess.run(
            ["lsappinfo", "list"],
            capture_output=True,
            text=True,
        )

        for line in result.stdout.split("\n"):
            if bundle_id in line:
                # Parse PID from line
                parts = line.split()
                if parts and parts[0].isdigit():
                    pid = int(parts[0])
                    log.info(f"Found PID {pid} for bundle ID {bundle_id} via lsappinfo")
                    return pid

        raise RuntimeError(f"No running process found for bundle ID: {bundle_id}")

    except Exception as e:
        raise RuntimeError(f"Failed to find PID for bundle ID {bundle_id}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Test ScreenCaptureKit audio capture on macOS"
    )
    parser.add_argument(
        "--pid",
        type=int,
        help="Process ID to capture audio from"
    )
    parser.add_argument(
        "--bundle-id",
        type=str,
        help="Application bundle identifier (e.g., com.apple.Safari)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=5,
        help="Duration to capture in seconds (default: 5)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="screencapture_test.wav",
        help="Output WAV file path (default: screencapture_test.wav)"
    )

    args = parser.parse_args()

    # Get PID
    if args.bundle_id:
        pid = get_pid_from_bundle_id(args.bundle_id)
    elif args.pid:
        pid = args.pid
    else:
        print("Error: Either --pid or --bundle-id must be specified", file=sys.stderr)
        sys.exit(1)

    # Standard format constants (matching backend)
    SAMPLE_RATE = 48000
    CHANNELS = 2

    log.info(f"Testing ScreenCaptureKit capture for PID {pid}")
    log.info(f"Output: {args.output}")
    log.info(f"Duration: {args.duration} seconds")
    log.info(f"Format: {SAMPLE_RATE}Hz, {CHANNELS}ch, float32 (converted to 16-bit for WAV)")

    # Create audio capture (no config needed - uses standard format)
    try:
        tap = ProcessAudioCapture(pid)
    except Exception as e:
        log.error(f"Failed to create capture: {e}")
        log.error("\nTroubleshooting:")
        log.error("1. Build Swift helper: cd src/proctap/swift/screencapture-audio && swift build")
        log.error("2. Enable Screen Recording permission:")
        log.error("   System Settings → Privacy & Security → Screen Recording → Enable for Terminal")
        log.error("3. Ensure target application is running and playing audio")
        sys.exit(1)

    # Prepare WAV file (16-bit PCM)
    wav_file = wave.open(args.output, "wb")
    wav_file.setnchannels(CHANNELS)
    wav_file.setsampwidth(2)  # 16-bit
    wav_file.setframerate(SAMPLE_RATE)

    frames_written = 0

    def on_audio_data(data: bytes, frame_count: int):
        """Convert float32 to int16 for WAV file."""
        nonlocal frames_written

        # Convert float32 PCM to int16 for WAV
        float_samples = np.frombuffer(data, dtype=np.float32)
        int16_samples = (np.clip(float_samples, -1.0, 1.0) * 32767).astype(np.int16)

        wav_file.writeframes(int16_samples.tobytes())
        frames_written += frame_count
        print(f"\rCaptured {frames_written} frames ({frames_written / SAMPLE_RATE:.2f}s)", end="", flush=True)

    try:
        # Set callback and start capture
        log.info("Starting audio capture...")
        tap.set_callback(on_audio_data)
        tap.start()

        # Record for specified duration
        import time
        time.sleep(args.duration)

        # Stop capture
        log.info("\nStopping audio capture...")
        tap.stop()

    except KeyboardInterrupt:
        log.info("\nInterrupted by user")
        tap.stop()
    except Exception as e:
        log.error(f"Error during capture: {e}")
        tap.stop()
        sys.exit(1)
    finally:
        wav_file.close()

    log.info(f"Capture complete! Wrote {frames_written} frames to {args.output}")
    log.info(f"File size: {Path(args.output).stat().st_size / 1024:.2f} KB")
    log.info(f"Duration: {frames_written / SAMPLE_RATE:.2f} seconds")


if __name__ == "__main__":
    main()
