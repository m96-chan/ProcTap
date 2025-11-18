"""
Discord AudioSource implementation for proctap.

Streams process audio to Discord voice channels. The fixed 48kHz stereo float32 format
is automatically converted to Discord's required format (48kHz, 16-bit PCM, stereo).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Optional, cast

import numpy as np

try:
    import discord
except ImportError as e:
    raise ImportError(
        "discord.py is required for ProcessAudioSource. "
        "Install with: pip install discord.py"
    ) from e

from ..core import ProcessAudioCapture

logger = logging.getLogger(__name__)

# Discord audio constants
DISCORD_SAMPLE_RATE = 48000  # Hz
DISCORD_CHANNELS = 2  # Stereo
DISCORD_SAMPLE_SIZE = 2  # 16-bit = 2 bytes
DISCORD_FRAME_DURATION_MS = 20  # ms
DISCORD_SAMPLES_PER_FRAME = int(DISCORD_SAMPLE_RATE * DISCORD_FRAME_DURATION_MS / 1000)
DISCORD_FRAME_SIZE = DISCORD_SAMPLES_PER_FRAME * DISCORD_CHANNELS * DISCORD_SAMPLE_SIZE  # 3840 bytes


class ProcessAudioSource(discord.AudioSource):
    """
    Discord AudioSource that captures audio from a specific process.

    This class streams audio from a target process to Discord voice channels.
    The fixed 48kHz stereo float32 format is automatically converted to Discord's requirements.

    Args:
        pid: Process ID to capture audio from
        gain: Audio gain multiplier (default: 1.0)
        max_queue_frames: Maximum frames to buffer (default: 50)

    Example:
        ```python
        import discord
        from proctap.contrib import ProcessAudioSource

        # In your Discord bot
        voice_client = await channel.connect()
        source = ProcessAudioSource(pid=12345, gain=1.2)
        voice_client.play(source)
        ```

    Note:
        - StreamConfig automatically converts to Discord format (48kHz, stereo, 16-bit)
        - Runs capture in a separate thread for minimal latency
    """

    def __init__(
        self,
        pid: int,
        gain: float = 1.0,
        max_queue_frames: int = 50,
    ) -> None:
        self.pid = pid
        self.gain = gain
        self.max_queue_frames = max_queue_frames

        self._tap: Optional[ProcessAudioCapture] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Audio queue and buffer
        self._audio_queue: deque[bytes] = deque(maxlen=max_queue_frames)
        self._queue_lock = threading.Lock()
        self._buffer = bytearray()

        # Statistics
        self._frames_dropped = 0
        self._frames_served = 0

        logger.info(f"ProcessAudioSource created for PID {pid} (gain={gain})")

    def start(self) -> None:
        """Start audio capture from the target process."""
        if self._capture_thread is not None:
            logger.warning("Audio capture already started")
            return

        logger.info(f"Starting audio capture for PID {self.pid}")

        # Create ProcessAudioCapture with Discord format
        config = StreamConfig(
            sample_rate=DISCORD_SAMPLE_RATE,
            channels=DISCORD_CHANNELS,
            sample_width=DISCORD_SAMPLE_SIZE
        )
        self._tap = ProcessAudioCapture(pid=self.pid)
        self._tap.start()

        logger.info(f"Discord format configured: {DISCORD_SAMPLE_RATE}Hz, {DISCORD_CHANNELS}ch, {DISCORD_SAMPLE_SIZE*8}bit")

        # Start capture thread
        self._stop_event.clear()
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name=f"ProcessAudioSource-{self.pid}"
        )
        self._capture_thread.start()

        logger.info("Audio capture started")

    def stop(self) -> None:
        """Stop audio capture and release resources."""
        if self._capture_thread is None:
            return

        logger.info("Stopping audio capture...")
        self._stop_event.set()

        if self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None

        if self._tap is not None:
            try:
                self._tap.close()
            except Exception:
                logger.exception("Error closing ProcessAudioCapture")
            finally:
                self._tap = None

        logger.info(
            f"Audio capture stopped. Stats: served={self._frames_served}, dropped={self._frames_dropped}"
        )

    def _capture_loop(self) -> None:
        """
        Capture loop running in separate thread.
        Reads pre-converted audio from ProcessAudioCapture and applies gain.
        """
        logger.debug("Capture loop started")

        while not self._stop_event.is_set():
            try:
                # Read audio with timeout
                if self._tap is None:
                    break
                chunk = self._tap.read(timeout=0.5)

                if chunk is None or len(chunk) == 0:
                    continue

                # Apply gain if needed
                if self.gain != 1.0:
                    chunk = self._apply_gain(chunk)

                # Queue the audio chunk
                with self._queue_lock:
                    try:
                        self._audio_queue.append(chunk)
                    except IndexError:
                        # Queue full, frame dropped
                        self._frames_dropped += 1

            except Exception:
                logger.exception("Error in capture loop")
                time.sleep(0.1)  # Prevent busy loop on error

        logger.debug("Capture loop ended")

    def _apply_gain(self, chunk: bytes) -> bytes:
        """
        Apply gain to 16-bit PCM audio data.

        Args:
            chunk: Raw 16-bit PCM audio data

        Returns:
            Audio data with gain applied
        """
        try:
            # Parse as 16-bit PCM (already converted by StreamConfig)
            audio_data = np.frombuffer(chunk, dtype=np.int16)

            # Apply gain with clipping
            audio_data = audio_data.astype(np.float32)
            audio_data = np.clip(audio_data * self.gain, -32768, 32767)
            audio_data = audio_data.astype(np.int16)

            return cast(bytes, audio_data.tobytes())

        except Exception:
            logger.exception("Error applying gain")
            return chunk  # Return original on error

    def read(self) -> bytes:
        """
        Read one Discord audio frame (20ms @ 48kHz = 3840 bytes).

        This method is called by discord.py's voice client.

        Returns:
            3840 bytes of 16-bit PCM stereo audio, or silence if no data available
        """
        # Accumulate data until we have a full Discord frame
        while len(self._buffer) < DISCORD_FRAME_SIZE:
            with self._queue_lock:
                if not self._audio_queue:
                    # No data available, return silence
                    silence = b"\x00" * DISCORD_FRAME_SIZE
                    return silence

                chunk = self._audio_queue.popleft()
                self._buffer.extend(chunk)

        # Extract one Discord frame
        frame = bytes(self._buffer[:DISCORD_FRAME_SIZE])
        del self._buffer[:DISCORD_FRAME_SIZE]

        self._frames_served += 1
        return frame

    def is_opus(self) -> bool:
        """
        Indicate whether this source provides Opus-encoded audio.

        Returns:
            False (this source provides raw PCM)
        """
        return False

    def cleanup(self) -> None:
        """
        Cleanup resources when discord.py is done with this source.

        This is called automatically by discord.py.
        """
        self.stop()

    @property
    def stats(self) -> dict[str, int]:
        """
        Get capture statistics.

        Returns:
            Dictionary with keys:
            - 'frames_served': Number of frames successfully served
            - 'frames_dropped': Number of frames dropped due to queue overflow
            - 'queue_size': Current number of frames in queue
        """
        with self._queue_lock:
            queue_size = len(self._audio_queue)

        return {
            "frames_served": self._frames_served,
            "frames_dropped": self._frames_dropped,
            "queue_size": queue_size,
        }
