"""
CLI entry point for proctap.

Usage:
    python -m proctap --pid 12345 --stdout | ffmpeg -f f32le -ar 48000 -ac 2 -i pipe:0 output.mp3
    python -m proctap --name "VRChat.exe" --stdout | ffmpeg -f f32le -ar 48000 -ac 2 -i pipe:0 output.mp3
"""

from __future__ import annotations

import argparse
import sys
import signal
import logging
import platform
import struct
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

from .core import ProcessAudioCapture
from .format import FIXED_AUDIO_FORMAT

logger = logging.getLogger(__name__)


def find_pid_by_name(process_name: str) -> int:
    """Find PID by process name."""
    if psutil is None:
        raise RuntimeError(
            "psutil is required for --name option. Install with: pip install psutil"
        )

    for proc in psutil.process_iter(['pid', 'name']):
        try:
            proc_name = proc.info.get('name')
            proc_pid = proc.info.get('pid')

            if proc_name is None or proc_pid is None:
                continue

            if proc_name.lower() == process_name.lower():
                return int(proc_pid)
            # Also match without .exe extension
            if proc_name.lower() == f"{process_name.lower()}.exe":
                return int(proc_pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    raise ValueError(f"Process '{process_name}' not found")


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="proctap",
        description="Capture audio from a specific process",
        epilog="""
Examples:
  # Pipe to ffmpeg (MP3) - Direct command
  proctap --pid 12345 --stdout | ffmpeg -f f32le -ar 48000 -ac 2 -i pipe:0 output.mp3

  # Pipe to ffmpeg (FLAC)
  proctap --name "VRChat.exe" --stdout | ffmpeg -f f32le -ar 48000 -ac 2 -i pipe:0 output.flac

  # Or using python -m (alternative)
  python -m proctap --pid 12345 --stdout | ffmpeg -f f32le -ar 48000 -ac 2 -i pipe:0 output.mp3
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '--pid',
        type=int,
        help="Process ID to capture audio from"
    )
    parser.add_argument(
        '--name',
        type=str,
        help="Process name to capture audio from (e.g., 'VRChat.exe' or 'VRChat')"
    )
    parser.add_argument(
        '--stdout',
        action='store_true',
        help="Output raw PCM to stdout (for piping to ffmpeg)"
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help="Enable verbose logging (to stderr)"
    )
    parser.add_argument(
        '--duration',
        type=float,
        help="Capture duration in seconds (optional, runs indefinitely if not specified)"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='[%(levelname)s] %(message)s',
        stream=sys.stderr  # Always log to stderr to avoid contaminating stdout
    )

    # Validate arguments
    if args.pid is None and args.name is None:
        parser.error("Either --pid or --name must be specified")

    if not args.stdout:
        parser.error("--stdout is currently required (other output modes not yet implemented)")

    # Resolve PID
    pid: int
    if args.name:
        try:
            pid = find_pid_by_name(args.name)
            logger.info(f"Found process '{args.name}' with PID: {pid}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        pid = args.pid
        logger.info(f"Using PID: {pid}")

    logger.info(f"Audio format: {FIXED_AUDIO_FORMAT.sample_rate}Hz, {FIXED_AUDIO_FORMAT.channels}ch, float32")
    logger.info(f"FFmpeg format args: -f f32le -ar {FIXED_AUDIO_FORMAT.sample_rate} -ac {FIXED_AUDIO_FORMAT.channels}")

    # Setup signal handling for graceful shutdown
    stop_requested = False

    def signal_handler(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        logger.info("Shutdown signal received")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Callback to write PCM to stdout
    bytes_written = 0
    def on_data(pcm: bytes, frames: int) -> None:
        nonlocal bytes_written
        try:
            sys.stdout.buffer.write(pcm)
            sys.stdout.buffer.flush()
            bytes_written += len(pcm)
            logger.debug(f"Wrote {len(pcm)} bytes to stdout (total: {bytes_written})")
        except BrokenPipeError:
            # Pipe closed (e.g., ffmpeg finished)
            logger.warning(f"BrokenPipeError: Pipe closed after writing {bytes_written} bytes")
            nonlocal stop_requested
            stop_requested = True
        except Exception as e:
            logger.error(f"Error writing to stdout: {e}")

    # Start capture
    try:
        logger.info("Starting audio capture...")
        tap = ProcessAudioCapture(pid, on_data=on_data)
        tap.start()

        if args.duration:
            logger.info(f"Capture started. Will stop after {args.duration} seconds.")
        else:
            logger.info("Capture started. Press Ctrl+C to stop.")

        # Keep running until signal received, pipe broken, or duration expires
        import time
        start_time = time.time()
        while not stop_requested:
            try:
                # Check duration limit if specified
                if args.duration and (time.time() - start_time) >= args.duration:
                    logger.info(f"Duration limit ({args.duration}s) reached, stopping...")
                    break

                # Sleep in small increments to respond quickly to signals
                time.sleep(0.1)
            except KeyboardInterrupt:
                break

        logger.info("Stopping capture...")
        tap.stop()
        logger.info("Capture stopped")
        return 0

    except Exception as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
