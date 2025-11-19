<div align="center">

# 📡 ProcTap

**Cross-Platform Per-Process Audio Capture**

[![PyPI version](https://img.shields.io/pypi/v/proc-tap?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/proc-tap/)
[![Python versions](https://img.shields.io/pypi/pyversions/proc-tap?logo=python&logoColor=white)](https://pypi.org/project/proc-tap/)
[![Downloads](https://img.shields.io/pypi/dm/proc-tap?logo=pypi&logoColor=white)](https://pypi.org/project/proc-tap/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux*%20%7C%20macOS*-blue)](https://github.com/m96-chan/ProcTap)

[![Build wheels](https://github.com/m96-chan/ProcTap/actions/workflows/build-wheels.yml/badge.svg)](https://github.com/m96-chan/ProcTap/actions/workflows/build-wheels.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub stars](https://img.shields.io/github/stars/m96-chan/ProcTap?style=social)](https://github.com/m96-chan/ProcTap/stargazers)

---

ProcTap is a Python library for per-process audio capture with platform-specific backends.

**Capture audio from a specific process only** — without system sounds or other app audio mixed in.
Ideal for VRChat, games, DAWs, browsers, and AI audio analysis pipelines.

### Platform Support

| Platform | Status | Backend | Notes |
|----------|--------|---------|-------|
| **Windows** | ✅ **Fully Supported** | WASAPI (C++ native) | Windows 10/11 (20H1+) |
| **Linux** | ✅ **Fully Supported** | PipeWire Native / PulseAudio | Per-process isolation, auto-fallback (v0.3.0+) |
| **macOS** | 🧪 **Experimental** | Core Audio Process Tap | macOS 14.4+ (Sonoma) required |

<sub>\* Linux is fully supported with PipeWire/PulseAudio (v0.3.0+). macOS support is experimental (see requirements).</sub>

</div>

---

## 🚀 Features

- 🎧 **Capture audio from a single target process**
  (VRChat, games, browsers, Discord, DAWs, streaming tools, etc.)

- 🌍 **Cross-platform architecture**
  → Windows (fully supported) | Linux (fully supported, v0.3.0+) | macOS (experimental, 14.4+)

- ⚡ **Platform-optimized backends**
  → Windows: ActivateAudioInterfaceAsync (modern WASAPI)
  → Linux: PipeWire Native API / PulseAudio (fully supported, v0.3.0+)
  → macOS: Core Audio Process Tap API (macOS 14.4+)

- 🧵 **Low-latency, thread-safe audio engine**
  → 44.1 kHz / stereo / 16-bit PCM format (Windows)

- 🐍 **Python-friendly high-level API**
  - Callback-based streaming
  - Async generator streaming (`async for`)

- 🔌 **Native extensions for high-performance**
  → C++ extension on Windows for optimal throughput

---

## 📦 Installation

**From PyPI**:

```bash
pip install proc-tap
```

**Platform-specific dependencies are automatically installed:**
- Windows: No additional dependencies
- Linux: `pulsectl` is automatically installed, but you also need system packages:
  ```bash
  # Ubuntu/Debian
  sudo apt-get install pulseaudio-utils

  # Fedora/RHEL
  sudo dnf install pulseaudio-utils
  ```

**Optional: High-Quality Audio Resampling** (74% faster / 3.8x speedup for sample rate conversion):

```bash
pip install proc-tap[hq-resample]
```

**Performance:** With `libsamplerate`, resampling achieves **0.66ms per 10ms chunk** (vs 2.6ms with scipy-only).

**Compatibility Notes:**
- ✅ **Python 3.10-3.12**: Works on all platforms
- ✅ **Linux/macOS + Python 3.13+**: Should work (you can try it!)
- ⚠️ **Windows + Python 3.13+**: May fail to build (as of 2025-01)
  - If it fails, the library automatically falls back to scipy's polyphase filtering
  - Still provides excellent audio quality, just 74% slower for resampling
  - You can still try installing - if it works, great! If not, no harm done.

📚 **[Read the Full Documentation](https://m96-chan.github.io/ProcTap/)** for detailed guides and API reference.

**From TestPyPI** (for testing pre-releases):

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ proctap
```

**From Source**:

```bash
git clone https://github.com/m96-chan/ProcTap
cd ProcTap
pip install -e .
```

---

## 🎬 CLI Usage (Pipe to FFmpeg)

ProcTap includes a CLI for piping audio directly to FFmpeg or other tools:

```bash
# Pipe to FFmpeg (MP3 encoding) - Direct command
proctap --pid 12345 --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 output.mp3

# Or using python -m
python -m proctap --pid 12345 --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 output.mp3

# Using process name instead of PID
proctap --name "VRChat.exe" --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 output.mp3

# FLAC encoding (lossless)
proctap --pid 12345 --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 output.flac

# Custom sample rate and mono output
proctap --pid 12345 --sample-rate 44100 --channels 1 --stdout | ffmpeg -f s16le -ar 44100 -ac 1 -i pipe:0 output.wav
```

**CLI Options:**

| Option | Description |
|--------|-------------|
| `--pid PID` | Process ID to capture (required if `--name` not used) |
| `--name NAME` | Process name to capture (e.g., `VRChat.exe` or `VRChat`) |
| `--stdout` | Output raw PCM to stdout for piping (required) |
| `--sample-rate RATE` | Sample rate in Hz (default: 48000) |
| `--channels {1,2}` | Number of channels: 1=mono, 2=stereo (default: 2) |
| `--native-converter` | **Windows only:** Enable SIMD native converter pipeline (beta) |
| `--quality {low,high}` | **Windows only:** Resampling quality for native converter (`low`=linear, `high`=libsamplerate) |
| `--verbose` | Enable verbose logging to stderr |

> **Windows note:** The native converter still emits s16le PCM on stdout, but moves int16→float32 + resampling into a SIMD-optimized C++ path. `--quality high` requires `libsamplerate`; install the optional extra `pip install proc-tap[hq-resample]` or point `LIBSAMPLERATE_PATH` to the directory containing `libsamplerate-0.dll`.

**Finding Process IDs:**

```bash
# Windows
tasklist | findstr "VRChat"

# Linux/macOS
ps aux | grep VRChat
```

**FFmpeg Format Arguments:**

The CLI outputs raw PCM in s16le (signed 16-bit little-endian) format by default, but can be customized via `--sample-rate` and `--channels` options. FFmpeg needs these arguments:
- `-f s16le`: PCM format
- `-ar RATE`: Sample rate (must match `--sample-rate`, default 48000)
- `-ac CHANNELS`: Number of channels (must match `--channels`, default 2)
- `-i pipe:0`: Read from stdin

## 🚀 Native Converter Benchmark (Windows)

Use the helper script to quickly sanity-check throughput and latency of the SIMD converter:

```bash
python benchmarks/benchmark_native_converter.py --quality high --seconds 5 --iterations 20
```

It generates synthetic audio, converts it to the fixed 48kHz/float32 format, and reports realtime factors for both low-latency (linear) and high-quality (libsamplerate) modes. Requires the native extension to be built (Windows only).

---

## 🛠 Requirements

**Windows (Fully Supported):**
- Windows 10 / 11 (20H1 or later)
- Python 3.10+
- WASAPI support
- **No admin privileges required**
- 🧪 **Native SIMD converter (beta, Windows-only)**:
  - Enable with `--native-converter` (CLI) or `StreamConfig(use_native_converter=True)`
  - `--quality high` uses libsamplerate (install `pip install proc-tap[hq-resample]` or set `LIBSAMPLERATE_PATH` to `libsamplerate-0.dll`)
  - Automatically falls back to the Python converter if SIMD extension or libsamplerate is unavailable

**Linux (Fully Supported - v0.3.0+):**
- Linux with PulseAudio or PipeWire
- Python 3.10+
- **Auto-detection:** Automatically selects best available backend
- **Native PipeWire API** (in development, experimental):
  - `libpipewire-0.3-dev`: `sudo apt-get install libpipewire-0.3-dev`
  - Target latency: ~2-5ms (when fully implemented)
  - Auto-selected when available (may fall back to subprocess)
- **PipeWire subprocess:**
  - `pw-record`: install with `sudo apt-get install pipewire-media-session`
- **PulseAudio fallback:**
  - `pulsectl` library: automatically installed
  - `parec` command: `sudo apt-get install pulseaudio-utils`
- ✅ **Per-process isolation** using null-sink strategy
- ✅ **Graceful fallback** chain: Native → PipeWire subprocess → PulseAudio

**macOS (Experimental):**
- macOS 14.4 (Sonoma) or later
- Python 3.10+
- Swift CLI helper binary (proctap-macos)
- Audio capture permission
- ⚠️ **EXPERIMENTAL:** Core Audio Process Tap API support implemented
- ⚠️ **REQUIREMENT:** Requires macOS 14.4+ for Process Tap API

---

## 🧰 Basic Usage (Callback API)

```python
from proctap import ProcTap, StreamConfig

def on_chunk(pcm: bytes, frames: int):
    print(f"Received {len(pcm)} bytes ({frames} frames)")

pid = 12345  # Target process ID

tap = ProcTap(pid, StreamConfig(), on_data=on_chunk)
tap.start()

input("Recording... Press Enter to stop.\n")

tap.close()
```

---

## 🔁 Async Usage (Async Generator)

```python
import asyncio
from proctap import ProcTap

async def main():
    tap = ProcTap(pid=12345)
    tap.start()

    async for chunk in tap.iter_chunks():
        print(f"PCM chunk size: {len(chunk)} bytes")

asyncio.run(main())
```

---

## 📄 API Overview

### `class ProcTap`

**Control Methods:**

| Method | Description |
|--------|-------------|
| `start()` | Start WASAPI per-process capture |
| `stop()` | Stop capture |
| `close()` | Release native resources |

**Data Access:**

| Method | Description |
|--------|-------------|
| `iter_chunks()` | Async generator yielding PCM chunks |
| `read(timeout=1.0)` | Synchronous: read one chunk (blocking) |

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `is_running` | bool | Check if capture is active |
| `pid` | int | Get target process ID |
| `config` | StreamConfig | Get stream configuration |

**Utility Methods:**

| Method | Description |
|--------|-------------|
| `set_callback(callback)` | Change or remove audio callback |
| `get_format()` | Get audio format info (dict) |

### Audio Format

**Native Backend Format** (Windows WASAPI, hardcoded in C++):

| Parameter | Value | Description |
|-----------|-------|-------------|
| Sample Rate | **44,100 Hz** | CD quality (fixed in C++) |
| Channels | **2** | Stereo (fixed in C++) |
| Bit Depth | **16-bit** | PCM format (fixed in C++) |

**Output Format Conversion** (v0.2.1+):

The `StreamConfig` class controls the **output format** through automatic conversion:
- Native format → converted to match your `StreamConfig` settings
- Supports sample rate conversion (e.g., 44.1kHz → 48kHz)
- Supports channel conversion (mono ↔ stereo)
- Supports bit depth conversion (8/16/24/32-bit)
- Zero overhead when formats match (automatic bypass)

Example:
```python
# Get audio as 48kHz mono 24-bit
config = StreamConfig(sample_rate=48000, channels=1, width=3)
tap = ProcTap(pid, config=config)
```

---

## 🎯 Use Cases

- 🎮 Record audio from one game only
- 🕶 Capture VRChat audio cleanly (without system sounds)
- 🎙 Feed high-SNR audio into AI recognition models
- 📹 Alternative to OBS "Application Audio Capture"
- 🎧 Capture DAW/app playback for analysis tools

---

## 📚 Example: Save to WAV

```python
from proctap import ProcTap
import wave

pid = 12345

wav = wave.open("output.wav", "wb")
wav.setnchannels(2)
wav.setsampwidth(2)  # 16-bit PCM
wav.setframerate(44100)  # Native format is 44.1 kHz

def on_data(pcm, frames):
    wav.writeframes(pcm)

with ProcTap(pid, on_data=on_data):
    input("Recording... Press Enter to stop.\n")

wav.close()
```

---

## 📚 Example: Synchronous Read API

```python
from proctap import ProcTap

tap = ProcTap(pid=12345)
tap.start()

try:
    while True:
        chunk = tap.read(timeout=1.0)  # Blocking read
        if chunk:
            print(f"Got {len(chunk)} bytes")
            # Process audio data...
        else:
            print("Timeout, no data")
except KeyboardInterrupt:
    pass
finally:
    tap.close()
```

---

## 🐧 Linux Example

```python
from proctap import ProcessAudioCapture, StreamConfig
import wave

pid = 12345  # Your target process ID

# Create WAV file
wav = wave.open("linux_capture.wav", "wb")
wav.setnchannels(2)
wav.setsampwidth(2)
wav.setframerate(44100)

def on_data(pcm, frames):
    wav.writeframes(pcm)

# Create stream config (Linux backend respects these settings)
config = StreamConfig(sample_rate=44100, channels=2)

try:
    with ProcessAudioCapture(pid, config=config, on_data=on_data):
        print("⚠️  Make sure the process is actively playing audio!")
        input("Recording... Press Enter to stop.\n")
finally:
    wav.close()
```

**Linux-specific requirements:**
- Install system package: `sudo apt-get install pulseaudio-utils` (provides `parec` command)
- Python dependency `pulsectl` is automatically installed with `pip install proc-tap`
- The target process must be actively playing audio
- See [examples/linux_basic.py](examples/linux_basic.py) for a complete example

---

## 🍎 macOS Example

```python
from proctap import ProcessAudioCapture, StreamConfig
import wave

pid = 12345  # Your target process ID

# Create WAV file
wav = wave.open("macos_capture.wav", "wb")
wav.setnchannels(2)
wav.setsampwidth(2)
wav.setframerate(48000)  # macOS backend default is 48 kHz

def on_data(pcm, frames):
    wav.writeframes(pcm)

# Create stream config (macOS backend respects these settings)
config = StreamConfig(sample_rate=48000, channels=2)

try:
    with ProcessAudioCapture(pid, config=config, on_data=on_data):
        print("⚠️  Make sure the process is actively playing audio!")
        print("⚠️  On first run, macOS will prompt for permission.")
        input("Recording... Press Enter to stop.\n")
finally:
    wav.close()
```

**macOS-specific requirements:**
- macOS 14.4 (Sonoma) or later
- Swift CLI helper binary (proctap-macos) - automatically built during installation if Swift toolchain available
- Audio capture permission - macOS will prompt on first run
- The target process must be actively playing audio
- See [examples/macos_basic.py](examples/macos_basic.py) for a complete example

**Building the Swift helper manually:**
```bash
cd swift/proctap-macos
swift build -c release
cp .build/release/proctap-macos ../../src/proctap/bin/
```

---

## 🏗 Build From Source

```bash
git clone https://github.com/m96-chan/ProcTap
cd ProcTap
pip install -e .
```

**Windows Build Requirements:**
- Visual Studio Build Tools
- Windows SDK
- CMake (if you modularize the C++ code)

**Linux:**
- No C++ compiler required (pure Python)
- System dependencies: `pulseaudio-utils` or `pipewire` with `libpipewire-0.3-dev`

**macOS:**
- No C++ compiler required (pure Python)
- Swift toolchain (optional, for building the Swift CLI helper)
- If Swift is not available, pre-built binary is included in the package

---

## 🤝 Contributing

Contributions are welcome! We have structured issue templates to help guide your contributions:

- 🐛 [**Bug Report**](../../issues/new?template=bug_report.yml) - Report bugs or unexpected behavior
- ✨ [**Feature Request**](../../issues/new?template=feature_request.yml) - Suggest new features or enhancements
- ⚡ [**Performance Issue**](../../issues/new?template=performance.yml) - Report performance problems or optimizations
- 🔧 [**Type Hints / Async**](../../issues/new?template=type_hints_async.yml) - Improve type annotations or async functionality
- 📚 [**Documentation**](../../issues/new?template=documentation.yml) - Improve docs, examples, or guides

**Special Interest:**
- PRs from WASAPI/C++ experts are especially appreciated
- **Linux backend improvements** (PulseAudio/PipeWire per-app isolation)
- **macOS backend testing** (Core Audio Process Tap on macOS 14.4+)
- Cross-platform testing and compatibility
- Performance profiling and optimization

---

## 📄 License

```
MIT License
```

---

## 👤 Author

**m96-chan**  
Windows Audio / VRChat Tools / Python / C++  
https://github.com/m96-chan

