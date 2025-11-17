#!/usr/bin/env python3
"""
Real-time audio transcription using faster-whisper.

This contrib module provides real-time transcription of process audio using
faster-whisper, with support for both GPU (CUDA) and CPU execution.

Requirements:
- faster-whisper: pip install faster-whisper
- psutil (optional): pip install psutil (for process name lookup)
- CUDA (optional): For GPU acceleration

Usage as CLI:
    # Using PID with GPU (CUDA) and VAD enabled (default)
    python -m proctap.contrib.whisper_transcribe --pid 12345

    # Using process name with CPU
    python -m proctap.contrib.whisper_transcribe --name "Discord" --cpu

    # Custom model and language
    python -m proctap.contrib.whisper_transcribe --pid 12345 --model large-v3 --language ja

    # Disable VAD to transcribe all chunks
    python -m proctap.contrib.whisper_transcribe --pid 12345 --no-vad

    # Adjust VAD sensitivity (lower = more sensitive)
    python -m proctap.contrib.whisper_transcribe --pid 12345 --vad-threshold -50.0

Usage as library:
    ```python
    from proctap.contrib.whisper_transcribe import RealtimeTranscriber

    # Create transcriber with VAD enabled (default)
    transcriber = RealtimeTranscriber(
        pid=12345,
        model_size="base",
        device="cuda",
        language="en",
        use_vad=True,
        vad_threshold_db=-45.0
    )

    # Start transcription
    transcriber.start()

    # ... transcription runs in background ...

    # Stop when done
    transcriber.stop()
    ```

    VAD (Voice Activity Detection) is enabled by default and helps skip
    silent chunks, reducing unnecessary transcription and improving performance.
"""

from __future__ import annotations

import argparse
import io
import sys
import threading
import wave
from collections import deque
from pathlib import Path
from typing import Optional

# Note: pkg_resources deprecation warning from ctranslate2
# This is a known upstream issue in ctranslate2 4.6.1 that will be fixed in a future release.
# See: https://github.com/SYSTRAN/faster-whisper/issues/1360
# The warning does not affect functionality and can be safely ignored for now.

try:
    from proctap import ProcessAudioCapture, StreamConfig
    from proctap.contrib.filters import EnergyVAD
except ImportError:
    print("Error: proctap is not installed. Install it with: pip install proc-tap")
    sys.exit(1)

try:
    from faster_whisper import WhisperModel
except ImportError:
    # Allow module to be imported without faster-whisper for testing purposes
    # Runtime error will be raised when RealtimeTranscriber is instantiated
    WhisperModel = None  # type: ignore

try:
    import numpy as np
except ImportError:
    print("Error: numpy is not installed.")
    print("Install with: pip install numpy")
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
        for proc_pid, name in matching_pids:
            print(f"  PID {proc_pid}: {name}")
        print(f"\nUsing first match: PID {matching_pids[0][0]}")

    result_pid: int = matching_pids[0][0]
    return result_pid


class RealtimeTranscriber:
    """
    Real-time audio transcriber using faster-whisper.

    Captures audio from a process and transcribes it in chunks using
    faster-whisper with configurable model and device.
    """

    def __init__(
        self,
        pid: int,
        model_size: str = "base",
        device: str = "cuda",
        compute_type: str = "float16",
        language: Optional[str] = None,
        chunk_duration: float = 3.0,
        use_vad: bool = True,
        vad_threshold_db: float = -45.0,
    ):
        """
        Initialize the real-time transcriber.

        Args:
            pid: Process ID to capture audio from
            model_size: Whisper model size (tiny, base, small, medium, large-v2, large-v3)
            device: Device to use (cuda, cpu)
            compute_type: Compute type (float16, int8, int8_float16 for GPU; int8, float32 for CPU)
            language: Language code (None for auto-detection, e.g., "en", "ja", "zh")
            chunk_duration: Duration of audio chunks to transcribe in seconds
            use_vad: Enable Voice Activity Detection to skip silence (default: True)
            vad_threshold_db: VAD energy threshold in dB (default: -45.0)
        """
        self.pid = pid
        self.chunk_duration = chunk_duration
        self.language = language
        self.use_vad = use_vad

        # Audio format: 16kHz mono (Whisper's native format)
        self.config = StreamConfig(
            sample_rate=16000,  # Whisper expects 16kHz
            channels=1,  # Mono
        )

        # Audio buffer
        self.audio_buffer = bytearray()
        self.buffer_lock = threading.Lock()
        self.chunk_size_bytes = int(self.config.sample_rate * 2 * chunk_duration)  # 2 bytes per sample

        # ProcessAudioCapture instance
        self.tap: Optional[ProcessAudioCapture] = None
        self.running = False

        # Initialize VAD filter
        self.vad: Optional[EnergyVAD]
        if self.use_vad:
            self.vad = EnergyVAD(
                threshold_db=vad_threshold_db,
                hangover_frames=3,  # Keep speech flag for 3 frames after silence
            )
            print(f"VAD enabled (threshold: {vad_threshold_db} dB)")
        else:
            self.vad = None

        # Statistics
        self.total_chunks = 0
        self.speech_chunks = 0
        self.skipped_chunks = 0

        # Initialize Whisper model
        if WhisperModel is None:
            raise ImportError(
                "faster-whisper is not installed. "
                "Install it with: pip install faster-whisper"
            )

        print(f"Loading Whisper model '{model_size}' on {device}...")
        try:
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
            print(f"Model loaded successfully")
        except Exception as e:
            print(f"Error loading model: {e}")
            if device == "cuda":
                print("\nTip: If CUDA is not available, try using --cpu flag")
            raise

    def on_audio_data(self, pcm_data: bytes, frames: int) -> None:
        """
        Callback function to receive audio data from ProcessAudioCapture.

        Args:
            pcm_data: Raw PCM audio data
            frames: Number of audio frames (not used)
        """
        with self.buffer_lock:
            self.audio_buffer.extend(pcm_data)

    def transcribe_chunk(self, audio_data: bytes) -> str:
        """
        Transcribe an audio chunk using faster-whisper.

        Args:
            audio_data: Raw PCM audio data (16kHz, mono, 16-bit)

        Returns:
            Transcribed text
        """
        # Convert bytes to WAV format for faster-whisper
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(16000)
            wav_file.writeframes(audio_data)

        wav_buffer.seek(0)

        # Transcribe using faster-whisper
        segments, info = self.model.transcribe(
            wav_buffer,
            language=self.language,
            vad_filter=True,  # Enable VAD to filter silence
            beam_size=5,
        )

        # Collect transcribed text
        transcription = ""
        for segment in segments:
            transcription += segment.text

        return transcription.strip()

    def process_audio_loop(self) -> None:
        """
        Background loop to process accumulated audio chunks.
        """
        print(f"\n{'=' * 60}")
        print("Real-time Transcription Started")
        print(f"{'=' * 60}")
        print(f"Language: {self.language or 'auto-detect'}")
        print(f"Chunk duration: {self.chunk_duration}s")
        print(f"VAD: {'enabled' if self.use_vad else 'disabled'}")
        print(f"{'=' * 60}\n")

        while self.running:
            # Check if we have enough audio data
            with self.buffer_lock:
                if len(self.audio_buffer) >= self.chunk_size_bytes:
                    # Extract chunk
                    chunk = bytes(self.audio_buffer[:self.chunk_size_bytes])
                    del self.audio_buffer[:self.chunk_size_bytes]
                else:
                    chunk = None

            # Transcribe chunk if available
            if chunk:
                self.total_chunks += 1

                # Check for speech activity with VAD
                should_transcribe = True
                if self.use_vad and self.vad is not None:
                    # Convert bytes to float32 for VAD
                    audio_array = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0

                    # Apply VAD
                    self.vad.process(audio_array)

                    if not self.vad.is_speech:
                        should_transcribe = False
                        self.skipped_chunks += 1

                # Transcribe only if speech detected (or VAD disabled)
                if should_transcribe:
                    self.speech_chunks += 1
                    try:
                        text = self.transcribe_chunk(chunk)
                        if text:
                            print(f"> {text}")
                    except Exception as e:
                        print(f"Error during transcription: {e}", file=sys.stderr)

    def start(self) -> None:
        """Start audio capture and transcription."""
        if self.running:
            print("Transcriber already running")
            return

        print(f"\nStarting audio capture from PID {self.pid}...")

        # Create and start ProcessAudioCapture
        self.tap = ProcessAudioCapture(
            pid=self.pid,
            config=self.config,
            on_data=self.on_audio_data
        )
        self.tap.start()

        # Start processing loop
        self.running = True
        self.process_thread = threading.Thread(
            target=self.process_audio_loop,
            daemon=True,
            name="TranscriptionProcessor"
        )
        self.process_thread.start()

        print("Audio capture started")
        print("\nListening for audio... (Press Ctrl+C to stop)\n")

    def stop(self) -> None:
        """Stop audio capture and transcription."""
        if not self.running:
            return

        print("\n\nStopping transcription...")
        self.running = False

        if self.process_thread and self.process_thread.is_alive():
            self.process_thread.join(timeout=2.0)

        if self.tap:
            self.tap.stop()
            self.tap.close()

        # Display statistics
        print("\n" + "=" * 60)
        print("Transcription Statistics")
        print("=" * 60)
        print(f"Total chunks processed:   {self.total_chunks}")
        print(f"Speech chunks transcribed: {self.speech_chunks}")
        if self.use_vad:
            print(f"Silence chunks skipped:    {self.skipped_chunks}")
            if self.total_chunks > 0:
                skip_rate = (self.skipped_chunks / self.total_chunks) * 100
                print(f"Skip rate:                 {skip_rate:.1f}%")
        print("=" * 60)
        print("Transcription stopped")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Real-time audio transcription using faster-whisper"
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

    # Whisper configuration
    parser.add_argument(
        '--model', '-m',
        type=str,
        default='base',
        choices=['tiny', 'base', 'small', 'medium', 'large-v2', 'large-v3'],
        help='Whisper model size (default: base)'
    )
    parser.add_argument(
        '--language', '-l',
        type=str,
        default=None,
        help='Language code (e.g., "en", "ja", "zh"). Auto-detect if not specified.'
    )
    parser.add_argument(
        '--cpu',
        action='store_true',
        help='Use CPU instead of GPU (CUDA)'
    )
    parser.add_argument(
        '--chunk-duration',
        type=float,
        default=3.0,
        help='Duration of audio chunks to transcribe in seconds (default: 3.0)'
    )
    parser.add_argument(
        '--no-vad',
        action='store_true',
        help='Disable Voice Activity Detection (transcribe all chunks including silence)'
    )
    parser.add_argument(
        '--vad-threshold',
        type=float,
        default=-45.0,
        help='VAD energy threshold in dB (default: -45.0, lower = more sensitive)'
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

    # Determine device and compute type
    if args.cpu:
        device = "cpu"
        compute_type = "int8"
    else:
        device = "cuda"
        compute_type = "float16"

    try:
        # Create transcriber
        transcriber = RealtimeTranscriber(
            pid=pid,
            model_size=args.model,
            device=device,
            compute_type=compute_type,
            language=args.language,
            chunk_duration=args.chunk_duration,
            use_vad=not args.no_vad,
            vad_threshold_db=args.vad_threshold,
        )

        # Start transcription
        transcriber.start()

        # Wait for user interrupt
        try:
            while True:
                import time
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass

        # Stop transcription
        transcriber.stop()

        return 0

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def _cli_entry_point() -> int:
    """Entry point for CLI execution to avoid sys.modules RuntimeWarning."""
    return main()


if __name__ == '__main__':
    sys.exit(_cli_entry_point())
