"""Type stubs for _native C++ extension module."""

from typing import Optional

class ProcessLoopback:
    """
    Native C++ implementation of WASAPI process-specific audio capture.

    Uses ActivateAudioInterfaceAsync for per-process loopback recording
    on Windows 10 20H1+ / Windows 11.
    """

    def __init__(self, process_id: int) -> None:
        """
        Initialize ProcessLoopback for a specific process.

        Args:
            process_id: Target process ID to capture audio from

        Raises:
            RuntimeError: If initialization fails
        """
        ...

    def start(self) -> None:
        """
        Start audio capture.

        Raises:
            RuntimeError: If capture fails to start
        """
        ...

    def stop(self) -> None:
        """
        Stop audio capture.

        Raises:
            RuntimeError: If capture fails to stop
        """
        ...

    def read(self) -> Optional[bytes]:
        """
        Read captured audio data.

        Returns:
            PCM audio data as bytes, or None if no data is available

        Note:
            Returns raw PCM data in the format specified by get_format()
        """
        ...

    def get_format(self) -> dict[str, int]:
        """
        Get audio format information.

        Returns:
            Dictionary with keys:
            - 'sample_rate': Sample rate in Hz (e.g., 48000)
            - 'channels': Number of channels (e.g., 2 for stereo)
            - 'bits_per_sample': Bits per sample (e.g., 16)
        """
        ...

    def is_process_specific(self) -> bool:
        """
        Check if process-specific capture is active.

        Returns:
            True if capturing from specific process, False if system-wide fallback
        """
        ...

    def get_last_error(self) -> str:
        """
        Get the last error message.

        Returns:
            Error message string, or empty string if no error
        """
        ...
