"""
Audio analysis and visualization for proctap.

Provides real-time audio analysis including:
- Spectrum analysis (FFT)
- Volume metering (RMS, peak)
- Frequency analysis
- CLI and GUI visualization modes

Usage:
    # CLI mode (terminal-based)
    python -m proctap.contrib.analysis --pid 12345

    # GUI mode (matplotlib window)
    python -m proctap.contrib.analysis --pid 12345 --gui

    # Or use process name
    python -m proctap.contrib.analysis --name "VRChat.exe" --gui
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from collections import deque
from typing import Optional

import numpy as np
from numpy.typing import NDArray

from ..core import ProcessAudioCapture

logger = logging.getLogger(__name__)


class AudioAnalyzer:
    """
    Real-time audio analyzer for ProcessAudioCapture.

    Analyzes audio streams and provides:
    - RMS volume (dB)
    - Peak amplitude
    - Spectrum analysis (FFT)
    - Frequency analysis
    """

    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
        fft_size: int = 2048,
        update_interval: float = 0.05,  # 50ms
    ):
        """
        Initialize audio analyzer.

        Args:
            sample_rate: Audio sample rate in Hz
            channels: Number of audio channels
            fft_size: FFT window size (power of 2)
            update_interval: Analysis update interval in seconds
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.fft_size = fft_size
        self.update_interval = update_interval

        # Analysis results (thread-safe)
        self._lock = threading.Lock()
        self._rms_db: float = -np.inf
        self._peak_db: float = -np.inf
        self._spectrum: NDArray[np.float32] = np.zeros(fft_size // 2, dtype=np.float32)
        self._freqs: NDArray[np.float32] = np.fft.rfftfreq(fft_size, 1 / sample_rate).astype(np.float32)

        # Audio buffer for analysis (numpy ring buffer for efficiency)
        self._buffer: NDArray[np.float32] = np.zeros(fft_size * 2, dtype=np.float32)
        self._buffer_pos: int = 0  # Current write position in ring buffer
        self._buffer_filled: int = 0  # Number of samples currently in buffer
        self._last_update = 0.0

    def process_audio(self, pcm: bytes) -> None:
        """
        Process audio chunk and update analysis.

        Args:
            pcm: Raw PCM audio data (float32)
        """
        # Convert to float32 samples
        samples = np.frombuffer(pcm, dtype=np.float32)

        # Convert stereo to mono if needed
        if self.channels == 2:
            samples = samples.reshape(-1, 2).mean(axis=1)

        # Add to ring buffer efficiently
        n_samples = len(samples)
        buffer_size = len(self._buffer)

        if n_samples >= buffer_size:
            # If new data is larger than buffer, just take the last buffer_size samples
            self._buffer[:] = samples[-buffer_size:]
            self._buffer_pos = 0
            self._buffer_filled = buffer_size
        else:
            # Write samples to ring buffer
            end_pos = self._buffer_pos + n_samples
            if end_pos <= buffer_size:
                # Simple case: no wrap-around
                self._buffer[self._buffer_pos:end_pos] = samples
            else:
                # Wrap-around case
                first_part = buffer_size - self._buffer_pos
                self._buffer[self._buffer_pos:] = samples[:first_part]
                self._buffer[:n_samples - first_part] = samples[first_part:]
            self._buffer_pos = end_pos % buffer_size
            self._buffer_filled = min(self._buffer_filled + n_samples, buffer_size)

        # Update analysis at specified interval
        now = time.time()
        if now - self._last_update >= self.update_interval:
            self._update_analysis()
            self._last_update = now

    def _update_analysis(self) -> None:
        """Update analysis from current buffer."""
        if self._buffer_filled < self.fft_size:
            return

        # Get latest samples from ring buffer (no list conversion)
        # We need the most recent fft_size samples ending at buffer_pos
        end_pos = self._buffer_pos
        start_pos = (end_pos - self.fft_size) % len(self._buffer)

        if start_pos < end_pos:
            # Simple case: no wrap-around
            samples = self._buffer[start_pos:end_pos].copy()
        else:
            # Wrap-around case: concatenate two slices
            samples = np.concatenate([
                self._buffer[start_pos:],
                self._buffer[:end_pos]
            ])

        # Calculate RMS
        rms = np.sqrt(np.mean(samples**2))
        rms_db = 20 * np.log10(rms + 1e-10)  # Avoid log(0)

        # Calculate peak
        peak = np.max(np.abs(samples))
        peak_db = 20 * np.log10(peak + 1e-10)

        # FFT spectrum
        windowed = samples * np.hanning(len(samples))
        spectrum = np.abs(np.fft.rfft(windowed))
        spectrum_db = 20 * np.log10(spectrum + 1e-10)

        # Update thread-safe
        with self._lock:
            self._rms_db = float(rms_db)
            self._peak_db = float(peak_db)
            self._spectrum = spectrum_db.astype(np.float32)

    @property
    def rms_db(self) -> float:
        """Get current RMS level in dB."""
        with self._lock:
            return self._rms_db

    @property
    def peak_db(self) -> float:
        """Get current peak level in dB."""
        with self._lock:
            return self._peak_db

    @property
    def spectrum(self) -> NDArray[np.float32]:
        """Get current spectrum (frequency domain, dB)."""
        with self._lock:
            result: NDArray[np.float32] = self._spectrum.copy()
            return result

    @property
    def freqs(self) -> NDArray[np.float32]:
        """Get frequency bins (Hz)."""
        result: NDArray[np.float32] = self._freqs.copy()
        return result


class CLIVisualizer:
    """Terminal-based real-time audio visualizer."""

    def __init__(self, analyzer: AudioAnalyzer, width: int = 80):
        """
        Initialize CLI visualizer.

        Args:
            analyzer: AudioAnalyzer instance
            width: Terminal width in characters
        """
        self.analyzer = analyzer
        self.width = width
        self.running = False
        self._first_frame = True
        self._line_count = 0

    def start(self) -> None:
        """Start visualization loop."""
        self.running = True

        # Hide cursor for smoother display
        print("\033[?25l", end="", flush=True)

        try:
            while self.running:
                self._render_frame()
                time.sleep(0.05)  # 20 FPS for smoother updates
        except KeyboardInterrupt:
            print("\n\nStopped by user")
        finally:
            # Show cursor again
            print("\033[?25h", end="", flush=True)

    def stop(self) -> None:
        """Stop visualization."""
        self.running = False

    def _render_frame(self) -> None:
        """Render one frame of visualization."""
        rms_db = self.analyzer.rms_db
        peak_db = self.analyzer.peak_db
        spectrum = self.analyzer.spectrum

        # Build output in memory first (reduces flicker)
        lines = []

        # Header
        lines.append("=" * self.width)
        lines.append(f"{'Audio Analysis - CLI Mode (Press Ctrl+C to stop)':^{self.width}}")
        lines.append("=" * self.width)
        lines.append("")

        # Volume meters
        lines.append("Volume Meters:")
        lines.append("-" * self.width)

        # RMS meter
        rms_bar = self._render_meter(rms_db, -60, 0, self.width - 25, "RMS")
        lines.append(f"  RMS:  {rms_bar}  {rms_db:6.1f} dB")

        # Peak meter
        peak_bar = self._render_meter(peak_db, -60, 0, self.width - 25, "PEAK")
        lines.append(f"  Peak: {peak_bar}  {peak_db:6.1f} dB")

        lines.append("")

        # Spectrum analyzer (frequency bands)
        lines.append("Spectrum Analyzer:")
        lines.append("-" * self.width)

        # Define frequency bands
        bands = [
            ("Sub", 20, 60),
            ("Bass", 60, 250),
            ("Low Mid", 250, 500),
            ("Mid", 500, 2000),
            ("High Mid", 2000, 4000),
            ("Presence", 4000, 8000),
            ("Brilliance", 8000, 20000),
        ]

        freqs = self.analyzer.freqs
        for name, low, high in bands:
            # Find frequency indices
            idx_low = np.searchsorted(freqs, low)
            idx_high = np.searchsorted(freqs, high)

            # Average spectrum in this band
            if idx_high > idx_low:
                band_level = float(np.mean(spectrum[idx_low:idx_high]))
            else:
                band_level = -np.inf

            # Render band
            bar = self._render_meter(band_level, -80, -20, self.width - 30, "SPECTRUM")
            lines.append(f"  {name:12s} {bar}  {band_level:6.1f} dB")

        lines.append("")
        lines.append("-" * self.width)
        lines.append(f"Update: {time.strftime('%H:%M:%S')}")

        # Move cursor back and print all lines at once
        if not self._first_frame:
            # Move cursor up by the number of lines we printed last time
            print(f"\033[{self._line_count}A", end="")
        else:
            self._first_frame = False

        # Print all lines
        self._line_count = len(lines)
        for line in lines:
            # Clear line and print
            print(f"\033[K{line}")

        # Flush output for immediate display
        sys.stdout.flush()

    def _render_meter(
        self,
        value: float,
        min_db: float,
        max_db: float,
        width: int,
        meter_type: str = "RMS",
    ) -> str:
        """
        Render a horizontal meter bar.

        Args:
            value: Current value in dB
            min_db: Minimum dB value
            max_db: Maximum dB value
            width: Bar width in characters
            meter_type: Meter type for coloring

        Returns:
            Rendered meter string
        """
        # Normalize to 0-1
        if value <= min_db:
            normalized = 0.0
        elif value >= max_db:
            normalized = 1.0
        else:
            normalized = (value - min_db) / (max_db - min_db)

        # Calculate bar length
        bar_length = int(normalized * width)

        # Color coding (using ASCII for compatibility)
        if normalized > 0.9:  # Red zone
            char = "#"
        elif normalized > 0.7:  # Yellow zone
            char = "="
        else:  # Green zone
            char = "-"

        # Build bar
        bar = char * bar_length + " " * (width - bar_length)
        return f"[{bar}]"


class GUIVisualizer:
    """Matplotlib-based real-time audio visualizer."""

    def __init__(self, analyzer: AudioAnalyzer):
        """
        Initialize GUI visualizer.

        Args:
            analyzer: AudioAnalyzer instance
        """
        self.analyzer = analyzer
        self.running = False

        # Import matplotlib here (optional dependency)
        try:
            import matplotlib.pyplot as plt  # type: ignore[import-not-found]
            from matplotlib.animation import FuncAnimation  # type: ignore[import-not-found]

            self.plt = plt
            self.FuncAnimation = FuncAnimation
        except ImportError as e:
            raise ImportError(
                "matplotlib is required for GUI mode. "
                "Install with: pip install matplotlib"
            ) from e

        # Setup figure
        self.fig, (self.ax_meter, self.ax_spectrum) = self.plt.subplots(
            2, 1, figsize=(12, 8)
        )
        self.fig.suptitle("Audio Analysis - GUI Mode")

        # Volume meter plot
        self.ax_meter.set_xlim(0, 1)
        self.ax_meter.set_ylim(-60, 0)
        self.ax_meter.set_xlabel("Time")
        self.ax_meter.set_ylabel("Level (dB)")
        self.ax_meter.set_title("Volume Meters")
        self.ax_meter.grid(True, alpha=0.3)

        # Historical data
        self.time_history: deque[float] = deque(maxlen=100)
        self.rms_history: deque[float] = deque(maxlen=100)
        self.peak_history: deque[float] = deque(maxlen=100)

        (self.line_rms,) = self.ax_meter.plot([], [], "g-", label="RMS", linewidth=2)
        (self.line_peak,) = self.ax_meter.plot([], [], "r-", label="Peak", linewidth=1)
        self.ax_meter.legend()

        # Spectrum plot
        self.ax_spectrum.set_xlim(20, 20000)
        self.ax_spectrum.set_ylim(-80, -20)
        self.ax_spectrum.set_xlabel("Frequency (Hz)")
        self.ax_spectrum.set_ylabel("Level (dB)")
        self.ax_spectrum.set_title("Spectrum Analyzer")
        self.ax_spectrum.set_xscale("log")
        self.ax_spectrum.grid(True, alpha=0.3, which="both")

        freqs = self.analyzer.freqs
        (self.line_spectrum,) = self.ax_spectrum.plot(
            freqs, np.zeros_like(freqs), "b-", linewidth=1
        )

        # Start time
        self.start_time = time.time()

    def start(self) -> None:
        """Start GUI visualization."""
        self.running = True

        # Animation function
        def update(frame):
            if not self.running:
                return

            # Update time
            current_time = time.time() - self.start_time
            self.time_history.append(current_time)
            self.rms_history.append(self.analyzer.rms_db)
            self.peak_history.append(self.analyzer.peak_db)

            # Update meter plot
            if len(self.time_history) > 1:
                # Normalize time to 0-1 range
                times = np.array(self.time_history)
                times_norm = (times - times[0]) / (times[-1] - times[0] + 1e-6)

                self.line_rms.set_data(times_norm, list(self.rms_history))
                self.line_peak.set_data(times_norm, list(self.peak_history))

            # Update spectrum plot
            spectrum = self.analyzer.spectrum
            freqs = self.analyzer.freqs
            self.line_spectrum.set_data(freqs, spectrum)

        # Run animation
        anim = self.FuncAnimation(
            self.fig, update, interval=100, blit=False, cache_frame_data=False
        )

        self.plt.tight_layout()
        self.plt.show()

    def stop(self) -> None:
        """Stop GUI visualization."""
        self.running = False
        self.plt.close(self.fig)


def main():
    """Main entry point for audio analysis CLI."""
    parser = argparse.ArgumentParser(
        description="Real-time audio analysis and visualization for proctap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # CLI mode (terminal-based)
  %(prog)s --pid 12345

  # GUI mode (matplotlib window)
  %(prog)s --pid 12345 --gui

  # Use process name instead of PID
  %(prog)s --name "VRChat.exe" --gui

  # Adjust FFT size for better frequency resolution
  %(prog)s --pid 12345 --fft-size 4096 --gui
        """,
    )

    # Process selection (mutually exclusive)
    process_group = parser.add_mutually_exclusive_group(required=True)
    process_group.add_argument(
        "--pid", type=int, help="Process ID to capture audio from"
    )
    process_group.add_argument(
        "--name", type=str, help="Process name to capture audio from (e.g., 'VRChat.exe')"
    )

    # Visualization mode
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Use GUI mode (matplotlib) instead of CLI mode (terminal)",
    )

    # Analysis parameters
    parser.add_argument(
        "--fft-size",
        type=int,
        default=2048,
        choices=[512, 1024, 2048, 4096, 8192],
        help="FFT window size (default: 2048)",
    )

    parser.add_argument(
        "--update-interval",
        type=float,
        default=0.05,
        help="Analysis update interval in seconds (default: 0.05)",
    )

    # Logging
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Resolve PID if name provided
    pid = args.pid
    if args.name:
        try:
            import psutil

            for proc in psutil.process_iter(["pid", "name"]):
                if proc.info["name"] == args.name:
                    pid = proc.info["pid"]
                    logger.info(f"Found process '{args.name}' with PID {pid}")
                    break
            else:
                logger.error(f"Process '{args.name}' not found")
                return 1
        except ImportError:
            logger.error(
                "psutil is required for --name option. Install with: pip install psutil"
            )
            return 1

    # Create analyzer
    analyzer = AudioAnalyzer(
        sample_rate=48000,
        channels=2,
        fft_size=args.fft_size,
        update_interval=args.update_interval,
    )

    # Create visualizer
    if args.gui:
        logger.info("Starting GUI mode...")
        try:
            visualizer = GUIVisualizer(analyzer)
        except ImportError as e:
            logger.error(str(e))
            return 1
    else:
        logger.info("Starting CLI mode...")
        visualizer = CLIVisualizer(analyzer)

    # Create audio capture
    try:
        logger.info(f"Starting audio capture from PID {pid}...")

        # Create callback
        def on_audio(pcm: bytes, frames: int):
            analyzer.process_audio(pcm)

        # Create tap with callback
        tap = ProcessAudioCapture(pid=pid, on_data=on_audio)
        tap.start()
        logger.info("Audio capture started")

        # Start visualization (blocking)
        visualizer.start()

    except KeyboardInterrupt:
        logger.info("\nStopped by user")
    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1
    finally:
        # Cleanup
        logger.info("Cleaning up...")
        visualizer.stop()
        tap.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
