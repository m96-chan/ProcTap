#!/usr/bin/env python3
"""
macOS Core Audio Process Tap advanced capture example.

⚠️  WARNING: This example uses ARCHIVED experimental backend (archive/experimental-backends/macos.py)
This backend is not used in production and has AMFI limitations on Apple Silicon.

For production use, see examples/macos_basic.py which uses the recommended ScreenCaptureKit backend.

This example demonstrates advanced features of the experimental macOS backend:
- Capturing from multiple processes (include_pids)
- Excluding specific processes (exclude_pids)
- Capturing all processes except certain ones

Requirements:
- macOS 14.4 (Sonoma) or later
- Swift CLI helper binary (proctap-macos)
- Audio capture permission
- AMFI disabled on Apple Silicon

Usage Examples:
    # Capture from multiple specific processes
    python macos_advanced.py --include-pids 1234,5678 --duration 5 --output multi.wav

    # Capture all except music player
    python macos_advanced.py --exclude-pids 9999 --duration 10 --output no_music.wav

    # Capture game + voice chat, exclude music
    python macos_advanced.py --include-names "game,discord" --exclude-names "Music" --duration 10

Note:
    The target processes must be actively playing audio when you run this script.
    On first run, macOS will prompt for audio capture permission.
"""

from __future__ import annotations

import argparse
import sys
import wave
import time
from pathlib import Path

try:
    # Import from archived experimental backend
    sys.path.insert(0, str(Path(__file__).parent.parent / "archive" / "experimental-backends"))
    from macos import MacOSBackend  # type: ignore[import-not-found]
except ImportError as e:
    print("Error: Could not import archived experimental backend")
    print(f"Details: {e}")
    print("\nThis example uses the archived experimental backend which is not installed by default.")
    print("For production use, see examples/macos_basic.py with ScreenCaptureKit backend.")
    sys.exit(1)


def find_pids_by_names(names: list[str]) -> list[int]:
    """
    Find PIDs by process names.

    Args:
        names: List of process names to search for

    Returns:
        List of PIDs

    Raises:
        RuntimeError: If psutil not available
    """
    try:
        import psutil
    except ImportError:
        raise RuntimeError(
            "psutil is required to find process by name. "
            "Install it with: pip install psutil"
        )

    pids = []
    for name in names:
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if name.lower() in proc.info['name'].lower():
                    pids.append(proc.info['pid'])
                    print(f"  Found {proc.info['name']} (PID {proc.info['pid']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    return pids


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Advanced macOS Core Audio Process Tap capture with include/exclude"
    )

    # Process selection
    parser.add_argument(
        '--include-pids',
        type=str,
        help='Comma-separated list of PIDs to include (e.g., "1234,5678")'
    )
    parser.add_argument(
        '--exclude-pids',
        type=str,
        help='Comma-separated list of PIDs to exclude (e.g., "9999,8888")'
    )
    parser.add_argument(
        '--include-names',
        type=str,
        help='Comma-separated list of process names to include (requires psutil)'
    )
    parser.add_argument(
        '--exclude-names',
        type=str,
        help='Comma-separated list of process names to exclude (requires psutil)'
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
        default=48000,
        help='Sample rate in Hz (default: 48000)'
    )
    parser.add_argument(
        '--channels', '-c',
        type=int,
        default=2,
        choices=[1, 2],
        help='Number of channels: 1 (mono) or 2 (stereo) (default: 2)'
    )

    args = parser.parse_args()

    # Parse PIDs
    include_pids: list[int] = []
    exclude_pids: list[int] = []

    try:
        # Parse include PIDs
        if args.include_pids:
            include_pids = [int(p.strip()) for p in args.include_pids.split(',')]
        elif args.include_names:
            print(f"Searching for processes to include: {args.include_names}")
            names = [n.strip() for n in args.include_names.split(',')]
            include_pids = find_pids_by_names(names)
            if not include_pids:
                print("Error: No matching processes found to include", file=sys.stderr)
                return 1

        # Parse exclude PIDs
        if args.exclude_pids:
            exclude_pids = [int(p.strip()) for p in args.exclude_pids.split(',')]
        elif args.exclude_names:
            print(f"Searching for processes to exclude: {args.exclude_names}")
            names = [n.strip() for n in args.exclude_names.split(',')]
            exclude_pids = find_pids_by_names(names)

    except ValueError as e:
        print(f"Error parsing PIDs: {e}", file=sys.stderr)
        return 1

    # Validate configuration
    if not include_pids and not exclude_pids:
        print("Error: Must specify at least one of --include-pids, --exclude-pids, "
              "--include-names, or --exclude-names", file=sys.stderr)
        return 1

    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepare WAV file
    wav_file = wave.open(str(output_path), 'wb')
    wav_file.setnchannels(args.channels)
    wav_file.setsampwidth(2)  # 16-bit PCM
    wav_file.setframerate(args.sample_rate)

    chunk_count = 0
    total_bytes = 0

    try:
        print("\n" + "=" * 60)
        print("macOS Core Audio Process Tap - Advanced Capture")
        print("=" * 60)

        if include_pids:
            print(f"Include PIDs:   {include_pids}")
        else:
            print("Include PIDs:   All processes")

        if exclude_pids:
            print(f"Exclude PIDs:   {exclude_pids}")

        print(f"Output file:    {output_path}")
        print(f"Duration:       {args.duration} seconds")
        print(f"Sample rate:    {args.sample_rate} Hz")
        print(f"Channels:       {args.channels}")
        print("=" * 60)

        # Create macOS backend with include/exclude
        print("\nInitializing macOS backend...")
        backend = MacOSBackend(
            pid=0,  # Not used when include_pids is specified
            sample_rate=args.sample_rate,
            channels=args.channels,
            sample_width=2,  # 16-bit
            include_pids=include_pids if include_pids else None,
            exclude_pids=exclude_pids if exclude_pids else None,
        )

        print("Starting audio capture...")
        print("\n⚠️  IMPORTANT: Make sure the target processes are actively playing audio!")
        print("⚠️  On first run, macOS will prompt for audio capture permission.\n")

        backend.start()

        # Record for specified duration
        print(f"Recording for {args.duration} seconds...")
        start_time = time.time()

        while time.time() - start_time < args.duration:
            chunk = backend.read()
            if chunk:
                wav_file.writeframes(chunk)
                chunk_count += 1
                total_bytes += len(chunk)

                # Progress indicator every 100 chunks
                if chunk_count % 100 == 0:
                    elapsed = time.time() - start_time
                    print(f"  [{elapsed:.1f}s] {chunk_count} chunks, {total_bytes:,} bytes", end='\r')

            time.sleep(0.01)  # Small sleep to prevent busy loop

        print()  # New line after progress

        # Stop capture
        print("\nStopping capture...")
        backend.stop()
        backend.close()

        # Close WAV file
        wav_file.close()

        # Show results
        frames = total_bytes // (args.channels * 2)
        duration = frames / args.sample_rate
        file_size = output_path.stat().st_size

        print("\n" + "=" * 60)
        print("Capture Complete!")
        print("=" * 60)
        print(f"Chunks captured:  {chunk_count:,}")
        print(f"Frames captured:  {frames:,}")
        print(f"Duration:         {duration:.2f} seconds")
        print(f"File size:        {file_size:,} bytes ({file_size / 1024:.1f} KB)")
        print(f"Output file:      {output_path.absolute()}")
        print("=" * 60)

        if total_bytes == 0:
            print("\n⚠️  WARNING: No audio data was captured!")
            print("   Possible reasons:")
            print("   - The processes are not currently playing audio")
            print("   - Audio capture permission was denied")
            print("   - macOS version is older than 14.4")
            print("   - Swift CLI helper (proctap-macos) is not installed")
            print("\n   Try:")
            print("   1. Make sure the processes are actively playing audio")
            print("   2. Grant audio capture permission in System Settings")
            print("   3. Verify macOS version: System Settings > General > About")
            return 1

        return 0

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        backend.stop()
        wav_file.close()
        return 130

    except Exception as e:
        print(f"\nError during capture: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        try:
            backend.stop()
        except:
            pass
        wav_file.close()
        return 1


if __name__ == '__main__':
    sys.exit(main())
