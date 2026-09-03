"""
Linux audio capture backend.

This module provides process-specific audio capture on Linux using PulseAudio
or PipeWire with native support for both.

STATUS: Experimental - PulseAudio and PipeWire support implemented (v0.3.0+)

IMPORTANT: Always returns audio in standard format (48kHz/2ch/float32)

Features:
- Automatic detection of PipeWire vs PulseAudio
- Native PipeWire support via pw-record
- PulseAudio support via parec
- Per-process audio isolation using null-sink strategy
- Graceful fallback between backends
- Automatic format conversion to standard format

Requirements:
- pulsectl library (pip install pulsectl)
- For PulseAudio: parec command (pulseaudio-utils package)
- For PipeWire: pw-record command (pipewire-utils package)
"""

from __future__ import annotations

from typing import Optional, Callable, Any
from abc import ABC, abstractmethod
import json
import logging
import queue
import shutil
import threading
import subprocess
import os
import time

from .base import (
    AudioBackend,
    STANDARD_SAMPLE_RATE,
    STANDARD_CHANNELS,
    STANDARD_FORMAT,
    STANDARD_SAMPLE_WIDTH,
)
from .converter import AudioConverter, SampleFormat

# Try to import native PipeWire bindings
try:
    from . import pipewire_native
    PIPEWIRE_NATIVE_AVAILABLE = pipewire_native.is_available()
except (ImportError, AttributeError):
    PIPEWIRE_NATIVE_AVAILABLE = False
    pipewire_native = None  # type: ignore

logger = logging.getLogger(__name__)

# Type alias for audio callback
AudioCallback = Callable[[bytes, int], None]

# Capture buffering constants
DEFAULT_QUEUE_DEPTH_FRAMES = 50   # queued chunks; ~500ms at 10ms chunks
DEFAULT_CHUNK_DURATION_MS = 10    # duration of one captured/queued audio chunk


def detect_audio_server() -> str:
    """
    Detect which audio server is running on the system.

    Returns:
        "pipewire", "pulseaudio", or "unknown"
    """
    try:
        # Method 1: Check if PipeWire daemon is running
        result = subprocess.run(
            ['pgrep', '-x', 'pipewire'],
            capture_output=True,
            timeout=1.0
        )
        if result.returncode == 0:
            logger.debug("Detected PipeWire via process check")
            return "pipewire"

        # Method 2: Check if PulseAudio daemon is running
        result = subprocess.run(
            ['pgrep', '-x', 'pulseaudio'],
            capture_output=True,
            timeout=1.0
        )
        if result.returncode == 0:
            logger.debug("Detected PulseAudio via process check")
            return "pulseaudio"

        # Method 3: Check PulseAudio runtime directory for PipeWire
        pulse_runtime = os.environ.get('XDG_RUNTIME_DIR', '/run/user/1000')
        pipewire_socket = os.path.join(pulse_runtime, 'pipewire-0')
        if os.path.exists(pipewire_socket):
            logger.debug("Detected PipeWire via socket check")
            return "pipewire"

        logger.debug("Could not detect audio server type")
        return "unknown"

    except Exception as e:
        logger.debug(f"Error detecting audio server: {e}")
        return "unknown"


# ---------------------------------------------------------------------------
# pw-link / pw-dump helpers (used by PipeWireStrategy to avoid the
# sink_input_move + name-based pw-record approach that WirePlumber's session
# policy interferes with — see GitHub issue #48).
# ---------------------------------------------------------------------------

_PW_NODE_LOOKUP_RETRIES = 20
_PW_NODE_LOOKUP_INTERVAL_SEC = 0.05


def _pw_dump_capture() -> bytes:
    """Run ``pw-dump`` and return its raw stdout.

    Returns ``b""`` on any failure (missing binary, non-zero exit, timeout)
    so callers can fall back to "node not yet visible" without aborting.
    """
    try:
        result = subprocess.run(
            ["pw-dump"],
            capture_output=True,
            timeout=2.0,
            check=False,
        )
        if result.returncode != 0:
            logger.debug(
                "pw-dump returned non-zero: rc=%d stderr=%s",
                result.returncode,
                result.stderr[:200].decode("utf-8", errors="replace"),
            )
            return b""
        return result.stdout
    except FileNotFoundError:
        logger.debug("pw-dump binary not found")
        return b""
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug(f"pw-dump failed: {e}")
        return b""


def _pw_dump_parse(raw: bytes) -> list[dict[str, Any]]:
    """Parse ``pw-dump`` output into a list of object dicts.

    Returns an empty list (never raises) on empty/invalid input so
    consumers degrade to "no match" cleanly.
    """
    if not raw:
        return []
    try:
        data: Any = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [obj for obj in data if isinstance(obj, dict)]


def _pw_obj_props(obj: dict[str, Any]) -> dict[str, Any]:
    """Return ``obj['info']['props']`` as a dict, or ``{}`` when absent."""
    info = obj.get("info")
    if not isinstance(info, dict):
        return {}
    props = info.get("props")
    if not isinstance(props, dict):
        return {}
    return props


def _pw_coerce_int(value: Any) -> Optional[int]:
    """Coerce a pw-dump scalar (often a string) to ``int``; ``None`` on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pw_find_node_id_by_name(
    dump: list[dict[str, Any]], node_name: str
) -> Optional[int]:
    """Return the global node id whose ``node.name`` matches, or ``None``."""
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        if _pw_obj_props(obj).get("node.name") == node_name:
            return _pw_coerce_int(obj.get("id"))
    return None


def _pw_find_stream_node_ids_by_pid(
    dump: list[dict[str, Any]], pid: int
) -> list[int]:
    """Return ids of ``Stream/Output/Audio`` nodes for the given process.

    Some apps (multi-engine games, browsers) register more than one output
    stream, so this returns every matching node rather than the first hit.
    """
    pid_str = str(pid)
    ids: list[int] = []
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = _pw_obj_props(obj)
        media_class = props.get("media.class")
        if not isinstance(media_class, str):
            continue
        if not media_class.startswith("Stream/Output"):
            continue
        if str(props.get("application.process.id")) != pid_str:
            continue
        node_id = _pw_coerce_int(obj.get("id"))
        if node_id is not None:
            ids.append(node_id)
    return ids


def _pw_find_ports(
    dump: list[dict[str, Any]], node_id: int, direction: str
) -> dict[str, int]:
    """Return ``{audio.channel: global port id}`` for the given node + direction.

    ``direction`` is ``"in"`` or ``"out"``. Ports without an ``audio.channel``
    or a numeric global id are skipped.
    """
    ports: dict[str, int] = {}
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Port":
            continue
        props = _pw_obj_props(obj)
        if _pw_coerce_int(props.get("node.id")) != node_id:
            continue
        if props.get("port.direction") != direction:
            continue
        channel = props.get("audio.channel")
        if not isinstance(channel, str):
            continue
        port_id = _pw_coerce_int(obj.get("id"))
        if port_id is None:
            continue
        ports[channel] = port_id
    return ports


def _pw_link_already_linked(stderr: str) -> bool:
    """``pw-link`` returns non-zero + ``File exists`` when the link is already present."""
    return "File exists" in stderr


def _pw_link_ports(out_port_id: int, in_port_id: int) -> bool:
    """Link one output port to one input port by global port id.

    Returns ``True`` if the link is in place after the call (newly created
    *or* already existed), ``False`` on any other failure. Logs the outcome
    so post-mortems can trace which channels were wired.
    """
    try:
        result = subprocess.run(
            ["pw-link", str(out_port_id), str(in_port_id)],
            capture_output=True,
            timeout=2.0,
            check=False,
        )
    except FileNotFoundError:
        logger.error("pw-link binary not found; cannot establish port link")
        return False
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning(
            f"pw-link spawn failed (out={out_port_id}, in={in_port_id}): {e}"
        )
        return False

    stderr_text = result.stderr.decode("utf-8", errors="replace")
    if result.returncode == 0:
        logger.debug(f"pw-link ok: out={out_port_id} -> in={in_port_id}")
        return True
    if _pw_link_already_linked(stderr_text):
        logger.debug(
            f"pw-link already present: out={out_port_id} -> in={in_port_id}"
        )
        return True
    logger.warning(
        f"pw-link failed (rc={result.returncode}, out={out_port_id}, "
        f"in={in_port_id}): {stderr_text.strip()}"
    )
    return False


def _pw_link_nodes(
    dump: list[dict[str, Any]],
    src_node_id: int,
    src_direction: str,
    dst_node_id: int,
    dst_direction: str,
) -> int:
    """Link every shared channel between two nodes by global port id.

    Returns the number of channel pairs that ended up linked (newly
    created or pre-existing).
    """
    src_ports = _pw_find_ports(dump, src_node_id, src_direction)
    dst_ports = _pw_find_ports(dump, dst_node_id, dst_direction)
    linked = 0
    for channel, out_port in src_ports.items():
        in_port = dst_ports.get(channel)
        if in_port is None:
            continue
        if _pw_link_ports(out_port, in_port):
            linked += 1
    return linked


def _pw_poll_for(probe: Callable[[], Optional[Any]]) -> Optional[Any]:
    """Spin-call ``probe`` until it returns non-``None`` or the budget expires.

    Used to wait for the tap null-sink and the ``pw-record`` node to become
    visible in ``pw-dump`` after they are requested.
    """
    for _ in range(_PW_NODE_LOOKUP_RETRIES):
        result = probe()
        if result is not None:
            return result
        time.sleep(_PW_NODE_LOOKUP_INTERVAL_SEC)
    return None


class LinuxAudioStrategy(ABC):
    """
    Abstract base class for Linux audio capture strategies.

    Allows switching between PulseAudio and PipeWire implementations.
    """

    def __init__(
        self, pid: int, sample_rate: int, channels: int, sample_width: int
    ) -> None:
        """
        Every strategy is constructed with the target PID and capture format.

        This only declares the shared constructor contract; concrete subclasses
        override it and may supply their own sensible defaults for the format
        arguments.
        """
        ...

    @abstractmethod
    def connect(self) -> None:
        """Connect to the audio server."""
        pass

    @abstractmethod
    def find_process_stream(self, pid: int) -> bool:
        """
        Find audio stream for the target process.

        Args:
            pid: Process ID to find

        Returns:
            True if stream found, False otherwise
        """
        pass

    @abstractmethod
    def start_capture(self) -> None:
        """Start capturing audio from the target stream."""
        pass

    @abstractmethod
    def stop_capture(self) -> None:
        """Stop capturing audio."""
        pass

    @abstractmethod
    def read_audio(self, timeout: float = 0.1) -> Optional[bytes]:
        """
        Read audio data from capture buffer.

        Args:
            timeout: Maximum time to wait for data

        Returns:
            PCM audio data as bytes, or None if no data available
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Clean up resources."""
        pass

    @abstractmethod
    def get_format(self) -> dict[str, int | str]:
        """
        Get audio format information.

        Returns:
            Dictionary with 'sample_rate', 'channels', 'bits_per_sample'
        """
        pass


class _PulseCompatStrategy(LinuxAudioStrategy):
    """
    Shared base for strategies that drive capture through the PulseAudio API
    (or PipeWire's PulseAudio compatibility layer) using ``pulsectl``.

    Both PulseAudio and PipeWire isolate a process by creating a temporary
    null-sink, moving the target sink-input onto it and recording the null-sink's
    monitor source. The only real differences between the two are cosmetic
    (client name, sink names, log labels) and the external recorder invoked by
    :meth:`_build_capture_command` (``parec`` vs ``pw-record``). Everything else
    lives here so bug fixes apply to both backends at once.

    Subclasses customise behaviour via the class attributes below and by
    implementing :meth:`_build_capture_command`.
    """

    # --- Subclass-provided identity / labels -------------------------------
    _client_name: str = "proctap"
    _server_short: str = "PulseAudio"
    _connect_success_log: str = "Connected to PulseAudio server"
    _connect_failure_prefix: str = "Failed to connect to PulseAudio server"
    _connect_failure_hint: str = (
        "Make sure PulseAudio or PipeWire (with pulseaudio-compat) is running."
    )
    _sink_name_prefix: str = "proctap_isolated"
    _sink_description_prefix: str = "ProcTap_Isolated_PID"
    _capture_error_label: str = "Failed to start audio capture"
    _pulsectl_error_msg: str = (
        "pulsectl library is required for Linux audio capture. "
        "Install it with: pip install pulsectl"
    )

    def _init_common(
        self, pid: int, sample_rate: int, channels: int, sample_width: int
    ) -> None:
        """Initialise the fields shared by every PulseAudio-compatible strategy."""
        self._pid = pid
        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_width = sample_width
        self._bits_per_sample = sample_width * 8

        self._pulse: Any = None  # pulsectl.Pulse instance
        self._pulsectl: Any = None  # pulsectl module
        self._sink_input_index: Optional[int] = None
        self._stream_id: Optional[str] = None
        self._null_sink_index: Optional[int] = None
        self._null_sink_name: Optional[str] = None
        self._remap_source_index: Optional[int] = None
        self._remap_source_name: Optional[str] = None
        self._loopback_module_index: Optional[int] = None
        self._original_sink_index: Optional[int] = None
        self._audio_queue: queue.Queue[bytes] = queue.Queue(
            maxsize=DEFAULT_QUEUE_DEPTH_FRAMES
        )
        self._capture_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._isolation_mode = "remap"  # "remap" or "monitor" (fallback)
        self._chunk_duration_ms = DEFAULT_CHUNK_DURATION_MS

    def _import_pulsectl(self) -> None:
        """Import the pulsectl module, raising a helpful error if unavailable."""
        try:
            import pulsectl
            self._pulsectl = pulsectl
        except ImportError as e:
            raise RuntimeError(self._pulsectl_error_msg) from e

    def connect(self) -> None:
        """Connect to the audio server via the PulseAudio API."""
        try:
            self._pulse = self._pulsectl.Pulse(self._client_name)
            logger.info(self._connect_success_log)
        except Exception as e:
            raise RuntimeError(
                f"{self._connect_failure_prefix}: {e}. {self._connect_failure_hint}"
            ) from e

    def find_process_stream(self, pid: int) -> bool:
        """
        Find the sink-input for the target process.

        Args:
            pid: Process ID to find

        Returns:
            True if stream found, False otherwise

        Raises:
            RuntimeError: If not connected
        """
        if self._pulse is None:
            raise RuntimeError(
                f"Not connected to {self._server_short}. Call connect() first."
            )

        try:
            sink_inputs = self._pulse.sink_input_list()
            logger.debug(f"Found {len(sink_inputs)} sink inputs")

            for sink_input in sink_inputs:
                # Check application.process.id property
                process_id_str = sink_input.proplist.get('application.process.id')
                if process_id_str and process_id_str == str(pid):
                    self._sink_input_index = sink_input.index
                    self._note_stream(sink_input)
                    logger.info(
                        f"Found sink-input #{sink_input.index} for PID {pid}: "
                        f"{sink_input.proplist.get('application.name', 'Unknown')}"
                    )
                    return True

            logger.warning(f"No audio stream found for PID {pid}")
            return False

        except Exception as e:
            logger.error(f"Error finding process stream: {e}")
            return False

    def _note_stream(self, sink_input: Any) -> None:
        """Hook for subclasses to record extra stream metadata (no-op by default)."""

    def start_capture(self) -> None:
        """
        Start capturing audio from the target stream.

        Creates an isolated capture using the null-sink strategy. Subclasses
        decide what happens when isolation fails via :meth:`_handle_isolation_failure`.

        Raises:
            RuntimeError: If sink-input not found or capture fails to start
        """
        if self._sink_input_index is None:
            raise RuntimeError(
                "No sink-input found. Call find_process_stream() first."
            )

        try:
            # Get sink-input details
            sink_input = self._pulse.sink_input_info(self._sink_input_index)
            self._original_sink_index = sink_input.sink

            try:
                self._setup_isolated_capture()
                logger.info(f"Using isolated capture mode for PID {self._pid}")
            except Exception as e:
                self._handle_isolation_failure(e)

        except Exception as e:
            raise RuntimeError(f"{self._capture_error_label}: {e}") from e

    def _handle_isolation_failure(self, exc: Exception) -> None:
        """
        Decide what to do when isolated capture setup fails.

        The default re-raises (no fallback). PulseAudio overrides this to fall
        back to whole-sink monitor capture.
        """
        raise exc

    def _find_sink_by_name(self, sink_name: str) -> Any:
        """Return the sink with the given name, or None if not present."""
        for sink in self._pulse.sink_list():
            if sink.name == sink_name:
                return sink
        return None

    def _setup_isolated_capture(self) -> None:
        """
        Setup isolated audio capture using the null-sink strategy.

        1. Create a null-sink as a temporary destination
        2. Move the sink-input to the null-sink
        3. Get the null-sink's monitor source
        4. Capture from the monitor source (now carrying only our target's audio)
        """
        sink_name = f"{self._sink_name_prefix}_{self._pid}"
        description = f"{self._sink_description_prefix}_{self._pid}"

        # Step 1: Create a null-sink
        try:
            self._null_sink_index = self._pulse.module_load(
                'module-null-sink',
                args=f'sink_name={sink_name} '
                     f'sink_properties=device.description="{description}"'
            )
            self._null_sink_name = sink_name
            logger.debug(f"Loaded null-sink: {sink_name} (index: {self._null_sink_index})")
        except Exception as e:
            raise RuntimeError(f"Failed to load null-sink: {e}") from e

        # Step 2: Move sink-input to the null-sink
        try:
            target_sink = self._find_sink_by_name(sink_name)
            if target_sink is None:
                raise RuntimeError(f"Could not find created null-sink: {sink_name}")

            self._pulse.sink_input_move(self._sink_input_index, target_sink.index)
            logger.debug(f"Moved sink-input #{self._sink_input_index} to null-sink #{target_sink.index}")
        except Exception as e:
            # Clean up null-sink if move failed
            if self._null_sink_index is not None:
                try:
                    self._pulse.module_unload(self._null_sink_index)
                except Exception as unload_err:
                    logger.debug(f"Failed to unload null-sink during cleanup: {unload_err}")
            raise RuntimeError(f"Failed to move sink-input: {e}") from e

        # Step 3: Get the null-sink's monitor source
        try:
            null_sink = self._find_sink_by_name(sink_name)
            if null_sink is None:
                raise RuntimeError(f"Could not find null-sink after creation: {sink_name}")

            monitor_source_name = null_sink.monitor_source_name
            logger.debug(f"Null-sink monitor source: {monitor_source_name}")
        except Exception as e:
            self._cleanup_isolation_modules()
            raise RuntimeError(f"Failed to get monitor source: {e}") from e

        # Step 4: Start capture from the monitor source
        self._stop_event.clear()
        self._capture_thread = threading.Thread(
            target=self._capture_worker,
            args=(monitor_source_name,),
            daemon=True
        )
        self._capture_thread.start()

        logger.info(f"Isolated audio capture started for PID {self._pid}")

    def _capture_worker(self, source_name: str) -> None:
        """
        Worker thread that records ``source_name`` into the audio queue.

        The recorder command is backend-specific (:meth:`_build_capture_command`);
        the read loop, chunking and back-pressure handling are shared.
        """
        try:
            cmd = self._build_capture_command(source_name)
            logger.debug(f"Starting capture: {' '.join(cmd)}")

            # Calculate chunk size for buffering
            chunk_frames = int(self._sample_rate * (self._chunk_duration_ms / 1000.0))
            chunk_bytes = chunk_frames * self._channels * self._sample_width

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=chunk_bytes,  # Buffer one chunk to reduce system calls
            )

            while not self._stop_event.is_set():
                try:
                    if proc.stdout is None:
                        break
                    chunk = proc.stdout.read(chunk_bytes)
                    if not chunk:
                        break

                    if len(chunk) == chunk_bytes:
                        try:
                            self._audio_queue.put_nowait(chunk)
                        except queue.Full:
                            # Drop old frames if queue is full
                            try:
                                self._audio_queue.get_nowait()
                                self._audio_queue.put_nowait(chunk)
                            except Exception:
                                # Best-effort drop; racing consumer emptied it, etc.
                                pass

                except Exception as e:
                    logger.error(f"Error reading audio: {e}")
                    break

            # Clean up
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()

            logger.debug("Capture worker stopped")

        except Exception as e:
            logger.error(f"Capture worker error: {e}")

    def _build_capture_command(self, source_name: str) -> list[str]:
        """Return the recorder command line used to capture ``source_name``."""
        raise NotImplementedError

    def _cleanup_isolation_modules(self) -> None:
        """Clean up modules created for isolation and restore audio routing."""
        if not self._pulse:
            return

        # Restore sink-input to original sink if possible
        if (self._sink_input_index is not None and
            self._original_sink_index is not None and
            self._isolation_mode == "remap"):
            try:
                # Check if sink-input still exists
                sink_input = self._pulse.sink_input_info(self._sink_input_index)
                if sink_input:
                    self._pulse.sink_input_move(self._sink_input_index, self._original_sink_index)
                    logger.debug(
                        f"Restored sink-input #{self._sink_input_index} "
                        f"to original sink #{self._original_sink_index}"
                    )
            except Exception as e:
                logger.debug(f"Could not restore sink-input (may have closed): {e}")

        # Unload null-sink module
        if self._null_sink_index is not None:
            try:
                self._pulse.module_unload(self._null_sink_index)
                logger.debug(f"Unloaded null-sink module #{self._null_sink_index}")
            except Exception as e:
                logger.warning(f"Failed to unload null-sink module: {e}")
            finally:
                self._null_sink_index = None
                self._null_sink_name = None

        # Unload remap-source module if it exists
        if self._remap_source_index is not None:
            try:
                self._pulse.module_unload(self._remap_source_index)
                logger.debug(f"Unloaded remap-source module #{self._remap_source_index}")
            except Exception as e:
                logger.warning(f"Failed to unload remap-source module: {e}")
            finally:
                self._remap_source_index = None
                self._remap_source_name = None

        # Unload loopback module if it exists
        if self._loopback_module_index is not None:
            try:
                self._pulse.module_unload(self._loopback_module_index)
                logger.debug(f"Unloaded loopback module #{self._loopback_module_index}")
            except Exception as e:
                logger.warning(f"Failed to unload loopback module: {e}")
            finally:
                self._loopback_module_index = None

    def stop_capture(self) -> None:
        """Stop capturing audio and clean up modules."""
        self._stop_event.set()

        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)

        self._cleanup_isolation_modules()

        logger.info("Audio capture stopped")

    def read_audio(self, timeout: float = 0.1) -> Optional[bytes]:
        """
        Read audio data from capture buffer.

        Args:
            timeout: Maximum time to wait for data

        Returns:
            PCM audio data as bytes, or None if no data available
        """
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        """Clean up resources and restore audio routing."""
        self.stop_capture()

        if self._pulse:
            self._pulse.close()
            self._pulse = None
            logger.debug("Closed audio server connection")

    def get_format(self) -> dict[str, int | str]:
        """Get audio format information."""
        return {
            'sample_rate': self._sample_rate,
            'channels': self._channels,
            'bits_per_sample': self._bits_per_sample,
        }


class PulseAudioStrategy(_PulseCompatStrategy):
    """
    PulseAudio-based audio capture strategy.

    Uses pulsectl library to interact with PulseAudio server.
    Works on systems with PulseAudio or PipeWire (via pulseaudio-compat layer).
    Captures the isolated monitor source with ``parec`` and, unlike PipeWire,
    falls back to whole-sink monitor capture when isolation fails.
    """

    _client_name = "proctap"
    _server_short = "PulseAudio"
    _connect_success_log = "Connected to PulseAudio server"
    _connect_failure_prefix = "Failed to connect to PulseAudio server"
    _connect_failure_hint = (
        "Make sure PulseAudio or PipeWire (with pulseaudio-compat) is running."
    )
    _sink_name_prefix = "proctap_isolated"
    _sink_description_prefix = "ProcTap_Isolated_PID"
    _capture_error_label = "Failed to start audio capture"

    def __init__(
        self,
        pid: int,
        sample_rate: int = 44100,
        channels: int = 2,
        sample_width: int = 2,
    ) -> None:
        """
        Initialize PulseAudio strategy.

        Args:
            pid: Target process ID
            sample_rate: Sample rate in Hz (default: 44100)
            channels: Number of channels (default: 2 for stereo)
            sample_width: Bytes per sample (default: 2 for 16-bit)
        """
        self._init_common(pid, sample_rate, channels, sample_width)
        self._capture_stream = None
        self._import_pulsectl()

    def _build_capture_command(self, source_name: str) -> list[str]:
        # Use parec (PulseAudio recorder) to capture raw PCM
        return [
            'parec',
            '--device', source_name,
            '--rate', str(self._sample_rate),
            '--channels', str(self._channels),
            '--format', 's16le',  # 16-bit signed little-endian
            '--raw',
        ]

    def _handle_isolation_failure(self, exc: Exception) -> None:
        logger.warning(
            f"Failed to setup isolated capture, falling back to monitor mode: {exc}"
        )
        self._isolation_mode = "monitor"
        self._setup_monitor_capture()

    def _setup_monitor_capture(self) -> None:
        """
        Setup fallback monitor source capture.

        This captures from the entire sink monitor (not isolated).
        Used when isolated capture fails.
        """
        if self._original_sink_index is None:
            raise RuntimeError("Original sink index not set")

        # Get monitor source name
        sink_info = self._pulse.sink_info(self._original_sink_index)
        monitor_source = sink_info.monitor_source_name

        logger.info(
            f"Using monitor capture from sink {self._original_sink_index} "
            f"(monitor: {monitor_source})"
        )
        logger.warning(
            "Monitor mode captures ALL audio from the sink, not just the target process. "
            "This fallback is used when isolated capture fails."
        )

        # Start capture thread
        self._stop_event.clear()
        self._capture_thread = threading.Thread(
            target=self._capture_worker,
            args=(monitor_source,),
            daemon=True
        )
        self._capture_thread.start()

        logger.info("Monitor audio capture started")


class PipeWireStrategy(_PulseCompatStrategy):
    """
    PipeWire-based audio capture strategy using pw-record.

    Uses PipeWire's native command-line tools for audio capture.
    This strategy uses PipeWire's stream capture API via pw-record,
    which provides better integration with modern Linux audio systems.

    Note: Falls back to PulseAudio compatibility layer (pulsectl)
    for stream enumeration and management.
    """

    _client_name = "proctap-pipewire"
    _server_short = "PipeWire"
    _connect_success_log = "Connected to PipeWire (via PulseAudio compatibility layer)"
    _connect_failure_prefix = "Failed to connect to PipeWire"
    _connect_failure_hint = "Make sure PipeWire is running with PulseAudio compatibility."
    _sink_name_prefix = "proctap_pw_isolated"
    _sink_description_prefix = "ProcTap_PipeWire_PID"
    _capture_error_label = "Failed to start PipeWire capture"
    _pulsectl_error_msg = (
        "pulsectl library is required for PipeWire stream management. "
        "Install it with: pip install pulsectl"
    )

    def __init__(
        self,
        pid: int,
        sample_rate: int = 48000,  # PipeWire default is 48kHz
        channels: int = 2,
        sample_width: int = 2,
    ) -> None:
        """
        Initialize PipeWire strategy.

        Args:
            pid: Target process ID
            sample_rate: Sample rate in Hz (default: 48000 for PipeWire)
            channels: Number of channels (default: 2 for stereo)
            sample_width: Bytes per sample (default: 2 for 16-bit)
        """
        self._init_common(pid, sample_rate, channels, sample_width)
        self._recorder_node_name: str = f"proctap_pw_rec_{pid}"
        self._record_proc: Optional[subprocess.Popen[bytes]] = None
        self._stderr_thread: Optional[threading.Thread] = None

        # Required CLIs: pw-link (producer + capture-side port links) and
        # pw-dump (resolve global port ids) are mandatory for the isolation
        # strategy that survives WirePlumber's session policy.
        missing = [c for c in ("pw-record", "pw-link", "pw-dump") if shutil.which(c) is None]
        if missing:
            raise RuntimeError(
                f"PipeWire backend requires {missing} on PATH. "
                "Install 'pipewire' / 'pipewire-utils' (or distro equivalents)."
            )

        # Import pulsectl for stream management (PipeWire has PulseAudio compatibility)
        self._import_pulsectl()

    def _note_stream(self, sink_input: Any) -> None:
        # PipeWire additionally exposes a native stream id we keep for diagnostics.
        self._stream_id = sink_input.proplist.get('pipewire.stream.id')

    def find_process_stream(self, pid: int) -> bool:
        """
        Find sink-input for the target process using PulseAudio compatibility API.

        Args:
            pid: Process ID to find

        Returns:
            True if stream found, False otherwise
        """
        if self._pulse is None:
            raise RuntimeError("Not connected to PipeWire. Call connect() first.")

        try:
            sink_inputs = self._pulse.sink_input_list()
            logger.debug(f"Found {len(sink_inputs)} sink inputs")

            for sink_input in sink_inputs:
                # Check application.process.id property
                process_id_str = sink_input.proplist.get('application.process.id')
                if process_id_str and process_id_str == str(pid):
                    self._sink_input_index = sink_input.index
                    # Try to get PipeWire stream ID
                    self._stream_id = sink_input.proplist.get('pipewire.stream.id')
                    logger.info(
                        f"Found sink-input #{sink_input.index} for PID {pid}: "
                        f"{sink_input.proplist.get('application.name', 'Unknown')}"
                        f" (PW stream ID: {self._stream_id})"
                    )
                    return True

            logger.warning(f"No audio stream found for PID {pid}")
            return False

        except Exception as e:
            logger.error(f"Error finding process stream: {e}")
            return False

    def start_capture(self) -> None:
        """
        Start capturing audio using PipeWire via the pw-link isolation strategy.

        See :meth:`_setup_isolated_capture` for the routing details that make
        this resilient to WirePlumber's session policy (GitHub #48).
        """
        if self._sink_input_index is None:
            raise RuntimeError("No sink-input found. Call find_process_stream() first.")

        try:
            self._setup_isolated_capture()
            logger.info(f"PipeWire isolated capture started for PID {self._pid}")
        except Exception as e:
            # Best-effort cleanup of any partial state so the caller can retry.
            try:
                self._cleanup_isolation_modules()
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(f"Failed to start PipeWire capture: {e}") from e

    def _setup_isolated_capture(self) -> None:
        """Set up isolated capture by adding extra pw-link subscribers.

        This avoids the ``sink_input_move`` approach (which WirePlumber's
        session policy reverts) and the name-targeted ``pw-record`` approach
        (which the session manager redirects to the default sink's monitor
        in multi-sink environments). Instead:

        1. Load ``module-null-sink`` as a dedicated capture target.
        2. Spawn ``pw-record --target=0`` with a unique ``node.name`` so its
           input ports stay unconnected until we explicitly link them.
        3. From a single ``pw-dump`` snapshot, resolve every relevant
           node + port by **global id**, then ``pw-link`` two hops:

           a. Producer side: target process's ``Stream/Output/Audio`` nodes
              → tap null-sink's playback ports. The original route is left
              intact (no ``sink_input_move``), so the user still hears
              audio normally and WirePlumber does not revert anything —
              user-created explicit port links are exempt from session
              policy.
           b. Capture side: tap null-sink's monitor ports → recorder's
              input ports. Without this hop the ``--target=0`` recorder
              stays unconnected and captures silence.
        """
        # Step 1: load the null-sink that will act as our isolation tap.
        sink_name = f"proctap_pw_isolated_{self._pid}"
        try:
            self._null_sink_index = self._pulse.module_load(
                'module-null-sink',
                args=(
                    f'sink_name={sink_name} '
                    f'sink_properties=device.description="ProcTap_PipeWire_PID_{self._pid}"'
                ),
            )
            self._null_sink_name = sink_name
            logger.debug(
                f"Loaded null-sink: {sink_name} (module index: {self._null_sink_index})"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load null-sink: {e}") from e

        # Step 2: spawn the recorder with auto-connect disabled. It will not
        # produce any data until we link the capture-side ports below.
        self._stop_event.clear()
        chunk_frames = int(self._sample_rate * (self._chunk_duration_ms / 1000.0))
        chunk_bytes = chunk_frames * self._channels * self._sample_width
        cmd = [
            "pw-record",
            "--target=0",
            "-P",
            f"node.name={self._recorder_node_name}",
            f"--rate={self._sample_rate}",
            f"--channels={self._channels}",
            "--format=s16",
            "-",
        ]
        logger.debug(f"Starting pw-record: {' '.join(cmd)}")
        try:
            self._record_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=chunk_bytes,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to spawn pw-record: {e}") from e

        # Step 3: wait for both nodes to be visible in pw-dump, then resolve
        # ids and wire the two link hops.
        try:
            self._wire_pw_links()
        except Exception:
            # Cleanup recorder + null-sink and re-raise so start_capture can
            # surface the failure to the caller.
            self._terminate_record_proc()
            raise

        # Step 4: start drain threads on the (now-linked) recorder pipe.
        self._capture_thread = threading.Thread(
            target=self._pcm_drain_worker,
            args=(chunk_bytes,),
            daemon=True,
        )
        self._capture_thread.start()
        self._stderr_thread = threading.Thread(
            target=self._stderr_drain_worker,
            daemon=True,
        )
        self._stderr_thread.start()

    def _wire_pw_links(self) -> None:
        """Resolve node + port ids via ``pw-dump`` and create the two pw-link hops."""
        tap_node_name = self._null_sink_name
        rec_node_name = self._recorder_node_name
        assert tap_node_name is not None

        def probe_nodes() -> Optional[tuple[list[dict[str, Any]], int, int]]:
            dump = _pw_dump_parse(_pw_dump_capture())
            tap_id = _pw_find_node_id_by_name(dump, tap_node_name)
            rec_id = _pw_find_node_id_by_name(dump, rec_node_name)
            if tap_id is None or rec_id is None:
                return None
            return dump, tap_id, rec_id

        resolved = _pw_poll_for(probe_nodes)
        if resolved is None:
            raise RuntimeError(
                "Timed out waiting for tap null-sink / pw-record node to "
                "appear in pw-dump. Is PipeWire running?"
            )
        dump, tap_node_id, rec_node_id = resolved

        # Producer side: target app's output stream(s) -> tap input ports.
        producer_node_ids = _pw_find_stream_node_ids_by_pid(dump, self._pid)
        if not producer_node_ids:
            # The PID's audio stream may not be visible yet (app silent at
            # start). Log and continue — the capture-side link below still
            # delivers audio once the producer attaches. A future refinement
            # could listen to PipeWire registry events and re-link, but the
            # most common case (app already playing) is covered.
            logger.warning(
                f"No Stream/Output/Audio node found for PID {self._pid} in "
                "pw-dump; capture may be silent until the app starts playing"
            )
        else:
            total = 0
            for node_id in producer_node_ids:
                total += _pw_link_nodes(dump, node_id, "out", tap_node_id, "in")
            logger.info(
                f"Linked {total} channel(s) from PID {self._pid} producer node(s) "
                f"{producer_node_ids} to tap null-sink (id={tap_node_id})"
            )

        # Capture side: tap monitor ports -> recorder input ports.
        captured = _pw_link_nodes(dump, tap_node_id, "out", rec_node_id, "in")
        if captured == 0:
            raise RuntimeError(
                "pw-link could not connect tap monitor to pw-record input; "
                "the recorder would capture silence."
            )
        logger.info(
            f"Linked {captured} channel(s) from tap monitor (id={tap_node_id}) "
            f"to pw-record input (id={rec_node_id})"
        )

    def _pcm_drain_worker(self, chunk_bytes: int) -> None:
        """Drain raw PCM from the recorder subprocess into the audio queue."""
        proc = self._record_proc
        if proc is None or proc.stdout is None:
            logger.error("Capture worker started without a running recorder process")
            return
        try:
            while not self._stop_event.is_set():
                chunk = proc.stdout.read(chunk_bytes)
                if not chunk:
                    break
                if len(chunk) != chunk_bytes:
                    # Tail bytes on shutdown — drop rather than feed a short frame.
                    continue
                try:
                    self._audio_queue.put_nowait(chunk)
                except queue.Full:
                    # Bounded queue: drop the oldest frame and try once more.
                    try:
                        self._audio_queue.get_nowait()
                        self._audio_queue.put_nowait(chunk)
                    except (queue.Empty, queue.Full):
                        pass
        except Exception as e:  # noqa: BLE001
            logger.error(f"PipeWire capture worker error: {e}")
        finally:
            logger.debug("PipeWire capture worker stopped")

    def _stderr_drain_worker(self) -> None:
        """Forward ``pw-record`` stderr line-by-line so failures are visible."""
        proc = self._record_proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in iter(proc.stderr.readline, b""):
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.debug(f"pw-record stderr | {text}")
        except Exception:  # noqa: BLE001
            pass

    def _terminate_record_proc(self) -> None:
        """Stop the pw-record subprocess if running."""
        proc = self._record_proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Error terminating pw-record: {e}")
        finally:
            self._record_proc = None

    def stop_capture(self) -> None:
        """Stop capturing audio and tear down the isolation routing."""
        self._stop_event.set()

        # Terminate the recorder first so its stdout closes and the drain
        # thread exits its blocking read.
        self._terminate_record_proc()

        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1.0)

        self._cleanup_isolation_modules()
        logger.info("PipeWire audio capture stopped")

    def _cleanup_isolation_modules(self) -> None:
        """Tear down the tap null-sink.

        Producer-side and capture-side ``pw-link`` connections do not need
        explicit teardown: PipeWire garbage-collects every link attached to
        the null-sink ports as soon as the null-sink module is unloaded,
        and the recorder's ports vanish when its subprocess exits. We never
        moved the original sink-input (the whole point of the pw-link
        approach), so there is nothing to restore on the user's audio path.
        """
        # Make sure the recorder is dead even if stop_capture() did not run.
        self._terminate_record_proc()

        if not self._pulse:
            return

        if self._null_sink_index is not None:
            try:
                self._pulse.module_unload(self._null_sink_index)
                logger.debug("Unloaded null-sink module")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to unload null-sink: {e}")
            finally:
                self._null_sink_index = None
                self._null_sink_name = None

    def read_audio(self, timeout: float = 0.1) -> Optional[bytes]:
        """Read audio data from capture buffer."""
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        """Clean up resources."""
        self.stop_capture()

        if self._pulse:
            self._pulse.close()
            self._pulse = None
            logger.debug("Closed PipeWire connection")

    def get_format(self) -> dict[str, int | str]:
        """Get audio format information."""
        return {
            'sample_rate': self._sample_rate,
            'channels': self._channels,
            'bits_per_sample': self._bits_per_sample,
        }
class PipeWireNativeStrategy(LinuxAudioStrategy):
    """
    Native PipeWire API-based audio capture strategy.

    Uses direct C API bindings via ctypes for ultra-low latency capture (<5ms).
    This is the preferred strategy for modern Linux systems with PipeWire.

    Features:
    - Ultra-low latency (~2-5ms vs ~10-20ms with subprocess-based approaches)
    - Direct PipeWire API access (no subprocess overhead)
    - Per-process audio isolation using node discovery
    - Thread-safe operation
    """

    def __init__(
        self,
        pid: int,
        sample_rate: int = 48000,
        channels: int = 2,
        sample_width: int = 2,
    ) -> None:
        """
        Initialize native PipeWire strategy.

        Args:
            pid: Target process ID
            sample_rate: Sample rate in Hz (default: 48000)
            channels: Number of channels (default: 2 for stereo)
            sample_width: Bytes per sample (default: 2 for 16-bit)

        Raises:
            RuntimeError: If PipeWire native bindings are not available
        """
        if not PIPEWIRE_NATIVE_AVAILABLE or pipewire_native is None:
            raise RuntimeError(
                "PipeWire native bindings not available. "
                "Falling back to subprocess-based strategy."
            )

        self._pid = pid
        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_width = sample_width
        self._bits_per_sample = sample_width * 8

        self._stream_capture: Optional[object] = None  # pipewire_native.PipeWireStreamCapture
        self._target_node_id: Optional[int] = None
        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._is_running = False

    def connect(self) -> None:
        """Connect to PipeWire server."""
        # No explicit connection needed for native API
        # Connection happens when stream is created
        logger.debug("PipeWire native strategy ready")

    def find_process_stream(self, pid: int) -> bool:
        """
        Find audio node for the target process using Registry API.

        Args:
            pid: Process ID to find

        Returns:
            True if node found, False otherwise
        """
        try:
            # Use node discovery to find process nodes
            assert pipewire_native is not None
            discovery = pipewire_native.PipeWireNodeDiscovery()
            nodes = discovery.find_nodes_by_pid(pid, timeout_ms=2000)

            if not nodes:
                logger.warning(f"No PipeWire nodes found for PID {pid}")
                return False

            # Use the first found node
            self._target_node_id, props = nodes[0]
            node_name = props.get('node.name', 'unknown')
            logger.info(
                f"Found PipeWire node {self._target_node_id} for PID {pid}: {node_name}"
            )
            return True

        except Exception as e:
            logger.error(f"Error finding process stream: {e}")
            return False

    def start_capture(self) -> None:
        """Start capturing audio from the target node."""
        if self._is_running:
            return

        assert pipewire_native is not None

        try:
            # Create audio callback
            def on_audio_data(data: bytes, frames: int) -> None:
                try:
                    self._audio_queue.put_nowait(data)
                except queue.Full:
                    # Drop frames if queue is full
                    pass

            # Create stream capture
            self._stream_capture = pipewire_native.PipeWireStreamCapture(
                sample_rate=self._sample_rate,
                channels=self._channels,
                on_data=on_audio_data
            )

            # Start capture (in background thread)
            target_id = self._target_node_id if self._target_node_id else 0xFFFFFFFF
            self._stream_capture.start(target_id=target_id, blocking=False)  # type: ignore

            self._is_running = True
            logger.info("PipeWire native capture started")

        except Exception as e:
            self._is_running = False
            raise RuntimeError(f"Failed to start PipeWire native capture: {e}") from e

    def stop_capture(self) -> None:
        """Stop capturing audio."""
        if not self._is_running:
            return

        try:
            if self._stream_capture:
                self._stream_capture.stop()  # type: ignore
                self._stream_capture = None

            self._is_running = False
            logger.info("PipeWire native capture stopped")

        except Exception as e:
            logger.error(f"Error stopping capture: {e}")

    def read_audio(self, timeout: float = 0.1) -> Optional[bytes]:
        """
        Read audio data from capture buffer.

        Args:
            timeout: Maximum time to wait for data

        Returns:
            PCM audio data as bytes, or None if no data available
        """
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        """Clean up resources."""
        self.stop_capture()
        logger.debug("Closed PipeWire native strategy")

    def get_format(self) -> dict[str, int | str]:
        """Get audio format information."""
        return {
            'sample_rate': self._sample_rate,
            'channels': self._channels,
            'bits_per_sample': self._bits_per_sample,
        }


class LinuxBackend(AudioBackend):
    """
    Linux implementation for process-specific audio capture.

    🧪 EXPERIMENTAL: This backend supports both PulseAudio and PipeWire.

    Features:
    - True per-process audio isolation using null-sink strategy
    - Automatic fallback to monitor capture if isolation fails
    - PID-based stream identification
    - Automatic detection of PipeWire vs PulseAudio
    - Native PipeWire support via pw-record (v0.3.0+)
    - PulseAudio support via pulsectl + parec

    Audio Server Support:
    - **PipeWire** (Recommended for modern Linux): Uses pw-record for native capture
    - **PulseAudio** (Traditional): Uses parec for capture
    - **Auto-detection**: Automatically selects the best backend for your system

    Isolation Strategy:
    The backend attempts to create an isolated capture using:
    1. Creating a temporary null-sink for the target process
    2. Moving the process's sink-input to the null-sink
    3. Capturing from the null-sink's monitor (which contains ONLY target process audio)
    4. Automatically restoring the original audio routing when done

    If isolation fails, falls back to capturing from the original sink monitor
    (which may include audio from other applications).

    Requirements:
    - Linux with PulseAudio or PipeWire
    - pulsectl library: pip install pulsectl
    - For PulseAudio: parec command (pulseaudio-utils package)
    - For PipeWire: pw-record command (pipewire-utils package)
    - module-null-sink (standard in both PulseAudio and PipeWire)

    Limitations:
    - Requires the target process to be actively playing audio
    - Isolation requires moving sink-input, which may cause brief audio interruption
    - Some applications may not work well with sink changes

    Latency Characteristics:
    - End-to-end latency: ~10-20ms (suitable for real-time transcription)
    - Components: command-line tool (~5-10ms) + subprocess overhead (~2-5ms) + buffering (~5-10ms)
    - Optimizations: unbuffered I/O, small chunk size (10ms), reduced queue depth
    - For ultra-low latency (<5ms), native PipeWire API bindings would be required
    """

    def __init__(
        self,
        pid: int,
        sample_rate: int = 44100,
        channels: int = 2,
        sample_width: int = 2,
        engine: str = "auto",
        resample_quality: str = 'best',
    ) -> None:
        """
        Initialize Linux backend.

        This backend always converts audio to the standard format:
        - 48000 Hz
        - 2 channels (stereo)
        - float32 (IEEE 754, normalized to [-1.0, 1.0])

        Args:
            pid: Process ID to capture audio from
            sample_rate: Native sample rate in Hz (default: 44100)
            channels: Native number of channels (default: 2 for stereo)
            sample_width: Native bytes per sample (default: 2 for 16-bit)
            engine: Audio engine to use: "auto", "pulse", "pipewire", or "pipewire-native"
                   - "auto": Auto-detect (prefers native PipeWire if available)
                   - "pipewire-native": Native PipeWire API (ultra-low latency)
                   - "pipewire": PipeWire via subprocess (pw-record)
                   - "pulse": PulseAudio via subprocess (parec)
            resample_quality: Resampling quality mode ('best', 'medium', 'fast')
        """
        super().__init__(pid)

        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_width = sample_width
        self._engine = engine
        self._is_running = False

        # Auto-detect audio server if engine is "auto"
        detected_engine = engine
        if engine == "auto":
            server_type = detect_audio_server()
            if server_type == "pipewire":
                # Prefer native PipeWire if available
                if PIPEWIRE_NATIVE_AVAILABLE:
                    detected_engine = "pipewire-native"
                    logger.info("Auto-detected PipeWire with native API support")
                else:
                    detected_engine = "pipewire"
                    logger.info("Auto-detected PipeWire audio server (subprocess mode)")
            elif server_type == "pulseaudio":
                detected_engine = "pulse"
                logger.info("Auto-detected PulseAudio audio server")
            else:
                # Default to PulseAudio if detection fails
                detected_engine = "pulse"
                logger.warning(
                    "Could not detect audio server type, defaulting to PulseAudio"
                )

        # Select strategy by walking the ordered fallback chain for this engine.
        self._strategy: LinuxAudioStrategy = self._create_strategy(
            detected_engine, pid, sample_rate, channels, sample_width
        )

        # Setup audio format converter
        # Linux backends always capture as int16, so we need to convert to float32
        src_format = SampleFormat.INT16
        self._converter = AudioConverter(
            src_rate=sample_rate,
            src_channels=channels,
            src_width=sample_width,
            src_format=src_format,
            dst_rate=STANDARD_SAMPLE_RATE,
            dst_channels=STANDARD_CHANNELS,
            dst_width=STANDARD_SAMPLE_WIDTH,
            dst_format=SampleFormat.FLOAT32,
            resample_quality=resample_quality,  # type: ignore[arg-type]
        )
        logger.info(
            f"Audio format conversion enabled: "
            f"{sample_rate}Hz/{channels}ch/{src_format} -> "
            f"{STANDARD_SAMPLE_RATE}Hz/{STANDARD_CHANNELS}ch/float32 "
            f"(quality={resample_quality})"
        )

    def _get_strategy_chain(self, engine: str) -> list[type[LinuxAudioStrategy]]:
        """
        Return the ordered strategy classes to try for ``engine``.

        Earlier entries are preferred; later entries are fallbacks used when an
        earlier strategy cannot initialize on this system.

        Raises:
            ValueError: If ``engine`` is not a recognised value.
        """
        chains: dict[str, list[type[LinuxAudioStrategy]]] = {
            "pipewire-native": [PipeWireNativeStrategy, PipeWireStrategy, PulseAudioStrategy],
            "pipewire": [PipeWireStrategy, PulseAudioStrategy],
            "pulse": [PulseAudioStrategy],
        }
        try:
            return chains[engine]
        except KeyError:
            raise ValueError(
                f"Unknown engine: {engine}. "
                f"Use 'auto', 'pulse', 'pipewire', or 'pipewire-native'"
            )

    def _create_strategy(
        self,
        engine: str,
        pid: int,
        sample_rate: int,
        channels: int,
        sample_width: int,
    ) -> LinuxAudioStrategy:
        """
        Instantiate the first strategy in the chain that initializes successfully.

        Raises:
            ValueError: If ``engine`` is unknown.
            RuntimeError: If every strategy in the chain fails to initialize.
        """
        last_error: Optional[Exception] = None
        for strategy_class in self._get_strategy_chain(engine):
            try:
                strategy = strategy_class(
                    pid=pid,
                    sample_rate=sample_rate,
                    channels=channels,
                    sample_width=sample_width,
                )
                logger.info(
                    f"Initialized LinuxBackend for PID {pid} "
                    f"(strategy: {strategy_class.__name__})"
                )
                return strategy
            except RuntimeError as e:
                last_error = e
                logger.warning(f"{strategy_class.__name__} initialization failed: {e}")

        raise RuntimeError(
            f"No audio capture strategy could be initialized for engine '{engine}'. "
            f"Last error: {last_error}"
        ) from last_error

    def start(self) -> None:
        """
        Start audio capture from the target process.

        Raises:
            RuntimeError: If capture fails to start
        """
        if self._is_running:
            logger.warning("Audio capture is already running")
            return

        try:
            # Connect to audio server
            self._strategy.connect()

            # Find process stream
            if not self._strategy.find_process_stream(self._pid):
                raise RuntimeError(
                    f"No audio stream found for PID {self._pid}. "
                    "Make sure the process is actively playing audio."
                )

            # Start capture
            self._strategy.start_capture()
            self._is_running = True

            logger.info(f"Started audio capture for PID {self._pid}")

        except Exception as e:
            self._is_running = False
            raise RuntimeError(f"Failed to start audio capture: {e}") from e

    def stop(self) -> None:
        """Stop audio capture."""
        if not self._is_running:
            return

        try:
            self._strategy.stop_capture()
            self._is_running = False
            logger.info("Stopped audio capture")
        except Exception as e:
            logger.error(f"Error stopping capture: {e}")

    def read(self) -> Optional[bytes]:
        """
        Read audio data from the capture buffer.

        Returns:
            PCM audio data as bytes in standard format (48kHz/2ch/float32),
            or None if no data is available or the chunk could not be converted.
            See AudioBackend.read for the shared sentinel convention.
        """
        if not self._is_running:
            return None

        data = self._strategy.read_audio(timeout=0.1)

        # Apply format conversion
        if self._converter and data:
            try:
                data = self._converter.convert(data)
            except Exception as e:
                # Recoverable: log and report "no usable data" (None), never b''.
                logger.error(f"Error converting audio format: {e}")
                return None

        return data

    def get_format(self) -> dict[str, int | str]:
        """
        Get audio format information (always returns standard format).

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

    def close(self) -> None:
        """Clean up resources."""
        self.stop()
        if self._strategy:
            self._strategy.close()

    def __del__(self) -> None:
        """Destructor to ensure cleanup."""
        try:
            self.close()
        except Exception:
            # Suppress cleanup errors in the destructor, but let BaseException
            # (e.g. KeyboardInterrupt, SystemExit) propagate.
            pass


# Development notes:
#
# Implementation status (v0.3.0+):
# ✅ PID-based stream identification via application.process.id property
# ✅ Per-process audio isolation using null-sink strategy
# ✅ Automatic fallback to monitor capture
# ✅ Proper cleanup and audio routing restoration
# ✅ Native PipeWire support via pw-record (PipeWireStrategy class)
# ✅ Automatic audio server detection (PipeWire vs PulseAudio)
# ✅ Graceful fallback from PipeWire to PulseAudio
#
# Isolation strategy (both PulseAudio and PipeWire):
# 1. Create temporary null-sink for target process
# 2. Move sink-input to null-sink (isolates audio stream)
# 3. Capture from null-sink monitor (contains ONLY target process audio)
#    - PulseAudio: Uses parec command
#    - PipeWire: Uses pw-record command (native)
# 4. Restore original routing on cleanup
#
# This provides true per-process isolation without cross-app contamination.
#
# Latency Characteristics:
# - Current implementation: ~10-20ms end-to-end latency
#   * Command-line tools (parec/pw-record): ~5-10ms
#   * Python subprocess overhead: ~2-5ms
#   * Queue buffering: ~5-10ms (configurable via chunk_duration_ms)
# - Optimizations applied:
#   * Unbuffered subprocess I/O (bufsize=0)
#   * Small chunk size (10ms default, configurable)
#   * Reduced queue size (50 chunks = ~500ms max buffer)
#
# Native PipeWire API Implementation:
# - 🚧 In development: pipewire_native.py (ctypes bindings to libpipewire-0.3)
# - Target latency: ~2-5ms (vs current ~10-20ms)
# - Status (as of v0.3.0):
#   * ✅ Core API bindings (pw_init, pw_main_loop, pw_context, pw_stream)
#   * ✅ Stream capture framework (pw_stream_new_simple, dequeue/queue buffers)
#   * ⚠️  Incomplete: SPA POD format parameters, process node detection
#   * 🔜 Integration with LinuxBackend as opt-in feature
# - See: src/proctap/backends/pipewire_native.py
#
# Future improvements:
# 1. Complete native PipeWire implementation (SPA format params, node detection)
# 2. Improve error handling for edge cases (e.g., app closes during capture)
# 3. Add support for dynamic format negotiation
# 4. Add option to disable isolation (for low-overhead monitoring)
# 5. Support capturing from source-outputs (microphone inputs)
# 6. Configurable buffer sizes for latency vs stability tradeoff
#
# References:
# - PulseAudio module-null-sink: https://www.freedesktop.org/wiki/Software/PulseAudio/Documentation/User/Modules/#module-null-sink
# - pulsectl documentation: https://github.com/mk-fg/python-pulse-control
# - PipeWire PulseAudio compatibility: https://gitlab.freedesktop.org/pipewire/pipewire/-/wikis/Config-PulseAudio
# - PipeWire pw-record: https://docs.pipewire.org/page_man_pw-record_1.html
