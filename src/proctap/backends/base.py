"""
Abstract base class for platform-specific audio capture backends.

STANDARD FORMAT:
All backends MUST convert audio to this standard format:
- Sample rate: 48000 Hz
- Channels: 2 (stereo)
- Sample format: float32 (IEEE 754)
- Value range: [-1.0, 1.0] (normalized)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal, Optional
import numpy as np


# Standard audio format constants for all backends
STANDARD_SAMPLE_RATE = 48000
STANDARD_CHANNELS = 2
STANDARD_FORMAT = 'float32'
STANDARD_DTYPE = np.float32
STANDARD_SAMPLE_WIDTH = 4  # bytes (32-bit float)

# Canonical resample quality modes. Defined here (a dependency-free module that
# every backend already imports) so all modules share a single source of truth.
ResampleQuality = Literal['best', 'medium', 'fast']


class AudioBackend(ABC):
    """
    Abstract base class for audio capture backends.

    Each platform-specific backend must implement these methods to provide
    process-specific audio capture functionality.
    """

    def __init__(self, pid: int) -> None:
        """
        Initialize the backend for a specific process.

        Args:
            pid: Process ID to capture audio from
        """
        self._pid = pid

    @property
    def pid(self) -> int:
        """Get the target process ID."""
        return self._pid

    @abstractmethod
    def start(self) -> None:
        """
        Start audio capture from the target process.

        Raises:
            RuntimeError: If capture fails to start
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """
        Stop audio capture.

        Should be safe to call multiple times.
        """
        pass

    @abstractmethod
    def read(self) -> Optional[bytes]:
        """
        Read audio data from the capture buffer.

        Returns:
            PCM audio data as bytes, or None if no data is available.

        Sentinel convention (consistent across all backends):
            - None            -> no usable data right now: nothing buffered, or a
                                 chunk was logged-and-skipped after a recoverable
                                 error (e.g. format conversion failed).
            - non-empty bytes -> a real audio chunk in standard format.
            - b'' is never returned to signal an error.

        Unrecoverable errors should be raised as exceptions, not encoded in the
        return value.

        Note:
            This method should not block for extended periods.
            Return None quickly if no data is available.
        """
        pass

    @abstractmethod
    def get_format(self) -> dict[str, int | str]:
        """
        Get audio format information.

        Returns:
            Dictionary with keys:
            - 'sample_rate': Sample rate in Hz (e.g., 48000)
            - 'channels': Number of channels (e.g., 2 for stereo)
            - 'bits_per_sample': Bits per sample (e.g., 32)
            - 'sample_format': Format string (e.g., 'float32')
        """
        pass
