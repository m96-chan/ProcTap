# Installation

This guide covers installing ProcTap on Windows, Linux, and macOS.

## Requirements

Before installing ProcTap, ensure your system meets the platform-specific requirements:

### Windows (Fully Supported)
- **Operating System**: Windows 10 (20H1 or later) or Windows 11
- **Python Version**: 3.10, 3.11, 3.12, or 3.13
- **Administrator Rights**: Not required for using ProcTap
- **Build Tools** (for source installation): Visual Studio Build Tools + Windows SDK

!!! note "Windows Version Check"
    To check your Windows version, press ++win+r++, type `winver`, and press ++enter++.
    You need version 2004 (20H1) or later.

### Linux (Fully Supported)
- **Operating System**: Linux with PulseAudio or PipeWire
- **Python Version**: 3.10, 3.11, 3.12, or 3.13
- **System Packages**: `pulseaudio-utils` or `pipewire` with `libpipewire-0.3-dev` (optional for native API)
- **Auto-detection**: Graceful fallback between backends

### macOS (Officially Supported - v0.4.0+)
- **Operating System**: macOS 13.0 (Ventura) or later
- **Python Version**: 3.10, 3.11, 3.12, or 3.13
- **Backend**: ScreenCaptureKit (bundleID-based)
- **Permissions**: Screen Recording (automatically prompted)
- **Build Tools**: Swift toolchain / Xcode Command Line Tools

## Installation from PyPI

The simplest way to install ProcTap is using pip:

```bash
pip install proc-tap
```

This will install the pre-built wheel for your Python version and platform.

**Platform-specific dependencies are automatically installed:**
- **Linux**: `pulsectl` library is automatically installed
- **macOS**: `pyobjc-core` and `pyobjc-framework-CoreAudio` are automatically installed

### Linux System Packages

On Linux, you also need to install system packages:

```bash
# Ubuntu/Debian - PulseAudio
sudo apt-get install pulseaudio-utils

# Ubuntu/Debian - PipeWire (recommended)
sudo apt-get install pipewire pipewire-media-session

# Optional: Native PipeWire API (ultra-low latency)
sudo apt-get install libpipewire-0.3-dev

# Fedora/RHEL - PulseAudio
sudo dnf install pulseaudio-utils

# Fedora/RHEL - PipeWire (recommended)
sudo dnf install pipewire pipewire-utils
```

### macOS Build Requirements

On macOS, you need to build the Swift helper binary:

```bash
# Install Xcode Command Line Tools (if not already installed)
xcode-select --install

# Build the Swift helper
cd src/proctap/swift/screencapture-audio
swift build -c release
```

### Verify Installation

After installation, verify that ProcTap is working:

```python
python -c "from proctap import ProcessAudioCapture; print('✓ ProcTap installed successfully')"
```

## Installation from Source

If you want to build from source or contribute to development:

### 1. Install Build Dependencies

#### Windows
- **Visual Studio Build Tools** - [Download](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
- **Windows SDK** - Included with Visual Studio Build Tools

#### Linux
- **Build essentials**: `sudo apt-get install build-essential` (usually pre-installed)
- **PulseAudio development files**: `sudo apt-get install libpulse-dev` (optional)
- **PipeWire development files**: `sudo apt-get install libpipewire-0.3-dev` (optional, for native API)

#### macOS
- **Xcode Command Line Tools**: `xcode-select --install`
- **Swift toolchain**: Included with Xcode Command Line Tools

### 2. Clone the Repository

```bash
git clone https://github.com/m96-chan/ProcTap
cd ProcTap
```

### 3. Install in Development Mode

```bash
# Basic installation
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

### 4. Build Platform-Specific Components

#### macOS: Build Swift Helper
```bash
cd src/proctap/swift/screencapture-audio
swift build -c release
cd ../../../..
```

### 5. Verify Build

```python
python -c "from proctap import ProcessAudioCapture; print('✓ Build successful')"
```

!!! tip "Rebuilding After Code Changes"
    **Windows**: If you modify the C++ code in `src/proctap/_native.cpp`, rebuild with:
    ```bash
    pip install -e . --force-reinstall --no-deps
    ```

    **macOS**: If you modify the Swift helper, rebuild with:
    ```bash
    cd src/proctap/swift/screencapture-audio
    swift build -c release
    ```

## Installation from TestPyPI

For testing pre-release versions:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ proc-tap
```

## Optional Dependencies

### For Examples

Some examples require additional packages:

```bash
# For process name → PID resolution
pip install psutil
```

### For Development

Development dependencies are specified in `pyproject.toml`:

```bash
pip install -e ".[dev]"
```

This includes:
- `pytest` - Test framework
- `mypy` - Type checking
- `types-setuptools` - Type stubs

### For Documentation

To build this documentation locally:

```bash
pip install mkdocs-material mkdocstrings[python]
mkdocs serve
```

Then open [http://localhost:8000](http://localhost:8000).

## Troubleshooting

### Import Error: No module named 'proctap'

**Problem**: Python can't find the ProcTap package.

**Solution**:
```bash
pip install proc-tap
# Or for development:
pip install -e .
```

### Import Error: DLL load failed

**Problem**: The C++ extension can't load.

**Possible causes**:
1. Missing Visual C++ Redistributable
2. Incompatible Python version
3. Build failed during installation

**Solution**:
```bash
# Reinstall with verbose output
pip install proc-tap --force-reinstall -v
```

### Build Error: 'cl.exe' not found

**Problem**: C++ compiler not found.

**Solution**:
Install Visual Studio Build Tools:

1. Download from [Microsoft](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
2. Run installer
3. Select "Desktop development with C++"
4. Include Windows SDK

## Next Steps

- [Quick Start](quickstart.md) - Get started with ProcTap
- [Examples](examples.md) - See usage examples
- [API Reference](../api/processaudiotap.md) - Detailed API documentation
