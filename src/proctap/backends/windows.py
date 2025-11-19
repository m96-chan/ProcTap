"""
Windows audio capture backend using WASAPI Process Loopback.

This backend wraps the native C++ extension (_native) for Windows-specific
process audio capture functionality.

IMPORTANT: Always returns audio in standard format (48kHz/2ch/float32)
"""

from __future__ import annotations

from typing import Optional
import logging

from .base import (
    AudioBackend,
    STANDARD_SAMPLE_RATE,
    STANDARD_CHANNELS,
    STANDARD_FORMAT,
    STANDARD_SAMPLE_WIDTH,
)
from .converter import AudioConverter, SampleFormat

logger = logging.getLogger(__name__)


class WindowsBackend(AudioBackend):
    """
    Windows implementation using WASAPI Process Loopback.

    This backend always converts audio to the standard format:
    - 48000 Hz
    - 2 channels (stereo)
    - float32 (IEEE 754, normalized to [-1.0, 1.0])

    Requires:
    - Windows 10 20H1 or later
    - C++ native extension (_native)
    """

    def __init__(self, pid: int, resample_quality: str = 'best') -> None:
        """
        Initialize Windows backend.

        Args:
            pid: Process ID to capture audio from
            resample_quality: Resampling quality mode ('best', 'medium', 'fast')

        Raises:
            ImportError: If the native extension cannot be imported
        """
        super().__init__(pid)

        try:
            from .._native import ProcessLoopback  # type: ignore[attr-defined]
            self._native = ProcessLoopback(pid)
            logger.debug(f"Initialized Windows WASAPI backend for PID {pid}")
        except ImportError as e:
            raise ImportError(
                "Native extension (_native) could not be imported. "
                "Please build the extension with: pip install -e .\n"
                f"Original error: {e}"
            ) from e

        # Get native format from WASAPI (C++ may return 48k/float32 or 44.1k/int16)
        native_format = self._native.get_format()
        src_rate = native_format['sample_rate']
        src_channels = native_format['channels']
        src_bits = native_format['bits_per_sample']
        src_width = src_bits // 8

        # Detect source format (float32 or int16)
        if src_bits == 32 and src_rate == 48000:
            # C++ succeeded with float32 - no conversion needed!
            src_format = SampleFormat.FLOAT32
            self._converter = None
            logger.info(f"Native format is already standard (48kHz/float32) - no conversion needed")
        else:
            # C++ fell back to int16 - need conversion
            src_format = SampleFormat.INT16
            self._converter = AudioConverter(
                src_rate=src_rate,
                src_channels=src_channels,
                src_width=src_width,
                src_format=src_format,
                dst_rate=STANDARD_SAMPLE_RATE,
                dst_channels=STANDARD_CHANNELS,
                dst_width=STANDARD_SAMPLE_WIDTH,
                dst_format=SampleFormat.FLOAT32,
                resample_quality=resample_quality,  # type: ignore[arg-type]
            )
            logger.info(
                f"Audio format conversion enabled: "
                f"{src_rate}Hz/{src_channels}ch/{src_format} -> "
                f"{STANDARD_SAMPLE_RATE}Hz/{STANDARD_CHANNELS}ch/float32 "
                f"(quality={resample_quality})"
            )

    def start(self) -> None:
        """Start WASAPI audio capture."""
        self._native.start()
        logger.debug(f"Started audio capture for PID {self._pid}")

    def stop(self) -> None:
        """Stop WASAPI audio capture."""
        try:
            self._native.stop()
            logger.debug(f"Stopped audio capture for PID {self._pid}")
        except Exception as e:
            logger.error(f"Error stopping capture: {e}")

    def read(self) -> Optional[bytes]:
        """
        Read audio data from WASAPI capture buffer.

        Returns:
            PCM audio data as bytes in standard format (48kHz/2ch/float32),
            or empty bytes if no data available
        """
        data = self._native.read()

        # Apply format conversion if needed
        if self._converter and data:
            try:
                data = self._converter.convert(data)
            except Exception as e:
                logger.error(f"Error converting audio format: {e}")
                return b''

        return data

    def get_format(self) -> dict[str, int | str]:
        """
        Get audio format (always returns standard format).

        Returns:
            Dictionary with:
            - 'sample_rate': 48000
            - 'channels': 2
            - 'bits_per_sample': 32
            - 'sample_format': 'float32'
        """
        return {
            'sample_rate': STANDARD_SAMPLE_RATE,
            'channels': STANDARD_CHANNELS,
            'bits_per_sample': STANDARD_SAMPLE_WIDTH * 8,
            'sample_format': STANDARD_FORMAT,
        }
