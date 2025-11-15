# ProcTap Examples

This directory provides usage examples for the ProcTap library.

## Overview

This directory contains practical examples of per-process audio capture using ProcTap across different platforms. Each sample demonstrates platform-specific usage patterns.

## Available Examples

- **[windows_basic.py](windows_basic.py)**: Windows per-process audio capture example
- **[linux_basic.py](linux_basic.py)**: Linux PulseAudio capture example (experimental)
- **[macos_basic.py](macos_basic.py)**: macOS Core Audio Process Tap example (experimental)

## Platform Requirements

### Windows
- **OS**: Windows 10 (20H1 or later) or Windows 11
- **Python**: 3.10 or higher
- **Permissions**: No administrator privileges required

### Linux
- **OS**: Linux with PulseAudio or PipeWire
- **Python**: 3.10 or higher
- **System Package**: `pulseaudio-utils` (provides `parec` command)

### macOS
- **OS**: macOS 14.4 (Sonoma) or later
- **Python**: 3.10 or higher
- **Swift Helper**: Built automatically during installation

## Installation

### Install ProcTap

```bash
# From PyPI (recommended)
pip install proc-tap

# From source (for development)
git clone https://github.com/m96-chan/ProcTap
cd ProcTap
pip install -e .
```

### Optional: Install psutil (for process name lookup)

```bash
pip install psutil
```

---

## Example: windows_basic.py

### Description

This example captures audio from a specific process and saves it to a WAV file. You can specify either a process ID or process name to record the audio output from that process.

### Features

- Specify target process by process ID (`--pid`) or process name (`--name`)
- Save captured audio to a WAV file
- Stop recording with Enter key or Ctrl+C
- Records in 44.1kHz, stereo, 16-bit PCM format

### Usage

#### Basic Syntax

```bash
python examples/windows_basic.py [--pid PID | --name PROCESS_NAME] [--output OUTPUT_FILE]
```

#### Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--pid` | Integer | Yes* | Process ID to capture |
| `--name` | String | Yes* | Process name to capture (e.g., "VRChat.exe" or "VRChat") |
| `--output` | String | No | Output WAV file path (default: "output.wav") |

\* Either `--pid` or `--name` is required.

### Examples

#### 1. Recording by Process Name (Recommended)

```bash
# Record audio from VRChat
python examples/windows_basic.py --name "VRChat.exe" --output vrchat_audio.wav

# Record audio from Discord (works without .exe extension)
python examples/windows_basic.py --name "Discord" --output discord_audio.wav

# Use default output filename (output.wav)
python examples/windows_basic.py --name "spotify.exe"
```

#### 2. Recording by Process ID

```bash
# Record from process with PID 1234
python examples/windows_basic.py --pid 1234 --output audio.wav
```

### How to Find Process ID

#### Method 1: Task Manager

1. Open Task Manager with `Ctrl + Shift + Esc`
2. Click the "Details" tab
3. Check the "PID" column for the target process

#### Method 2: tasklist Command

```bash
# Display all processes
tasklist

# Search for a specific process name
tasklist | findstr "VRChat"
```

#### Method 3: Use Process Name (Easiest)

Using the `--name` option eliminates the need to look up the PID.

### Output File Format

Specifications of the recorded WAV file:

- **Format**: WAV (PCM)
- **Sample Rate**: 44,100 Hz (CD quality)
- **Channels**: 2 (stereo)
- **Bit Depth**: 16-bit
- **Encoding**: Linear PCM

### Stopping Recording

To stop recording:

- **Press Enter key**, or
- **Press Ctrl + C**

The WAV file will be saved when recording stops.

---

## Troubleshooting

### Error: `ModuleNotFoundError: No module named 'proctap'`

**Cause**: ProcTap is not installed.

**Solution**:
```bash
cd /path/to/ProcTap
pip install -e .
```

### Error: `ModuleNotFoundError: No module named 'psutil'`

**Cause**: psutil is not installed.

**Solution**:
```bash
pip install psutil
```

### Error: `Process 'ProcessName' not found`

**Cause**: The specified process name is not running.

**Solution**:
1. Verify the process name is correct
2. Ensure the application is running
3. Use `tasklist` command to find the exact process name

### Error: `ImportError: Native extension (_native) could not be imported`

**Cause**: C++ extension has not been built.

**Solution**:
```bash
# Rebuild the C++ extension
pip install -e . --force-reinstall --no-deps
```

**Note**: ProcTap requires the native C++ extension. Ensure Visual Studio Build Tools and Windows SDK are installed.

### Audio is Not Being Captured

**Things to Check**:
1. Verify the target process is actually playing audio
2. Ensure Windows 10 is version 20H1 or later (check with `winver` command)
3. Verify the process ID or name is correct

---

## Additional Information

### Supported Audio Applications Examples

- Games: VRChat, Discord, general gaming applications
- Media Players: Spotify, foobar2000, MusicBee
- Communication Apps: Discord, Zoom, Teams
- Browsers: Chrome, Firefox, Edge (per-tab processes)

### Benefits of Per-Process Capture

- Capture audio from specific applications only, not the entire system
- Record only the desired audio even when multiple applications are playing sound
- No administrator privileges required

### Platform Limitations

- **Windows**: Requires Windows 10 20H1 or later for per-process WASAPI capture
- **Linux**: Experimental - currently captures from sink monitor (may include other apps)
- **macOS**: Experimental - requires macOS 14.4+ for Core Audio Process Tap API

---

## Support

- **Bug Reports**: [GitHub Issues](https://github.com/m96-chan/ProcTap/issues)
- **Documentation**: [README.md](../README.md) in the project root
- **API Details**: [CLAUDE.md](../CLAUDE.md)
