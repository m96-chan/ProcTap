"""
CLI entry point for proctap.

All audio is captured in standard format (48kHz/2ch/float32) and can be
converted to other formats for output.

Usage:
    proctap --pid 12345 --stdout | ffmpeg -f f32le -ar 48000 -ac 2 -i pipe:0 output.mp3
    proctap --name "VRChat.exe" --format int16 --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 output.mp3
"""

from __future__ import annotations

import argparse
import sys
import signal
import logging
import time
import traceback
import numpy as np
from typing import Optional

try:
    import psutil  # type: ignore[import-untyped]
except ImportError:
    psutil = None  # type: ignore[assignment]

from .core import ProcessAudioCapture
from .backends.base import STANDARD_SAMPLE_RATE, STANDARD_CHANNELS
from ._version import __version__

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


def list_audio_processes() -> None:
    """
    List all processes currently playing audio.

    On Windows: Uses Windows Audio Session API to detect active audio sessions
    On other platforms: Shows common audio-related processes (fallback)
    """
    import platform

    if psutil is None:
        print("Error: psutil is required. Install with: pip install psutil", file=sys.stderr)
        sys.exit(1)

    if platform.system() == "Windows":
        try:
            # Try to use our native extension to detect active processes
            from .backends.windows import WindowsBackend
            from .backends.base import AudioBackend
            import subprocess

            # Use PowerShell to query active audio sessions
            ps_script = """
            Add-Type -TypeDefinition @"
            using System;
            using System.Runtime.InteropServices;
            public class AudioSession {
                [DllImport("kernel32.dll", SetLastError=true)]
                public static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, uint dwProcessId);
                [DllImport("kernel32.dll", SetLastError=true)]
                public static extern bool CloseHandle(IntPtr hObject);
            }
"@

            # Get audio session processes using WMI
            $audioProcesses = Get-Process | Where-Object {
                $_.MainWindowHandle -ne 0 -and $_.ProcessName -match 'audio|media|music|video|player|chrome|firefox|edge|spotify|discord|teams|zoom|vlc|winamp|foobar|aimp'
            } | Select-Object Id, Name, @{Name="Status";Expression={$_.Responding}}

            if ($audioProcesses) {
                $audioProcesses | Format-Table -AutoSize
            } else {
                Write-Host "No audio processes detected"
            }
            """

            # Simpler approach: Just list processes with open audio devices
            # This works by checking for processes that are likely playing audio

            active_procs = []

            # Common audio-related process keywords
            audio_keywords = [
                'chrome', 'firefox', 'edge', 'msedge', 'opera', 'brave',
                'spotify', 'discord', 'teams', 'zoom', 'slack',
                'vlc', 'mpc', 'media', 'player', 'winamp', 'foobar', 'aimp',
                'obs', 'streamlabs', 'xsplit',
                'game', 'unity', 'unreal',
                'audiodg', 'wmplayer', 'groove'
            ]

            print(f"{'PID':<10} {'Process Name':<35} {'CPU %':<10} {'Memory (MB)'}")
            print("-" * 75)

            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    pid = proc.info['pid']
                    name = proc.info['name']

                    # Filter for audio-related processes
                    if any(keyword in name.lower() for keyword in audio_keywords):
                        cpu = proc.cpu_percent(interval=0.1)
                        mem_mb = proc.info['memory_info'].rss / (1024 * 1024)

                        # Only show if using CPU (likely active)
                        if cpu > 0.1:
                            active_procs.append((pid, name, cpu, mem_mb))

                except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, KeyError):
                    pass

            # Sort by CPU usage (descending)
            active_procs.sort(key=lambda x: x[2], reverse=True)

            for pid, name, cpu, mem_mb in active_procs:
                print(f"{pid:<10} {name:<35} {cpu:<10.1f} {mem_mb:<.1f}")

            if not active_procs:
                print("\nNo active audio processes detected")
                print("Tip: This shows processes that might be playing audio based on process names.")
            else:
                print(f"\nFound {len(active_procs)} potentially active audio process(es)")
                print("Note: This is a heuristic detection. Use --pid or --name to specify the target process.")

        except Exception as e:
            print(f"Error detecting audio processes: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    else:
        # Non-Windows platforms
        print(f"Audio process detection is best-effort on {platform.system()}")
        print(f"\n{'PID':<10} {'Process Name':<35}")
        print("-" * 50)

        audio_keywords = ['chrome', 'firefox', 'spotify', 'vlc', 'mpv', 'rhythmbox', 'audacious']

        for proc in psutil.process_iter(['pid', 'name']):
            try:
                pid = proc.info['pid']
                name = proc.info['name']

                if any(keyword in name.lower() for keyword in audio_keywords):
                    print(f"{pid:<10} {name:<35}")
            except (TypeError, KeyError):
                pass


def convert_float32_to_int16(audio_float32: bytes) -> bytes:
    """Convert float32 PCM to int16 PCM."""
    audio_array = np.frombuffer(audio_float32, dtype=np.float32)
    # Clip to [-1.0, 1.0] and convert to int16
    audio_int16 = (np.clip(audio_array, -1.0, 1.0) * 32767).astype(np.int16)
    return audio_int16.tobytes()


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="proctap",
        description="Capture audio from a specific process (always captures at 48kHz/2ch)",
        epilog="""
Examples:
  # List processes currently playing audio
  proctap --list-audio-procs

  # Output float32 (native format, no conversion)
  proctap --pid 12345 --format float32 --stdout | ffmpeg -f f32le -ar 48000 -ac 2 -i pipe:0 output.mp3

  # Output int16 (converted for compatibility)
  proctap --name "VRChat.exe" --format int16 --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 output.flac

  # Default is int16 for backwards compatibility
  proctap --pid 12345 --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 output.mp3
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
        '--format',
        type=str,
        default='int16',
        choices=['int16', 'float32'],
        help="Output format: int16 (s16le) or float32 (f32le) (default: int16)"
    )
    parser.add_argument(
        '--resample-quality',
        type=str,
        default='best',
        choices=['best', 'medium', 'fast'],
        help="Resampling quality when format conversion is needed (default: best)\n"
             "  best: Highest quality, ~1.3-1.4ms latency\n"
             "  medium: Medium quality, ~0.7-0.9ms latency\n"
             "  fast: Lowest quality, ~0.3-0.5ms latency"
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help="Enable verbose logging (to stderr)"
    )
    parser.add_argument(
        '--list-audio-procs',
        action='store_true',
        help="List all processes currently playing audio and exit"
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}'
    )

    args = parser.parse_args()

    # Handle --list-audio-procs first (no other options required)
    if args.list_audio_procs:
        try:
            list_audio_processes()
            return 0
        except Exception as e:
            print(f"Error listing audio processes: {e}", file=sys.stderr)
            return 1

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

    # Determine FFmpeg format string
    ffmpeg_format = 'f32le' if args.format == 'float32' else 's16le'
    logger.info(f"Capture format: {STANDARD_SAMPLE_RATE}Hz, {STANDARD_CHANNELS}ch, float32 (internal)")
    logger.info(f"Output format: {STANDARD_SAMPLE_RATE}Hz, {STANDARD_CHANNELS}ch, {args.format}")
    logger.info(f"FFmpeg format args: -f {ffmpeg_format} -ar {STANDARD_SAMPLE_RATE} -ac {STANDARD_CHANNELS}")

    # Setup signal handling for graceful shutdown
    stop_requested = False

    def signal_handler(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True
        logger.info("Shutdown signal received")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Callback to write PCM to stdout
    def on_data(pcm: bytes, _frames: int) -> None:
        nonlocal stop_requested
        try:
            # Convert format if needed
            if args.format == 'int16':
                pcm = convert_float32_to_int16(pcm)
            # else: keep as float32

            sys.stdout.buffer.write(pcm)
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            # Pipe closed (e.g., ffmpeg finished)
            stop_requested = True
        except Exception as e:
            logger.error(f"Error writing to stdout: {e}")
            stop_requested = True

    # Start capture
    try:
        logger.info("Starting audio capture...")
        tap = ProcessAudioCapture(pid, on_data=on_data, resample_quality=args.resample_quality)  # type: ignore[arg-type]
        tap.start()

        logger.info("Capture started. Press Ctrl+C to stop.")

        # Keep running until signal received or pipe broken
        while not stop_requested:
            try:
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
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
