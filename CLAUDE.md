# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ProcTap is a cross-platform Python library for capturing audio from specific processes. It provides platform-optimized backends for Windows, Linux, and macOS.

**Platform Support:**
- **Windows**: ✅ Fully implemented using WASAPI Process Loopback (C++ native extension)
- **Linux**: 🧪 Experimental - PulseAudio backend (basic implementation with limitations)
- **macOS**: 🧪 Experimental - Core Audio Process Tap via Swift CLI helper (macOS 14.4+)

**Key Characteristics:**
- Per-process audio isolation (not system-wide)
- Low-latency streaming (10ms default buffer on Windows)
- Platform-specific implementations:
  - Windows: WASAPI C++ extension (Windows 10 20H1+)
  - Linux: PulseAudio backend (experimental)
  - macOS: Core Audio Process Tap via Swift helper (macOS 14.4+, experimental)
- Dual API: callback-based and async iterator patterns

## Development Guidelines

### Testing Standards

**IMPORTANT:** When creating test code, ALWAYS follow pytest conventions:
- Use pytest framework for all tests
- Place tests in `tests/` directory or name files with `test_*.py` pattern
- Use pytest fixtures, parametrize, and markers
- Follow pytest discovery conventions
- Delete experimental/temporary test scripts after verification

### Setup and Building

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Build wheel (requires Visual Studio Build Tools + Windows SDK)
python -m build --wheel

# Build source distribution
python -m build
```

**Important:** After modifying C++ code in [_native.cpp](src/proctap/_native.cpp), you must rebuild:
```bash
pip install -e . --force-reinstall --no-deps
```

### Testing and Type Checking

```bash
# Run tests
pytest

# Type check
mypy src/
```

### Running Examples

```bash
# Windows example
python examples/windows_basic.py --pid 12345 --output audio.wav
python examples/windows_basic.py --name "VRChat.exe" --output audio.wav

# Linux example (requires pulseaudio-utils)
python examples/linux_basic.py --pid 12345 --duration 5 --output output.wav

# macOS example (requires macOS 14.4+, Swift helper)
python examples/macos_basic.py --pid 12345 --duration 5 --output output.wav
```

### CLI Usage (Pipe to FFmpeg)

The package installs a `proctap` command for direct use:

```bash
# Direct command (recommended)
proctap --pid 12345 --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 output.mp3

# Or using python -m (alternative)
python -m proctap --pid 12345 --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 output.mp3

# Using process name instead of PID
proctap --name "VRChat.exe" --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 output.mp3

# Custom sample rate and mono output
proctap --pid 12345 --sample-rate 44100 --channels 1 --stdout | ffmpeg -f s16le -ar 44100 -ac 1 -i pipe:0 output.wav
```

### Building macOS Swift Helper

```bash
# Build Swift CLI helper for macOS
cd swift/proctap-macos
swift build -c release

# Copy to package directory
cp .build/release/proctap-macos ../../src/proctap/bin/

# The setup.py build system will do this automatically on macOS if Swift toolchain is available
```

## Architecture

### Multi-Platform Backend Architecture

The library uses platform-specific backends selected at runtime:

```
ProcTap (core.py - Public API)
    ↓
backends/__init__.py (Platform Detection)
    ↓
┌─────────────────┬──────────────────┬──────────────────┐
│ Windows         │ Linux            │ macOS            │
│ (Implemented)   │ (Experimental)   │ (Experimental)   │
├─────────────────┼──────────────────┼──────────────────┤
│ WindowsBackend  │ LinuxBackend     │ MacOSBackend     │
│ └─ _native.cpp  │ └─ PulseAudio    │ └─ Swift CLI     │
│    (WASAPI)     │    (parec)       │    (Process Tap) │
└─────────────────┴──────────────────┴──────────────────┘
```

**Backend Selection** ([backends/__init__.py](src/proctap/backends/__init__.py)):
- Automatic platform detection using `platform.system()`
- Windows: Uses native C++ extension with WASAPI
- Linux: PulseAudio backend (experimental)
- macOS: Core Audio Process Tap via Swift CLI helper (experimental)

**Windows Backend** ([backends/windows.py](src/proctap/backends/windows.py)):
- Wraps `_native.cpp` C++ extension
- Per-process audio capture requires `ActivateAudioInterfaceAsync` (Windows 10 20H1+)
- Native WASAPI format: 44.1kHz, 2ch, 16-bit PCM (fixed in C++)
- **Audio Format Conversion** ([backends/converter.py](src/proctap/backends/converter.py)):
  - Python-based audio format conversion using scipy
  - Supports sample rate conversion (resampling)
  - Supports channel conversion (mono ↔ stereo)
  - Supports bit depth conversion (8/16/24/32-bit)
  - Automatically converts WASAPI output to match `StreamConfig`
  - No conversion overhead if formats already match

**Linux Backend** ([backends/linux.py](src/proctap/backends/linux.py)):
- ✅ Fully implemented with multiple strategies (v0.3.0+)
- **PipeWire Native API** ([backends/pipewire_native.py](src/proctap/backends/pipewire_native.py)):
  - Ultra-low latency: ~2-5ms (vs ~10-20ms subprocess-based)
  - Direct C API bindings via ctypes
  - Auto-selected when available
- **Strategy Pattern:** PipeWire Native → PipeWire subprocess (`pw-record`) → PulseAudio (`parec`)
- **Per-process Isolation:** True isolation using null-sink strategy
- Uses `pulsectl` library for stream management
- Requires: System-dependent (libpipewire-0.3-dev for native, pw-record or parec for subprocess)

**macOS Backend** ([backends/macos.py](src/proctap/backends/macos.py)):
- 🧪 Experimental - Core Audio Process Tap API (macOS 14.4+)
- Uses Swift CLI helper binary (proctap-macos) that wraps Core Audio APIs
- Swift helper outputs raw PCM to stdout, Python reads from subprocess pipe
- **Requirements:**
  - macOS 14.4 (Sonoma) or later
  - Swift CLI helper binary (built with SwiftPM)
  - Audio capture permission (NSAudioCaptureUsageDescription)
  - Target process must be actively playing audio
- **Implementation:**
  - Python side: Version detection, subprocess management, PCM reading
  - Swift side: Core Audio Process Tap API, aggregate device creation, IOProc callback
  - See [swift/proctap-macos/](swift/proctap-macos/) for Swift helper source

### Threading Model

Audio capture runs on a background thread to prevent blocking:

1. **Worker Thread**: Reads from WASAPI capture buffer continuously
2. **Main Thread**: Receives data via callbacks or async queue
3. **Synchronization**: Thread-safe queue for async iteration, direct callbacks for callback mode

**Data Flow:**
```
Audio Source (Process-specific)
  → Platform Backend (WASAPI/PulseAudio/CoreAudio)
  → Worker Thread
  → Queue/Callback
  → User Code
```

### Key Components

**[core.py](src/proctap/core.py)** - Main API surface:
- `ProcessAudioCapture`: User-facing class with two operation modes:
  - Callback mode: `start(on_data=callback)`
  - Async mode: `async for chunk in tap.iter_chunks()`
  - Uses platform-specific backend via `get_backend()`
- `StreamConfig`: Audio format configuration
  - If `None`, uses native backend format (no conversion)
  - If specified, backend converts to match the desired format

**[backends/](src/proctap/backends/)** - Platform-specific implementations:
- `base.py`: `AudioBackend` abstract base class
- `windows.py`: Windows implementation (wraps `_native.cpp` + format conversion)
- `linux.py`: Linux PulseAudio implementation (experimental)
- `macos.py`: macOS Core Audio Process Tap implementation (experimental)
- `converter.py`: Audio format converter (sample rate, channels, bit depth)

**[_native.cpp](src/proctap/_native.cpp)** - Windows C++ Extension:
- `ProcessLoopback` class: WASAPI capture implementation
- Uses `ActivateAudioInterfaceAsync` for process-specific capture
- COM/WRL integration with proper apartment threading
- Exposes methods: `start()`, `stop()`, `read()`, `get_format()`

## Build System Details

**Platform-Specific Builds:**

The build system ([setup.py](setup.py)) automatically detects the platform and builds appropriate extensions:

**Windows Build Requirements:**
- Visual Studio Build Tools (MSVC compiler)
- Windows SDK
- Python 3.10+ (supports 3.10, 3.11, 3.12, 3.13)
- C++20 compiler (`/std:c++20` flag)

**Windows Linked Libraries:**
- `ole32`: COM infrastructure
- `uuid`: GUID support
- `propsys`: Property system

**Extension Module:** Builds as `_native.cp3XX-win_amd64.pyd` (Windows only)

**Linux Builds:**
- No C++ extension required (pure Python)
- PulseAudio backend uses `pulsectl` library and `parec` command
- System dependencies: `pulseaudio-utils` package

**macOS Builds:**
- Swift CLI helper (proctap-macos) built with SwiftPM
- Custom `build_py` command in setup.py:
  - Runs `swift build -c release` in `swift/proctap-macos/`
  - Copies binary to `src/proctap/bin/`
  - Makes binary executable
- Gracefully degrades if Swift toolchain not available
- Binary included in wheel via `package_data`

## Python Dependencies

**Runtime:**
- **Core**:
  - `numpy>=1.20.0` - Array operations for audio processing
  - `scipy>=1.7.0` - Signal processing (fallback resampling)
- **Optional**:
  - `samplerate>=0.1.0` - Professional-grade audio resampling (libsamplerate)
    - Install with: `pip install proc-tap[hq-resample]`
    - **Note**: May fail to build on some platforms (Windows with Python 3.13+)
    - Falls back to scipy if not available
- **Windows**: Uses native C++ extension + Python format conversion
- **Linux**: `pulsectl>=23.5.0` (automatically installed via environment markers in pyproject.toml)
- **macOS**: No additional dependencies (uses Swift CLI helper binary)

**System Dependencies (Linux only):**
- `parec` command from `pulseaudio-utils` package
- PulseAudio or PipeWire with pulseaudio-compat

**Examples:**
- `psutil`: Used in examples for process name → PID resolution

**Development:**
- `pytest`: Test framework
- `mypy`: Type checking
- `types-setuptools`, `types-psutil`, `scipy-stubs`: Type stubs for type checking

**Contrib (optional):**
- `faster-whisper>=1.0.0`: For real-time transcription features
  - Install with: `pip install proc-tap[contrib]`

## Audio Format

**Windows Backend:**

The Windows native extension uses a **fixed audio format** hardcoded in [_native.cpp:329-336](src/proctap/_native.cpp#L329-L336):

- **Sample Rate:** 44,100 Hz (CD quality)
- **Channels:** 2 (stereo)
- **Bits per Sample:** 16-bit
- **Format:** PCM (WAVE_FORMAT_PCM)
- **Block Align:** 4 bytes (2 channels × 16 bits / 8)
- **Byte Rate:** 176,400 bytes/sec

**Format Conversion (New in v0.2.1):**

The `StreamConfig` parameter now controls output format through automatic conversion:

- **Native Format (C++)**: Fixed at 44.1kHz, 2ch, 16-bit PCM (WASAPI requirement)
- **Output Format (Python)**: Converted to match `StreamConfig` settings
- **Conversion Features**:
  - Sample rate conversion (e.g., 44.1kHz → 48kHz)
  - Channel conversion (stereo ↔ mono)
  - Bit depth conversion (8/16/24/32-bit)
  - Automatic bypass when formats match (zero overhead)
- **Resampling Quality** (automatic priority order):
  1. **libsamplerate** (optional, highest quality)
     - Professional-grade SRC (Sample Rate Converter)
     - SINC interpolation with minimal artifacts
     - Install with: `pip install proc-tap[hq-resample]`
     - **Note**: May fail to build on Windows with Python 3.13+
  2. **scipy.signal.resample_poly** (default fallback, high quality)
     - Polyphase filtering
     - Used if libsamplerate is not installed or unavailable
  3. **scipy.signal.resample** (final fallback)
     - FFT-based resampling
     - Used only if both above methods fail
- **Usage**:
  ```python
  # Use native format (no conversion)
  tap = ProcessAudioCapture(pid, config=None)

  # Convert to 48kHz stereo (uses libsamplerate if available, scipy otherwise)
  config = StreamConfig(sample_rate=48000, channels=2)
  tap = ProcessAudioCapture(pid, config=config)
  ```

**Linux Backend:**

The PulseAudio backend respects the `StreamConfig` settings:
- Default: 44,100 Hz, 2 channels, 16-bit PCM
- Configurable via `StreamConfig` parameter

**macOS Backend:**

The Core Audio Process Tap backend respects the `StreamConfig` settings:
- Default: 48,000 Hz, 2 channels, 16-bit PCM
- Configurable via `StreamConfig` parameter
- Format specified via command-line args to Swift helper

Raw PCM data is returned as `bytes` to user callbacks/iterators.

## Known Issues and TODOs

**Windows Backend:**
1. ✅ **Audio Format Conversion** - COMPLETED in v0.2.1
   - StreamConfig now controls output format via Python-based conversion
   - WASAPI native format (44.1kHz/2ch/16bit) automatically converted to desired format
   - See [backends/converter.py](src/proctap/backends/converter.py)

2. **Frame Count Calculation** ([core.py:207](src/proctap/core.py#L207)):
   - Currently returns `-1` for frame count in callbacks
   - TODO: Calculate from backend format info (needs to account for conversion)

3. **Buffer Size Control** ([core.py:29](src/proctap/core.py#L29)):
   - `buffer_ms` parameter exists but note indicates limited control

**Linux Backend:**
1. **Native PipeWire API Implementation** ([backends/pipewire_native.py](src/proctap/backends/pipewire_native.py)):
   - ✅ COMPLETED (v0.4.0+):
     * SPA POD format parameters
     * Registry API for node discovery
     * Comprehensive error handling
     * Thread management
     * Integration with LinuxBackend
   - ✅ Testing: Unit tests and examples added

2. **Cross-distribution Testing** (Ongoing):
   - Verify on Ubuntu, Fedora, Arch Linux, Debian
   - Test with various PipeWire and PulseAudio versions
   - Validate fallback behavior

**macOS Backend (Experimental):**
1. **Core Audio Process Tap Implementation** ([backends/macos.py](src/proctap/backends/macos.py)):
   - ✅ Basic implementation complete using Swift CLI helper
   - ✅ macOS 14.4+ version detection
   - ✅ Swift helper binary discovery and subprocess management
   - ✅ PCM streaming from stdout
   - TODO: Test on actual macOS 14.4+ system
   - TODO: Handle permission prompts gracefully
   - TODO: Improve error messages for common failure modes
   - TODO: Code signing guidance for distribution

**General:**
1. **Test Coverage:**
   - ✅ Audio format converter tests added ([test_converter.py](test_converter.py))
   - TODO: Add platform-specific backend tests
   - TODO: Add integration tests for ProcessAudioCapture with real processes

## CI/CD Workflows

GitHub Actions workflows in [.github/workflows/](.github/workflows/):

- **[build-wheels.yml](.github/workflows/build-wheels.yml)**: Multi-platform wheel builds
  - Builds for Windows, Linux, macOS
  - Python versions: 3.10, 3.11, 3.12, 3.13
  - Platform-specific setup: PulseAudio (Linux), Swift verification (macOS)

- **[publish-pypi.yml](.github/workflows/publish-pypi.yml)**: PyPI release workflow
  - Builds wheels for all platforms
  - Merges artifacts from multiple runners
  - Manual trigger with git tag input

- **[release-testpypi.yml](.github/workflows/release-testpypi.yml)**: TestPyPI releases
  - Triggered on version tags (v*.*.*)
  - Multi-platform wheel generation
  - Automatic upload to TestPyPI

**Platform-Specific Build Steps:**
- **Windows**: C++ extension compilation (Visual Studio Build Tools)
- **Linux**: PulseAudio system package installation
- **macOS**: Swift CLI helper compilation (SwiftPM)
