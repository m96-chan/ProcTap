from proctap import ProcessAudioCapture
import wave
import argparse
import psutil
import sys
import struct


def find_pid_by_name(process_name: str) -> int:
    """プロセス名からPIDを検出する"""
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'].lower() == process_name.lower():
                return proc.info['pid']
            # .exeなしでも検索できるように
            if proc.info['name'].lower() == f"{process_name.lower()}.exe":
                return proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    raise ValueError(f"Process '{process_name}' not found")


def main():
    parser = argparse.ArgumentParser(
        description="Record audio from a specific process to WAV file"
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
        '--output',
        type=str,
        default="output.wav",
        help="Output WAV file path (default: output.wav)"
    )

    args = parser.parse_args()

    # PIDまたはプロセス名のどちらかが必要
    if args.pid is None and args.name is None:
        parser.error("Either --pid or --name must be specified")

    # プロセス名が指定された場合はPIDを検出
    if args.name:
        try:
            pid = find_pid_by_name(args.name)
            print(f"Found process '{args.name}' with PID: {pid}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        pid = args.pid
        print(f"Using PID: {pid}")

    # Audio format is now fixed at 48kHz, stereo, float32
    # We'll convert to 16-bit for WAV compatibility
    wav = wave.open(args.output, "wb")
    wav.setnchannels(2)  # stereo
    wav.setsampwidth(2)  # 16-bit PCM for WAV compatibility
    wav.setframerate(48000)  # 48kHz

    def on_data(pcm, frames):
        # Convert float32 PCM to int16 for WAV file
        # pcm contains float32 samples in range [-1.0, 1.0]
        import numpy as np
        
        # Convert bytes to float32 array
        float_samples = np.frombuffer(pcm, dtype=np.float32)
        
        # Convert to int16 (scale and clip)
        int16_samples = np.clip(float_samples * 32767, -32768, 32767).astype(np.int16)
        
        # Write to WAV file
        wav.writeframes(int16_samples.tobytes())

    print(f"Recording audio from PID {pid} to '{args.output}'")
    print(f"Format: {config.sample_rate}Hz, {config.channels}ch, 16-bit PCM")
    print("(WASAPI native 44.1kHz will be automatically converted to 48kHz)")
    print("Press Enter to stop recording...")

    try:
        with ProcessAudioCapture(pid, config=config, on_data=on_data):
            input()
    except KeyboardInterrupt:
        print("\nRecording stopped by user")
    finally:
        wav.close()
        print(f"Recording saved to '{args.output}'")


if __name__ == "__main__":
    main()