"""
PipeWire native API bindings using ctypes.

This module provides low-level ctypes bindings to the PipeWire C API,
enabling ultra-low latency audio capture without subprocess overhead.

Requirements:
- libpipewire-0.3.so (PipeWire library)
- PipeWire 0.3.x or later

Latency: ~2-5ms (vs ~10-20ms with pw-record subprocess)
"""

from __future__ import annotations

import ctypes
import ctypes.util
from typing import Optional, Callable
from enum import IntEnum
import logging
import errno
import os
import threading

logger = logging.getLogger(__name__)

# Type aliases
AudioCallback = Callable[[bytes, int], None]


class PipeWireError(Exception):
    """Exception raised for PipeWire API errors."""
    pass


class PipeWireInitError(PipeWireError):
    """Exception raised when PipeWire initialization fails."""
    pass


class PipeWireStreamError(PipeWireError):
    """Exception raised for stream-related errors."""
    pass


class PipeWireRegistryError(PipeWireError):
    """Exception raised for registry-related errors."""
    pass


def _get_error_string(error_code: int) -> str:
    """
    Get human-readable error string from error code.

    Args:
        error_code: Error code (usually negative errno value)

    Returns:
        Human-readable error description
    """
    if error_code == 0:
        return "Success"

    # PipeWire returns negative errno values
    abs_code = abs(error_code)

    error_names = {
        errno.EPERM: "Operation not permitted",
        errno.ENOENT: "No such file or directory",
        errno.ESRCH: "No such process",
        errno.EINTR: "Interrupted system call",
        errno.EIO: "I/O error",
        errno.ENXIO: "No such device or address",
        errno.EBADF: "Bad file descriptor",
        errno.EAGAIN: "Resource temporarily unavailable",
        errno.ENOMEM: "Out of memory",
        errno.EACCES: "Permission denied",
        errno.EFAULT: "Bad address",
        errno.EBUSY: "Device or resource busy",
        errno.EEXIST: "File exists",
        errno.ENODEV: "No such device",
        errno.EINVAL: "Invalid argument",
        errno.ENOSPC: "No space left on device",
        errno.EPIPE: "Broken pipe",
    }

    error_msg = error_names.get(abs_code, f"Unknown error {abs_code}")
    return f"[errno {abs_code}] {error_msg}"


# Load PipeWire library
def _load_pipewire_library() -> ctypes.CDLL:
    """
    Load the PipeWire shared library.

    Returns:
        ctypes.CDLL: Loaded PipeWire library

    Raises:
        PipeWireError: If library cannot be loaded
    """
    lib_name = ctypes.util.find_library('pipewire-0.3')
    if lib_name is None:
        raise PipeWireError(
            "libpipewire-0.3.so not found. "
            "Install PipeWire development package (e.g., libpipewire-0.3-dev)"
        )

    try:
        lib = ctypes.CDLL(lib_name)
        logger.debug(f"Loaded PipeWire library: {lib_name}")
        return lib
    except OSError as e:
        raise PipeWireError(f"Failed to load PipeWire library: {e}") from e


# Attempt to load library (will raise PipeWireError if not available)
_pw_lib: Optional[ctypes.CDLL]
try:
    _pw_lib = _load_pipewire_library()
except PipeWireError as e:
    logger.warning(f"PipeWire native bindings unavailable: {e}")
    _pw_lib = None


# PipeWire enums and constants
class PWDirection(IntEnum):
    """Stream direction."""
    INPUT = 1   # Consuming data (capture/recording)
    OUTPUT = 2  # Producing data (playback)


class PWStreamState(IntEnum):
    """Stream state."""
    ERROR = -1
    UNCONNECTED = 0
    CONNECTING = 1
    PAUSED = 2
    STREAMING = 3


# PipeWire structure definitions (opaque pointers)
class pw_main_loop(ctypes.Structure):
    """Main loop (opaque)."""
    pass


class pw_context(ctypes.Structure):
    """Context (opaque)."""
    pass


class pw_core(ctypes.Structure):
    """Core (opaque)."""
    pass


class pw_stream(ctypes.Structure):
    """Stream (opaque)."""
    pass


class pw_properties(ctypes.Structure):
    """Properties (opaque)."""
    pass


class pw_registry(ctypes.Structure):
    """Registry (opaque)."""
    pass


class pw_proxy(ctypes.Structure):
    """Proxy (opaque)."""
    pass


class spa_pod(ctypes.Structure):
    """SPA POD (opaque)."""
    pass


class pw_buffer(ctypes.Structure):
    """Buffer structure."""
    _fields_ = [
        ("buffer", ctypes.c_void_p),  # struct spa_buffer *
        ("user_data", ctypes.c_void_p),
        ("size", ctypes.c_uint64),
        ("requested", ctypes.c_uint64),
    ]


class spa_buffer(ctypes.Structure):
    """SPA buffer structure."""
    _fields_ = [
        ("n_metas", ctypes.c_uint32),
        ("n_datas", ctypes.c_uint32),
        ("metas", ctypes.c_void_p),   # struct spa_meta *
        ("datas", ctypes.c_void_p),   # struct spa_data *
    ]


class spa_data(ctypes.Structure):
    """SPA data structure."""
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("fd", ctypes.c_int64),
        ("mapoffset", ctypes.c_uint32),
        ("maxsize", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
        ("chunk", ctypes.c_void_p),  # struct spa_chunk *
    ]


class spa_chunk(ctypes.Structure):
    """SPA chunk structure."""
    _fields_ = [
        ("offset", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("stride", ctypes.c_int32),
        ("flags", ctypes.c_int32),
    ]


# SPA POD structures for audio format parameters
class spa_pod_header(ctypes.Structure):
    """SPA POD header."""
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
    ]


class spa_pod_body(ctypes.Structure):
    """SPA POD body (base structure)."""
    _fields_ = [
        ("value", ctypes.c_void_p),
    ]


class spa_pod_builder_state(ctypes.Structure):
    """SPA POD builder state."""
    _fields_ = [
        ("offset", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("frame", ctypes.c_void_p),
    ]


class spa_pod_builder(ctypes.Structure):
    """SPA POD builder."""
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
        ("_padding", ctypes.c_uint32),
        ("state", spa_pod_builder_state),
        ("callbacks", ctypes.c_void_p),
    ]


class spa_pod_frame(ctypes.Structure):
    """SPA POD frame."""
    _fields_ = [
        ("pod", ctypes.c_void_p),  # struct spa_pod *
        ("parent", ctypes.c_void_p),  # struct spa_pod_frame *
        ("flags", ctypes.c_uint32),
        ("offset", ctypes.c_uint32),
    ]


# SPA type IDs (from spa/utils/type.h)
class SPAType(IntEnum):
    """SPA type IDs."""
    NONE = 0
    BOOL = 1
    ID = 2
    INT = 3
    LONG = 4
    FLOAT = 5
    DOUBLE = 6
    STRING = 7
    BYTES = 8
    RECTANGLE = 9
    FRACTION = 10
    BITMAP = 11
    ARRAY = 12
    STRUCT = 13
    OBJECT = 14
    SEQUENCE = 15
    POINTER = 16
    FD = 17
    CHOICE = 18
    POD = 19


# SPA format IDs (from spa/param/format.h)
class SPAParamType(IntEnum):
    """SPA parameter type IDs."""
    Invalid = 0
    PropInfo = 1
    Props = 2
    EnumFormat = 3
    Format = 4
    Buffers = 5
    Meta = 6
    IO = 7
    Profile = 8
    PortConfig = 9
    Route = 10
    Control = 11
    Latency = 12
    ProcessLatency = 13


# SPA audio format IDs (from spa/param/audio/format.h)
class SPAAudioFormat(IntEnum):
    """SPA audio format IDs."""
    UNKNOWN = 0
    ENCODED = 1
    S8 = 2
    U8 = 3
    S16_LE = 4
    S16_BE = 5
    U16_LE = 6
    U16_BE = 7
    S24_32_LE = 8
    S24_32_BE = 9
    U24_32_LE = 10
    U24_32_BE = 11
    S24_LE = 12
    S24_BE = 13
    U24_LE = 14
    U24_BE = 15
    S32_LE = 16
    S32_BE = 17
    U32_LE = 18
    U32_BE = 19
    F32_LE = 20
    F32_BE = 21
    F64_LE = 22
    F64_BE = 23


# SPA format property IDs
SPA_FORMAT_mediaType = 0x00001
SPA_FORMAT_mediaSubtype = 0x00002
SPA_FORMAT_AUDIO_format = 0x10001
SPA_FORMAT_AUDIO_rate = 0x10003
SPA_FORMAT_AUDIO_channels = 0x10004

# SPA media types
SPA_MEDIA_TYPE_audio = 1

# SPA media subtypes
SPA_MEDIA_SUBTYPE_raw = 1


class pw_stream_events(ctypes.Structure):
    """Stream events callbacks."""
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("destroy", ctypes.c_void_p),
        ("state_changed", ctypes.c_void_p),
        ("control_info", ctypes.c_void_p),
        ("io_changed", ctypes.c_void_p),
        ("param_changed", ctypes.c_void_p),
        ("add_buffer", ctypes.c_void_p),
        ("remove_buffer", ctypes.c_void_p),
        ("process", ctypes.c_void_p),  # Process callback
        ("drained", ctypes.c_void_p),
    ]


class spa_dict_item(ctypes.Structure):
    """SPA dictionary item."""
    _fields_ = [
        ("key", ctypes.c_char_p),
        ("value", ctypes.c_char_p),
    ]


class spa_dict(ctypes.Structure):
    """SPA dictionary."""
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("n_items", ctypes.c_uint32),
        ("items", ctypes.POINTER(spa_dict_item)),
    ]


class spa_hook(ctypes.Structure):
    """SPA hook for event listeners."""
    pass

spa_hook._fields_ = [
    ("link", ctypes.c_void_p),  # struct spa_list
    ("cb", ctypes.c_void_p),    # callbacks
    ("removed", ctypes.c_void_p),  # removed callback
    ("priv", ctypes.c_void_p),  # private data
]


class pw_registry_events(ctypes.Structure):
    """Registry events callbacks."""
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("global_", ctypes.c_void_p),  # global callback (renamed from 'global')
        ("global_remove", ctypes.c_void_p),
    ]


# Function pointer types
PROCESS_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
STATE_CHANGED_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,  # user_data
    ctypes.c_int,     # old state
    ctypes.c_int,     # new state
    ctypes.c_char_p   # error
)
REGISTRY_GLOBAL_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,  # user_data
    ctypes.c_uint32,  # id
    ctypes.c_uint32,  # permissions
    ctypes.c_char_p,  # type
    ctypes.c_uint32,  # version
    ctypes.POINTER(spa_dict)  # props
)


# Define PipeWire C API functions
if _pw_lib is not None:
    # Initialization
    _pw_lib.pw_init.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.POINTER(ctypes.c_char_p))]
    _pw_lib.pw_init.restype = None

    _pw_lib.pw_deinit.argtypes = []
    _pw_lib.pw_deinit.restype = None

    # Main loop
    _pw_lib.pw_main_loop_new.argtypes = [ctypes.c_void_p]  # const struct spa_dict *props
    _pw_lib.pw_main_loop_new.restype = ctypes.POINTER(pw_main_loop)

    _pw_lib.pw_main_loop_destroy.argtypes = [ctypes.POINTER(pw_main_loop)]
    _pw_lib.pw_main_loop_destroy.restype = None

    _pw_lib.pw_main_loop_get_loop.argtypes = [ctypes.POINTER(pw_main_loop)]
    _pw_lib.pw_main_loop_get_loop.restype = ctypes.c_void_p  # struct pw_loop *

    _pw_lib.pw_main_loop_run.argtypes = [ctypes.POINTER(pw_main_loop)]
    _pw_lib.pw_main_loop_run.restype = ctypes.c_int

    _pw_lib.pw_main_loop_quit.argtypes = [ctypes.POINTER(pw_main_loop)]
    _pw_lib.pw_main_loop_quit.restype = ctypes.c_int

    # Context
    _pw_lib.pw_context_new.argtypes = [
        ctypes.c_void_p,  # struct pw_loop *
        ctypes.c_void_p,  # struct pw_properties *
        ctypes.c_size_t   # user_data_size
    ]
    _pw_lib.pw_context_new.restype = ctypes.POINTER(pw_context)

    _pw_lib.pw_context_destroy.argtypes = [ctypes.POINTER(pw_context)]
    _pw_lib.pw_context_destroy.restype = None

    _pw_lib.pw_context_connect.argtypes = [
        ctypes.POINTER(pw_context),
        ctypes.c_void_p,  # struct pw_properties *
        ctypes.c_size_t   # user_data_size
    ]
    _pw_lib.pw_context_connect.restype = ctypes.POINTER(pw_core)

    # Core (for registry)
    _pw_lib.pw_core_get_registry.argtypes = [
        ctypes.POINTER(pw_core),
        ctypes.c_uint32,  # version
        ctypes.c_size_t   # user_data_size
    ]
    _pw_lib.pw_core_get_registry.restype = ctypes.POINTER(pw_registry)

    # Registry
    _pw_lib.pw_registry_add_listener.argtypes = [
        ctypes.POINTER(pw_registry),
        ctypes.POINTER(spa_hook),
        ctypes.POINTER(pw_registry_events),
        ctypes.c_void_p   # user_data
    ]
    _pw_lib.pw_registry_add_listener.restype = ctypes.c_int

    _pw_lib.pw_registry_destroy.argtypes = [ctypes.POINTER(pw_registry)]
    _pw_lib.pw_registry_destroy.restype = None

    # Proxy (for binding to objects)
    _pw_lib.pw_registry_bind.argtypes = [
        ctypes.POINTER(pw_registry),
        ctypes.c_uint32,  # id
        ctypes.c_char_p,  # type
        ctypes.c_uint32,  # version
        ctypes.c_size_t   # user_data_size
    ]
    _pw_lib.pw_registry_bind.restype = ctypes.POINTER(pw_proxy)

    _pw_lib.pw_proxy_destroy.argtypes = [ctypes.POINTER(pw_proxy)]
    _pw_lib.pw_proxy_destroy.restype = None

    # Properties
    _pw_lib.pw_properties_new.argtypes = [ctypes.c_char_p, ctypes.c_char_p]  # Varargs, NULL-terminated
    _pw_lib.pw_properties_new.restype = ctypes.POINTER(pw_properties)

    _pw_lib.pw_properties_free.argtypes = [ctypes.POINTER(pw_properties)]
    _pw_lib.pw_properties_free.restype = None

    # Stream
    _pw_lib.pw_stream_new_simple.argtypes = [
        ctypes.c_void_p,  # struct pw_loop *
        ctypes.c_char_p,  # name
        ctypes.c_void_p,  # struct pw_properties *
        ctypes.POINTER(pw_stream_events),  # events
        ctypes.c_void_p   # user_data
    ]
    _pw_lib.pw_stream_new_simple.restype = ctypes.POINTER(pw_stream)

    _pw_lib.pw_stream_destroy.argtypes = [ctypes.POINTER(pw_stream)]
    _pw_lib.pw_stream_destroy.restype = None

    _pw_lib.pw_stream_connect.argtypes = [
        ctypes.POINTER(pw_stream),
        ctypes.c_int,     # direction (pw_direction)
        ctypes.c_uint32,  # target_id
        ctypes.c_int,     # flags
        ctypes.POINTER(ctypes.c_void_p),  # params
        ctypes.c_uint32   # n_params
    ]
    _pw_lib.pw_stream_connect.restype = ctypes.c_int

    _pw_lib.pw_stream_dequeue_buffer.argtypes = [ctypes.POINTER(pw_stream)]
    _pw_lib.pw_stream_dequeue_buffer.restype = ctypes.POINTER(pw_buffer)

    _pw_lib.pw_stream_queue_buffer.argtypes = [
        ctypes.POINTER(pw_stream),
        ctypes.POINTER(pw_buffer)
    ]
    _pw_lib.pw_stream_queue_buffer.restype = ctypes.c_int

    _pw_lib.pw_stream_get_state.argtypes = [
        ctypes.POINTER(pw_stream),
        ctypes.POINTER(ctypes.c_char_p)  # error (optional)
    ]
    _pw_lib.pw_stream_get_state.restype = ctypes.c_int

    # SPA POD builder functions
    _pw_lib.spa_pod_builder_init.argtypes = [
        ctypes.POINTER(spa_pod_builder),
        ctypes.c_void_p,  # data buffer
        ctypes.c_uint32   # size
    ]
    _pw_lib.spa_pod_builder_init.restype = None

    _pw_lib.spa_pod_builder_push_object.argtypes = [
        ctypes.POINTER(spa_pod_builder),
        ctypes.POINTER(spa_pod_frame),
        ctypes.c_uint32,  # type
        ctypes.c_uint32   # id
    ]
    _pw_lib.spa_pod_builder_push_object.restype = ctypes.POINTER(spa_pod)

    _pw_lib.spa_pod_builder_add.argtypes = [
        ctypes.POINTER(spa_pod_builder),
        ctypes.c_uint32,  # key
        ctypes.c_uint32,  # type
        # Varargs follow
    ]
    _pw_lib.spa_pod_builder_add.restype = ctypes.c_int

    _pw_lib.spa_pod_builder_pop.argtypes = [
        ctypes.POINTER(spa_pod_builder),
        ctypes.POINTER(spa_pod_frame)
    ]
    _pw_lib.spa_pod_builder_pop.restype = ctypes.POINTER(spa_pod)


class PipeWireNative:
    """
    Native PipeWire API wrapper using ctypes.

    Provides low-level access to PipeWire stream capture with minimal overhead.
    """

    def __init__(self):
        """Initialize PipeWire native wrapper."""
        if _pw_lib is None:
            raise PipeWireError("PipeWire library not available")

        self._initialized = False
        self._main_loop: Optional[ctypes.POINTER(pw_main_loop)] = None
        self._context: Optional[ctypes.POINTER(pw_context)] = None
        self._core: Optional[ctypes.POINTER(pw_core)] = None
        self._stream: Optional[ctypes.POINTER(pw_stream)] = None
        self._process_callback: Optional[PROCESS_CALLBACK] = None
        self._user_callback: Optional[AudioCallback] = None

    def init(self) -> None:
        """
        Initialize PipeWire.

        Raises:
            PipeWireInitError: If initialization fails
        """
        if self._initialized:
            return

        try:
            _pw_lib.pw_init(None, None)
            self._initialized = True
            logger.debug("PipeWire initialized")
        except Exception as e:
            raise PipeWireInitError(f"Failed to initialize PipeWire: {e}") from e

    def deinit(self) -> None:
        """Deinitialize PipeWire."""
        if not self._initialized:
            return

        _pw_lib.pw_deinit()
        self._initialized = False
        logger.debug("PipeWire deinitialized")

    def create_main_loop(self) -> None:
        """
        Create PipeWire main loop.

        Raises:
            PipeWireInitError: If main loop creation fails
        """
        try:
            self._main_loop = _pw_lib.pw_main_loop_new(None)
            if not self._main_loop:
                raise PipeWireInitError(
                    "Failed to create main loop: pw_main_loop_new returned NULL. "
                    "This may indicate insufficient memory or system resources."
                )
            logger.debug("Main loop created")
        except PipeWireError:
            raise
        except Exception as e:
            raise PipeWireInitError(f"Unexpected error creating main loop: {e}") from e

    def destroy_main_loop(self) -> None:
        """Destroy main loop."""
        if self._main_loop:
            _pw_lib.pw_main_loop_destroy(self._main_loop)
            self._main_loop = None
            logger.debug("Main loop destroyed")

    def create_context(self) -> None:
        """
        Create PipeWire context.

        Raises:
            PipeWireInitError: If context creation fails
        """
        if not self._main_loop:
            raise PipeWireInitError(
                "Cannot create context: main loop not created. "
                "Call create_main_loop() first."
            )

        try:
            loop = _pw_lib.pw_main_loop_get_loop(self._main_loop)
            if not loop:
                raise PipeWireInitError("Failed to get loop from main loop")

            self._context = _pw_lib.pw_context_new(loop, None, 0)
            if not self._context:
                raise PipeWireInitError(
                    "Failed to create context: pw_context_new returned NULL. "
                    "This may indicate PipeWire daemon is not running or "
                    "insufficient permissions."
                )
            logger.debug("Context created")
        except PipeWireError:
            raise
        except Exception as e:
            raise PipeWireInitError(f"Unexpected error creating context: {e}") from e

    def destroy_context(self) -> None:
        """Destroy context."""
        if self._context:
            _pw_lib.pw_context_destroy(self._context)
            self._context = None
            logger.debug("Context destroyed")

    def connect_core(self) -> None:
        """
        Connect to PipeWire core.

        Raises:
            PipeWireInitError: If core connection fails
        """
        if not self._context:
            raise PipeWireInitError(
                "Cannot connect to core: context not created. "
                "Call create_context() first."
            )

        try:
            self._core = _pw_lib.pw_context_connect(self._context, None, 0)
            if not self._core:
                raise PipeWireInitError(
                    "Failed to connect to PipeWire core. "
                    "Possible causes:\n"
                    "  - PipeWire daemon is not running (check 'systemctl --user status pipewire')\n"
                    "  - Insufficient permissions\n"
                    "  - PipeWire socket not accessible"
                )
            logger.debug("Connected to core")
        except PipeWireError:
            raise
        except Exception as e:
            raise PipeWireInitError(f"Unexpected error connecting to core: {e}") from e

    def cleanup(self) -> None:
        """
        Clean up all PipeWire resources.

        Note: This method does not raise exceptions to ensure cleanup always completes.
        """
        try:
            if self._stream:
                _pw_lib.pw_stream_destroy(self._stream)
                self._stream = None
        except Exception as e:
            logger.warning(f"Error destroying stream during cleanup: {e}")

        try:
            self.destroy_context()
        except Exception as e:
            logger.warning(f"Error destroying context during cleanup: {e}")

        try:
            self.destroy_main_loop()
        except Exception as e:
            logger.warning(f"Error destroying main loop during cleanup: {e}")

        try:
            self.deinit()
        except Exception as e:
            logger.warning(f"Error deinitializing during cleanup: {e}")

        logger.debug("PipeWire cleaned up")


# Singleton instance
_pipewire_native: Optional[PipeWireNative] = None


def get_pipewire_native() -> PipeWireNative:
    """
    Get or create the PipeWire native wrapper singleton.

    Returns:
        PipeWireNative: Singleton instance
    """
    global _pipewire_native
    if _pipewire_native is None:
        _pipewire_native = PipeWireNative()
    return _pipewire_native


def is_available() -> bool:
    """
    Check if PipeWire native bindings are available.

    Returns:
        bool: True if native bindings can be loaded
    """
    return _pw_lib is not None


def build_audio_format_params(
    sample_rate: int,
    channels: int,
    audio_format: SPAAudioFormat = SPAAudioFormat.S16_LE
) -> tuple[ctypes.c_void_p, int]:
    """
    Build SPA POD audio format parameters.

    Args:
        sample_rate: Sample rate in Hz
        channels: Number of channels
        audio_format: Audio format (default: S16_LE)

    Returns:
        Tuple of (params pointer, buffer size)
    """
    # Allocate buffer for POD (1024 bytes should be enough)
    buffer_size = 1024
    buffer = ctypes.create_string_buffer(buffer_size)

    # Initialize POD builder
    builder = spa_pod_builder()
    _pw_lib.spa_pod_builder_init(
        ctypes.byref(builder),
        ctypes.cast(buffer, ctypes.c_void_p),
        buffer_size
    )

    # Build format object
    frame = spa_pod_frame()

    # Push object: type=SPA_TYPE_OBJECT_Format, id=SPA_PARAM_EnumFormat
    _pw_lib.spa_pod_builder_push_object(
        ctypes.byref(builder),
        ctypes.byref(frame),
        SPAType.OBJECT,
        SPAParamType.EnumFormat
    )

    # Add media type (audio)
    _pw_lib.spa_pod_builder_add(
        ctypes.byref(builder),
        SPA_FORMAT_mediaType,
        SPAType.ID,
        ctypes.c_uint32(SPA_MEDIA_TYPE_audio),
        ctypes.c_uint32(0)  # Terminator
    )

    # Add media subtype (raw)
    _pw_lib.spa_pod_builder_add(
        ctypes.byref(builder),
        SPA_FORMAT_mediaSubtype,
        SPAType.ID,
        ctypes.c_uint32(SPA_MEDIA_SUBTYPE_raw),
        ctypes.c_uint32(0)  # Terminator
    )

    # Add audio format
    _pw_lib.spa_pod_builder_add(
        ctypes.byref(builder),
        SPA_FORMAT_AUDIO_format,
        SPAType.ID,
        ctypes.c_uint32(audio_format),
        ctypes.c_uint32(0)  # Terminator
    )

    # Add sample rate
    _pw_lib.spa_pod_builder_add(
        ctypes.byref(builder),
        SPA_FORMAT_AUDIO_rate,
        SPAType.INT,
        ctypes.c_int(sample_rate),
        ctypes.c_uint32(0)  # Terminator
    )

    # Add channels
    _pw_lib.spa_pod_builder_add(
        ctypes.byref(builder),
        SPA_FORMAT_AUDIO_channels,
        SPAType.INT,
        ctypes.c_int(channels),
        ctypes.c_uint32(0)  # Terminator
    )

    # Pop object
    pod = _pw_lib.spa_pod_builder_pop(ctypes.byref(builder), ctypes.byref(frame))

    if not pod:
        raise PipeWireError("Failed to build audio format POD")

    return (ctypes.cast(pod, ctypes.c_void_p), buffer_size)


class PipeWireNodeDiscovery:
    """
    Discover PipeWire nodes by process ID.

    Uses the Registry API to find audio nodes associated with a specific PID.
    """

    def __init__(self):
        """Initialize node discovery."""
        if not is_available():
            raise PipeWireError("PipeWire native bindings not available")

        self._pw = get_pipewire_native()
        self._registry: Optional[object] = None  # ctypes.POINTER(pw_registry)
        self._registry_hook = spa_hook()
        self._found_nodes: list[tuple[int, str, dict[str, str]]] = []
        self._target_pid: Optional[int] = None
        self._registry_cb_ref: Optional[object] = None  # REGISTRY_GLOBAL_CALLBACK type

    def _on_registry_global(
        self,
        _user_data: ctypes.c_void_p,
        id: int,
        _permissions: int,
        type_: bytes,
        _version: int,
        props: object  # ctypes.POINTER(spa_dict)
    ) -> None:
        """
        Registry global callback - called for each registered object.

        Args:
            _user_data: User data pointer (unused)
            id: Object ID
            _permissions: Permissions (unused)
            type_: Object type (e.g., b"PipeWire:Interface:Node")
            _version: Version (unused)
            props: Properties dictionary
        """
        assert _pw_lib is not None, "PipeWire library not loaded"
        try:
            type_str = type_.decode('utf-8') if type_ else ""

            # Only interested in Node objects
            if type_str != "PipeWire:Interface:Node":
                return

            # Parse properties
            node_props: dict[str, str] = {}
            if props and props.contents.n_items > 0:  # type: ignore
                for i in range(props.contents.n_items):  # type: ignore
                    item = props.contents.items[i]  # type: ignore
                    key = item.key.decode('utf-8') if item.key else ""
                    value = item.value.decode('utf-8') if item.value else ""
                    node_props[key] = value

            # Check if this node belongs to the target PID
            if self._target_pid is not None:
                pid_str = node_props.get("application.process.id", "")
                if pid_str and int(pid_str) == self._target_pid:
                    self._found_nodes.append((id, type_str, node_props))
                    logger.debug(
                        f"Found node {id} for PID {self._target_pid}: "
                        f"{node_props.get('node.name', 'unknown')}"
                    )

        except Exception as e:
            logger.error(f"Error in registry global callback: {e}")

    def find_nodes_by_pid(self, pid: int, timeout_ms: int = 1000) -> list[tuple[int, dict[str, str]]]:
        """
        Find audio nodes associated with a process ID.

        Args:
            pid: Process ID to search for
            timeout_ms: Timeout in milliseconds

        Returns:
            List of tuples (node_id, properties)

        Raises:
            PipeWireError: If discovery fails
        """
        self._target_pid = pid
        self._found_nodes = []

        try:
            # Initialize PipeWire if not already initialized
            if not self._pw._initialized:
                self._pw.init()
                self._pw.create_main_loop()
                self._pw.create_context()
                self._pw.connect_core()

            # Get registry
            self._registry = _pw_lib.pw_core_get_registry(
                self._pw._core,
                3,  # PW_VERSION_REGISTRY
                0   # user_data_size
            )

            if not self._registry:
                raise PipeWireRegistryError(
                    "Failed to get registry from core. "
                    "Ensure PipeWire core is connected."
                )

            # Create registry callback
            self._registry_cb_ref = REGISTRY_GLOBAL_CALLBACK(self._on_registry_global)

            # Setup registry events
            events = pw_registry_events()
            events.version = 0  # PW_VERSION_REGISTRY_EVENTS
            events.global_ = ctypes.cast(self._registry_cb_ref, ctypes.c_void_p)
            events.global_remove = None

            # Add listener
            ret = _pw_lib.pw_registry_add_listener(
                self._registry,
                ctypes.byref(self._registry_hook),
                ctypes.byref(events),
                None  # user_data
            )

            if ret < 0:
                error_msg = _get_error_string(ret)
                raise PipeWireRegistryError(
                    f"Failed to add registry listener: {error_msg}"
                )

            # Run main loop for a short time to discover nodes
            # Note: This is a simplified approach; a proper implementation
            # would use a timer to stop the loop after timeout
            if self._pw._main_loop:
                # Process events by running a few iterations
                # In a real implementation, we'd use pw_loop_iterate or similar
                import time
                start = time.time()
                while (time.time() - start) * 1000 < timeout_ms:
                    # Give PipeWire time to process events
                    time.sleep(0.01)
                    # Break early if we found nodes
                    if self._found_nodes:
                        break

            # Return found nodes (id, properties)
            return [(node_id, props) for node_id, _, props in self._found_nodes]

        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        """
        Clean up registry resources.

        Note: This method does not raise exceptions to ensure cleanup always completes.
        """
        try:
            if self._registry:
                _pw_lib.pw_registry_destroy(self._registry)
                self._registry = None
        except Exception as e:
            logger.warning(f"Error destroying registry during cleanup: {e}")

        self._registry_cb_ref = None

    def __del__(self):
        """Destructor."""
        try:
            self._cleanup()
        except:
            pass


class PipeWireStreamCapture:
    """
    High-level PipeWire stream capture using native API.

    Provides audio capture with ultra-low latency (~2-5ms).
    """

    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
        on_data: Optional[AudioCallback] = None
    ):
        """
        Initialize stream capture.

        Args:
            sample_rate: Sample rate in Hz
            channels: Number of channels
            on_data: Callback for audio data (data: bytes, frames: int)
        """
        if not is_available():
            raise PipeWireError("PipeWire native bindings not available")

        self._sample_rate = sample_rate
        self._channels = channels
        self._on_data = on_data
        self._pw = get_pipewire_native()
        self._running = False

        # Keep references to prevent garbage collection
        self._process_cb_ref: Optional[object] = None  # PROCESS_CALLBACK type
        self._params_buffer: Optional[ctypes.Array] = None  # type: ignore[type-arg]

        # Thread management
        self._thread: Optional[threading.Thread] = None
        self._thread_started = threading.Event()
        self._thread_error: Optional[Exception] = None

    def _on_process(self, user_data: ctypes.c_void_p) -> None:
        """
        Process callback - called when new audio data is available.

        Args:
            user_data: User data pointer (unused)
        """
        assert _pw_lib is not None, "PipeWire library not loaded"

        if not self._pw._stream:
            return

        # Dequeue buffer
        buf = _pw_lib.pw_stream_dequeue_buffer(self._pw._stream)
        if not buf:
            logger.warning("Failed to dequeue buffer")
            return

        try:
            # Get SPA buffer
            spa_buf = ctypes.cast(buf.contents.buffer, ctypes.POINTER(spa_buffer))
            if not spa_buf or spa_buf.contents.n_datas == 0:
                return

            # Get data
            datas = ctypes.cast(spa_buf.contents.datas, ctypes.POINTER(spa_data))
            data_ptr = datas[0]

            if not data_ptr.data:
                return

            # Get chunk info
            chunk = ctypes.cast(data_ptr.chunk, ctypes.POINTER(spa_chunk))
            if not chunk:
                return

            size = chunk.contents.size
            offset = chunk.contents.offset

            # Extract audio data
            audio_data = ctypes.string_at(
                ctypes.c_void_p(data_ptr.data + offset),
                size
            )

            # Calculate frame count
            bytes_per_sample = 2  # 16-bit
            bytes_per_frame = self._channels * bytes_per_sample
            frames = size // bytes_per_frame

            # Call user callback
            if self._on_data and audio_data:
                self._on_data(audio_data, frames)

        finally:
            # Re-queue buffer
            _pw_lib.pw_stream_queue_buffer(self._pw._stream, buf)

    def _thread_worker(self, target_id: int) -> None:
        """
        Thread worker that runs the PipeWire main loop.

        Args:
            target_id: Target node ID
        """
        try:
            # Signal that thread has started
            self._thread_started.set()

            # Run main loop (blocks until stopped)
            logger.debug("Starting PipeWire main loop in worker thread")
            if self._pw._main_loop:
                _pw_lib.pw_main_loop_run(self._pw._main_loop)
            logger.debug("PipeWire main loop stopped")

        except Exception as e:
            logger.error(f"Error in PipeWire worker thread: {e}")
            self._thread_error = e
            self._running = False

    def start(self, target_id: int = 0xFFFFFFFF, blocking: bool = False) -> None:
        """
        Start audio capture.

        Args:
            target_id: Target node ID (0xFFFFFFFF for default)
            blocking: If True, run in current thread (blocks). If False, run in background thread.

        Raises:
            PipeWireError: If capture fails to start
        """
        if self._running:
            logger.warning("Stream capture already running")
            return

        # Reset thread state
        self._thread_started.clear()
        self._thread_error = None

        try:
            # Initialize PipeWire
            self._pw.init()
            self._pw.create_main_loop()
            self._pw.create_context()
            self._pw.connect_core()

            # Create process callback
            self._process_cb_ref = PROCESS_CALLBACK(self._on_process)

            # Setup stream events
            events = pw_stream_events()
            events.version = 0  # PW_VERSION_STREAM_EVENTS
            events.process = ctypes.cast(self._process_cb_ref, ctypes.c_void_p)

            # Get main loop
            loop = _pw_lib.pw_main_loop_get_loop(self._pw._main_loop)

            # Create stream
            self._pw._stream = _pw_lib.pw_stream_new_simple(
                loop,
                b"proctap-capture",
                None,
                ctypes.byref(events),
                None  # user_data
            )

            if not self._pw._stream:
                raise PipeWireStreamError(
                    "Failed to create stream: pw_stream_new_simple returned NULL"
                )

            # Build audio format parameters
            try:
                params_ptr, buffer_size = build_audio_format_params(
                    self._sample_rate,
                    self._channels,
                    SPAAudioFormat.S16_LE
                )
            except Exception as e:
                raise PipeWireStreamError(
                    f"Failed to build audio format parameters: {e}"
                ) from e

            # Store buffer reference to prevent garbage collection
            self._params_buffer = ctypes.cast(
                params_ptr,
                ctypes.POINTER(ctypes.c_char * buffer_size)
            ).contents

            # Create params array
            params_array = (ctypes.c_void_p * 1)()
            params_array[0] = params_ptr

            # Connect stream with audio format parameters
            flags = 0  # PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS
            ret = _pw_lib.pw_stream_connect(
                self._pw._stream,
                PWDirection.INPUT,
                target_id,
                flags,
                ctypes.cast(params_array, ctypes.POINTER(ctypes.c_void_p)),
                1  # n_params
            )

            if ret < 0:
                error_msg = _get_error_string(ret)
                raise PipeWireStreamError(
                    f"Failed to connect stream: {error_msg}\n"
                    f"Target ID: {target_id:#x}\n"
                    f"Format: {self._sample_rate}Hz, {self._channels}ch, S16_LE"
                )

            self._running = True
            logger.info("PipeWire native stream capture started")

            # Start main loop
            if blocking:
                # Run in current thread (blocks)
                logger.debug("Running PipeWire main loop in current thread (blocking)")
                _pw_lib.pw_main_loop_run(self._pw._main_loop)
            else:
                # Run in background thread
                self._thread = threading.Thread(
                    target=self._thread_worker,
                    args=(target_id,),
                    name="PipeWire-Capture",
                    daemon=True
                )
                self._thread.start()

                # Wait for thread to start (with timeout)
                if not self._thread_started.wait(timeout=5.0):
                    self._cleanup()
                    raise PipeWireStreamError(
                        "Timeout waiting for capture thread to start"
                    )

                # Check for thread errors
                if self._thread_error:
                    self._cleanup()
                    raise PipeWireStreamError(
                        f"Capture thread failed: {self._thread_error}"
                    ) from self._thread_error

                logger.debug("Capture thread started successfully")

        except Exception as e:
            self._cleanup()
            if isinstance(e, PipeWireError):
                raise
            raise PipeWireStreamError(f"Failed to start capture: {e}") from e

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop audio capture.

        Args:
            timeout: Maximum time to wait for thread to stop (seconds)
        """
        if not self._running:
            return

        logger.debug("Stopping PipeWire stream capture")
        self._running = False

        # Stop main loop (this will cause thread to exit)
        if self._pw._main_loop:
            try:
                _pw_lib.pw_main_loop_quit(self._pw._main_loop)
            except Exception as e:
                logger.warning(f"Error quitting main loop: {e}")

        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            logger.debug(f"Waiting for capture thread to stop (timeout={timeout}s)")
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(
                    "Capture thread did not stop within timeout. "
                    "Thread may be stuck in native code."
                )

        self._cleanup()
        logger.info("PipeWire native stream capture stopped")

    def _cleanup(self) -> None:
        """
        Clean up resources.

        Note: This method does not raise exceptions to ensure cleanup always completes.
        """
        try:
            self._pw.cleanup()
        except Exception as e:
            logger.warning(f"Error cleaning up PipeWire during cleanup: {e}")

        self._process_cb_ref = None
        self._params_buffer = None
        self._thread = None

    def __del__(self):
        """Destructor."""
        try:
            self.stop()
        except:
            pass
