#!/usr/bin/env python3
"""
Linux PulseAudio capture example.

This example demonstrates how to capture audio from a specific process on Linux
using ProcTap with PulseAudio backend.

Requirements:
- Linux with PulseAudio or PipeWire (with pulseaudio-compat)
- pulsectl library: pip install pulsectl
- parec command: sudo apt-get install pulseaudio-utils

Usage:
    python linux_pulse_basic.py --pid 12345 --duration 5 --output output.wav
    python linux_pulse_basic.py --name firefox --duration 10 --output firefox.wav

Note:
    The target process must be actively playing audio when you run this script.
"""

from __future__ import annotations

import argparse
import sys
import wave
import time
from pathlib import Path

try:
    from proctap import ProcessAudioCapture
except ImportError:
    print("Error: proctap is not installed. Install it with: pip install proc-tap")
    sys.exit(1)


def find_pid_by_name(process_name: str) -> int:
    """
    Find PID by process name.

    Args:
        process_name: Process name to search for

    Returns:
        Process ID

    Raises:
        RuntimeError: If process not found or psutil not available
    """
    try:
        import psutil
    except ImportError:
        raise RuntimeError(
            "psutil is required to find process by name. "
            "Install it with: pip install psutil"
        )

    # Find processes with matching name
    matching_pids = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if process_name.lower() in proc.info['name'].lower():
                matching_pids.append((proc.info['pid'], proc.info['name']))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not matching_pids:
        raise RuntimeError(f"No process found with name containing '{process_name}'")

    if len(matching_pids) > 1:
        print(f"Found {len(matching_pids)} matching processes:")
        for pid, name in matching_pids:
            print(f"  PID {pid}: {name}")
        print(f"\nUsing first match: PID {matching_pids[0][0]}")

    return matching_pids[0][0]


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Capture audio from a specific process on Linux using PulseAudio"
    )

    # Process selection (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--pid',
        type=int,
        help='Process ID to capture audio from'
    )
    group.add_argument(
        '--name',
        type=str,
        help='Process name to search for (requires psutil)'
    )

    # Output options
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='output.wav',
        help='Output WAV file path (default: output.wav)'
    )
    parser.add_argument(
        '--duration', '-d',
        type=float,
        default=5.0,
        help='Recording duration in seconds (default: 5.0)'
    )

    # Audio format options
    parser.add_argument(
        '--sample-rate', '-r',
        type=int,
        default=44100,
        help='Sample rate in Hz (default: 44100)'
    )
    parser.add_argument(
        '--channels', '-c',
        type=int,
        default=2,
        choices=[1, 2],
        help='Number of channels: 1 (mono) or 2 (stereo) (default: 2)'
    )

    args = parser.parse_args()

    # Determine PID
    try:
        if args.name:
            print(f"Searching for process: {args.name}")
            pid = find_pid_by_name(args.name)
            print(f"Found PID: {pid}")
        else:
            pid = args.pid
            print(f"Using PID: {pid}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepare WAV file (fixed to 48kHz, stereo, 16-bit)
    wav_file = wave.open(str(output_path), 'wb')
    wav_file.setnchannels(2)  # stereo
    wav_file.setsampwidth(2)  # 16-bit PCM
    wav_file.setframerate(48000)  # 48kHz

    frame_count = 0

    def on_audio_data(pcm_data: bytes, frames: int) -> None:
        """Callback function to convert float32 to int16 and write to WAV file."""
        nonlocal frame_count
        
        # Convert float32 PCM to int16 for WAV compatibility
        import numpy as np
        
        # Convert bytes to float32 array
        float_samples = np.frombuffer(pcm_data, dtype=np.float32)
        
        # Convert to int16 (scale and clip)
        int16_samples = np.clip(float_samples * 32767, -32768, 32767).astype(np.int16)
        
        # Write to WAV file
        wav_file.writeframes(int16_samples.tobytes())
        frame_count += len(int16_samples) // 2  # 2 channels

    try:
        print("\n" + "=" * 60)
        print("Linux PulseAudio Audio Capture")
        print("=" * 60)
        print(f"Target PID:     {pid}")
        print(f"Output file:    {output_path}")
        print(f"Duration:       {args.duration} seconds")
        print(f"Format:         48000Hz, 2ch, float32 -> 16-bit PCM (WAV)")
        print("=" * 60)

        # Create audio capture instance (now uses fixed format)
        print("\nInitializing ProcTap...")
        tap = ProcessAudioCapture(pid=pid, on_data=on_audio_data)

        print("Starting audio capture...")
        print("\n⚠️  IMPORTANT: Make sure the target process is actively playing audio!")
        print("⚠️  The capture may fail if the process is not producing audio.\n")

        tap.start()

        # Record for specified duration
        print(f"Recording for {args.duration} seconds...")
        time.sleep(args.duration)

        # Stop capture
        print("\nStopping capture...")
        tap.stop()
        tap.close()

        # Close WAV file
        wav_file.close()

        # Show results
        duration = frame_count / 48000  # Fixed sample rate
        file_size = output_path.stat().st_size

        print("\n" + "=" * 60)
        print("Capture Complete!")
        print("=" * 60)
        print(f"Frames captured:  {frame_count:,}")
        print(f"Duration:         {duration:.2f} seconds")
        print(f"File size:        {file_size:,} bytes ({file_size / 1024:.1f} KB)")
        print(f"Output file:      {output_path.absolute()}")
        print("=" * 60)

        if frame_count == 0:
            print("\n⚠️  WARNING: No audio data was captured!")
            print("   Possible reasons:")
            print("   - The process is not currently playing audio")
            print("   - The process does not have PulseAudio streams")
            print("   - Permission issues")
            print("\n   Try:")
            print("   1. Make sure the process is actively playing audio")
            print("   2. Check 'pactl list sink-inputs' to see active streams")
            return 1

        return 0

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        wav_file.close()
        return 130

    except Exception as e:
        print(f"\nError during capture: {e}", file=sys.stderr)
        wav_file.close()
        return 1


if __name__ == '__main__':
    sys.exit(main())
