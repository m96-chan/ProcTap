<div align="center">

# 📡 ProcTap

**Per-Process Audio Capture for Windows**

[![PyPI version](https://img.shields.io/pypi/v/proc-tap?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/proc-tap/)
[![Python versions](https://img.shields.io/pypi/pyversions/proc-tap?logo=python&logoColor=white)](https://pypi.org/project/proc-tap/)
[![Downloads](https://img.shields.io/pypi/dm/proc-tap?logo=pypi&logoColor=white)](https://pypi.org/project/proc-tap/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue?logo=windows)](https://github.com/m96-chan/ProcTap)

[![Build wheels](https://github.com/m96-chan/ProcTap/actions/workflows/build-wheels.yml/badge.svg)](https://github.com/m96-chan/ProcTap/actions/workflows/build-wheels.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub stars](https://img.shields.io/github/stars/m96-chan/ProcTap?style=social)](https://github.com/m96-chan/ProcTap/stargazers)

---

ProcTap is a Python library with a high-performance C++ backend that enables per-process audio capture on Windows 10/11 (20H1+) using ActivateAudioInterfaceAsync.

**Capture audio from a specific process only** — without system sounds or other app audio mixed in.
Ideal for VRChat, games, DAWs, browsers, and AI audio analysis pipelines.

</div>

---

## 🚀 Features

- 🎧 **Capture audio from a single target process**  
  (VRChat, games, browsers, Discord, DAWs, streaming tools, etc.)

- ⚡ **Uses ActivateAudioInterfaceAsync (modern WASAPI)**  
  → More stable than legacy IAudioClient2 loopback approaches

- 🧵 **Low-latency, thread-safe C++ engine**
  → 44.1 kHz / stereo / 16-bit PCM format

- 🐍 **Python-friendly high-level API**
  - Callback-based streaming
  - Async generator streaming (`async for`)

- 🔌 **Native extension for high-throughput PCM delivery**

- 🪟 **Windows-only (10/11, 20H1+)**

---

## 📦 Installation

**From PyPI**:

```bash
pip install proc-tap
```

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

## 🛠 Requirements

- Windows 10 / 11 (20H1 or later recommended)
- Python 3.10+
- WASAPI support
- **No admin privileges required**  
  (Per-process loopback capture works with standard user permissions)

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

**Note:** The native extension uses a **fixed audio format** (hardcoded in C++):

| Parameter | Value | Description |
|-----------|-------|-------------|
| Sample Rate | **44,100 Hz** | CD quality (fixed) |
| Channels | **2** | Stereo (fixed) |
| Bit Depth | **16-bit** | PCM format (fixed) |

The `StreamConfig` class exists for API compatibility but does not change the native backend format.

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

## 🏗 Build From Source

```bash
git clone https://github.com/m96-chan/ProcTap
cd ProcTap
pip install -e .
```

**Requirements:**
- Visual Studio Build Tools
- Windows SDK
- CMake (if you modularize the C++ code)

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
- Help with cross-platform compatibility research
- Performance profiling and optimization

---

## 📄 License

```
MIT License
```

---

## 👤 Author

**Yusuke Harada (m96-chan)**  
Windows Audio / VRChat Tools / Python / C++  
https://github.com/m96-chan

