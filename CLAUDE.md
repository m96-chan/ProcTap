# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ProcessAudioTap is a Windows-only Python library for capturing audio from specific processes using WASAPI Process Loopback. It provides both a high-performance C++ native extension and a pure Python fallback backend.

**Key Characteristics:**
- Per-process audio isolation (not system-wide)
- Low-latency streaming (10ms default buffer)
- Windows 10 20H1+ required for process-specific capture
- Dual API: callback-based and async iterator patterns

## Development Commands

### Setup and Building

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Build wheel (requires Visual Studio Build Tools + Windows SDK)
python -m build --wheel

# Build source distribution
python -m build
```

**Important:** After modifying C++ code in [_native.cpp](src/processaudiotap/_native.cpp), you must rebuild:
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
# Capture by process ID
python examples/record_proc_to_wav.py --pid 12345 --output audio.wav

# Capture by process name (requires psutil)
python examples/record_proc_to_wav.py --name "VRChat.exe" --output audio.wav
```

## Architecture

### Native-Only Architecture

The library uses a native C++ extension for per-process audio capture:

```
ProcessAudioTap (core.py - Public API)
    ↓
_BackendWrapper (Thin wrapper)
    ↓
_NativeLoopback (C++ extension - REQUIRED)
    - Uses ActivateAudioInterfaceAsync
    - Per-process audio capture
    - Defined in _native.cpp (763 lines)
```

**Backend Requirements** ([core.py:16-24](src/processaudiotap/core.py#L16-L24)):
- The native C++ extension (`_native`) is **required**
- If the extension fails to import, an `ImportError` is raised immediately
- No Python fallback is provided, as per-process capture requires native WASAPI APIs

**Why Native-Only:**
- Per-process audio capture requires `ActivateAudioInterfaceAsync` (Windows 10 20H1+)
- Pure Python implementations can only capture system-wide audio
- Maintaining a fallback that doesn't support the core feature adds complexity without value

### Threading Model

Audio capture runs on a background thread to prevent blocking:

1. **Worker Thread**: Reads from WASAPI capture buffer continuously
2. **Main Thread**: Receives data via callbacks or async queue
3. **Synchronization**: Thread-safe queue for async iteration, direct callbacks for callback mode

**Data Flow:**
```
WASAPI Capture Buffer
  → C++ Native Backend
  → Worker Thread
  → Queue/Callback
  → User Code
```

### Key Components

**[core.py](src/processaudiotap/core.py)** - Main API surface:
- `ProcessAudioTap`: User-facing class with two operation modes:
  - Callback mode: `start(on_data=callback)`
  - Async mode: `async for chunk in tap.iter_chunks()`
- `StreamConfig`: Audio format configuration (default: 48kHz, stereo, 10ms buffer)
- `_BackendWrapper`: Thin wrapper around native backend for interface consistency

**[_native.cpp](src/processaudiotap/_native.cpp)** - C++ Extension:
- `ProcessLoopback` class: Main capture implementation
- Uses `ActivateAudioInterfaceAsync` for process-specific capture
- COM/WRL integration with proper apartment threading
- Exposes methods: `start()`, `stop()`, `read()`

## Build System Details

**Requirements:**
- Windows OS only (`os.name == "nt"` enforced in setup.py)
- Visual Studio Build Tools (MSVC compiler)
- Windows SDK
- Python 3.10+ (supports 3.10, 3.11, 3.12, 3.13)
- C++20 compiler (`/std:c++20` flag in setup.py)

**Linked Libraries** ([setup.py:30](setup.py#L30)):
- `ole32`: COM infrastructure
- `uuid`: GUID support
- `propsys`: Property system

**Extension Module:** Builds as `_native.cp3XX-win_amd64.pyd` (platform-specific)

## Python Dependencies

**Runtime:**
- **None** - The library has no runtime Python dependencies
- The native C++ extension is built into the package

**Optional:**
- `psutil`: Used in examples for process name → PID resolution

**Development:**
- `pytest`: Test framework
- `mypy`: Type checking
- `types-setuptools`: Type stubs for setuptools

## Audio Format Defaults

Default configuration in `StreamConfig`:
- **Sample Rate:** 48000 Hz
- **Channels:** 2 (stereo)
- **Bits per Sample:** 16-bit
- **Buffer Duration:** 10ms (configurable via `buffer_ms`)

Format is enforced in WASAPI initialization. Raw PCM data is returned as `bytes` to user callbacks/iterators.

## Known Issues and TODOs

1. **Frame Count Calculation** ([core.py:210](src/processaudiotap/core.py#L210)):
   - Currently returns `-1` for frame count in callbacks
   - TODO: Calculate from backend format info

2. **Buffer Size Control** ([core.py:32](src/processaudiotap/core.py#L32)):
   - `buffer_ms` parameter exists but note indicates limited control

3. **Test Coverage:**
   - No test suite currently in repository (pytest configured but no tests written)

## CI/CD Workflows

GitHub Actions workflows in [.github/workflows/](.github/workflows/):

- **[build-wheels.yml](.github/workflows/build-wheels.yml)**: Multi-version wheel builds (Python 3.10-3.13)
- **[publish-pypi.yml](.github/workflows/publish-pypi.yml)**: Manual PyPI release trigger
- **[release-testpypi.yml](.github/workflows/release-testpypi.yml)**: TestPyPI releases

All workflows use Windows runners due to platform dependency.
