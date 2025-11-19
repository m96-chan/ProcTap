"""
Windows audio capture backend using WASAPI Process Loopback.

This backend wraps the native C++ extension (_native) for Windows-specific
process audio capture functionality.
"""

from __future__ import annotations

from typing import Optional
import logging

from .base import AudioBackend
from .converter import AudioConverter, is_conversion_needed, SampleFormat
from ..format import ResamplingQuality, FIXED_AUDIO_FORMAT

try:
    from ..converter_native import NativeAudioConverter, HAS_NATIVE_CONVERTER
except ImportError:
    HAS_NATIVE_CONVERTER = False
    NativeAudioConverter = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class WindowsBackend(AudioBackend):
    """
    Windows implementation using WASAPI Process Loopback.

    Requires:
    - Windows 10 20H1 or later
    - C++ native extension (_native)
    """

    def __init__(
        self,
        pid: int,
        sample_rate: int = 44100,
        channels: int = 2,
        sample_width: int = 2,
        sample_format: str = SampleFormat.INT16,
        resample_quality: ResamplingQuality | None = None,
        use_native_converter: bool = False,
    ) -> None:
        """
        Initialize Windows backend.

        Args:
            pid: Process ID to capture audio from
            sample_rate: Desired output sample rate in Hz (44100, 48000, 96000, 192000, etc.)
            channels: Desired output channel count (1-8)
            sample_width: Desired output sample width in bytes (2=16bit, 3=24bit, 4=32bit/float)
            sample_format: Desired output format (int16, int24, int24_32, int32, float32)

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

        # Get native format from WASAPI
        native_format = self._native.get_format()
        src_rate = native_format['sample_rate']
        src_channels = native_format['channels']
        src_width = native_format['bits_per_sample'] // 8
        self._native_src_rate = src_rate
        self._native_src_channels = src_channels
        self._native_src_format = "int16"
        self._native_converter: Optional[NativeAudioConverter] = None

        requested_quality = resample_quality or ResamplingQuality.LOW_LATENCY
        self._use_native_converter = False

        if use_native_converter:
            if not HAS_NATIVE_CONVERTER:
                logger.warning(
                    "Native SIMD converter requested but not available. "
                    "Falling back to Python-based converter."
                )
            elif src_width not in (2, 4):
                logger.warning(
                    "Native converter currently supports only 16-bit or float32 "
                    "WASAPI formats (got %s bytes). Falling back to Python converter.",
                    src_width,
                )
            else:
                try:
                    native_converter = NativeAudioConverter(quality=requested_quality)
                    self._native_converter = native_converter
                    self._use_native_converter = True
                    self._native_src_format = "float32" if src_width == 4 else "int16"
                    logger.info(
                        "Native SIMD converter enabled (quality=%s)",
                        native_converter.quality.value,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to initialize native converter: %s. "
                        "Falling back to Python converter.",
                        exc,
                    )
                    self._native_converter = None
                    self._use_native_converter = False

        self._converter: Optional[AudioConverter]
        if self._use_native_converter:
            fixed_width = 4
            if (
                FIXED_AUDIO_FORMAT.sample_rate != sample_rate
                or FIXED_AUDIO_FORMAT.channels != channels
                or sample_width != fixed_width
            ):
                self._converter = AudioConverter(
                    src_rate=FIXED_AUDIO_FORMAT.sample_rate,
                    src_channels=FIXED_AUDIO_FORMAT.channels,
                    src_width=fixed_width,
                    src_format=SampleFormat.FLOAT32,
                    dst_rate=sample_rate,
                    dst_channels=channels,
                    dst_width=sample_width,
                    dst_format=sample_format,
                    auto_detect_format=False,
                )
                logger.info(
                    "Secondary conversion (fixed float32 -> requested) enabled: "
                    "%sHz/%sch/float32 -> %sHz/%sch/%s",
                    FIXED_AUDIO_FORMAT.sample_rate,
                    FIXED_AUDIO_FORMAT.channels,
                    sample_rate,
                    channels,
                    sample_format,
                )
            else:
                self._converter = None
                logger.debug(
                    "Native converter outputs match desired format "
                    "(48kHz/float32 stereo)."
                )
        else:
            # Initialize Python converter if format conversion is needed
            if is_conversion_needed(
                src_rate, src_channels, src_width,
                sample_rate, channels, sample_width
            ):
                self._converter = AudioConverter(
                    src_rate=src_rate,
                    src_channels=src_channels,
                    src_width=src_width,
                    src_format=SampleFormat.INT16,
                    dst_rate=sample_rate,
                    dst_channels=channels,
                    dst_width=sample_width,
                    dst_format=sample_format,
                )
                logger.info(
                    f"Audio format conversion enabled: "
                    f"{src_rate}Hz/{src_channels}ch/int16 -> "
                    f"{sample_rate}Hz/{channels}ch/{sample_format}"
                )
            else:
                self._converter = None
                logger.debug("No audio format conversion needed (formats match)")

        # Store desired format for get_format()
        self._output_format = {
            'sample_rate': sample_rate,
            'channels': channels,
            'bits_per_sample': sample_width * 8,
            'sample_format': sample_format,
        }
        logger.debug(f"WindowsBackend initialized with output_format: {self._output_format}")

    def start(self) -> None:
        """Start WASAPI audio capture."""
        logger.debug(f"Starting WASAPI capture for PID {self._pid}")
        self._native.start()
        logger.debug(f"WASAPI capture started successfully for PID {self._pid}")

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
            PCM audio data as bytes (converted to desired format if needed),
            or empty bytes if no data available
        """
        data = self._native.read()
        # Debug logging only when data is received (avoid spam)
        if data:
            logger.debug(f"Native read: {len(data)} bytes")

        if self._native_converter and data:
            try:
                data = self._native_converter.convert_to_fixed_format(
                    data,
                    self._native_src_rate,
                    self._native_src_channels,
                    self._native_src_format,
                )
                logger.debug(f"Native SIMD conversion complete: {len(data)} bytes")
            except Exception as exc:
                logger.error(f"Native converter failed: {exc}")
                return b''

        # Apply format conversion if needed
        if self._converter and data:
            try:
                data_before = len(data)
                data = self._converter.convert(data)
                logger.debug(f"Converted: {data_before} -> {len(data) if data else 0} bytes")
            except Exception as e:
                logger.error(f"Error converting audio format: {e}")
                return b''

        return data

    def get_format(self) -> dict[str, int | object]:
        """
        Get audio format (output format after conversion).

        Returns:
            Dictionary with 'sample_rate', 'channels', 'bits_per_sample'

        Note:
            Returns the converted output format, not the native WASAPI format.
            To get the native format, use self._native.get_format() directly.
        """
        logger.debug(f"get_format() returning: {self._output_format}")
        return self._output_format
