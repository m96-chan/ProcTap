# 📡 ProcessAudioTap

ProcessAudioTap is a Python library with a high-performance C++ backend that enables per-process audio capture on Windows 10/11 (20H1+) using ActivateAudioInterfaceAsync.

It lets you capture audio from a specific process only — without system sounds or other app audio mixed in.  
Ideal for VRChat, games, DAWs, browsers, and AI audio analysis pipelines.

---

## 🚀 Features

- 🎧 **Capture audio from a single target process**  
  (VRChat, games, browsers, Discord, DAWs, streaming tools, etc.)

- ⚡ **Uses ActivateAudioInterfaceAsync (modern WASAPI)**  
  → More stable than legacy IAudioClient2 loopback approaches

- 🧵 **Low-latency, thread-safe C++ engine**  
  → 48 kHz / stereo / 10 ms buffer supported

- 🐍 **Python-friendly high-level API**
  - Callback-based streaming
  - Async generator streaming (`async for`)

- 🔌 **Native extension for high-throughput PCM delivery**

- 🪟 **Windows-only (10/11, 20H1+)**

---

## 📦 Installation

(Will be available after first PyPI release.)

```bash
pip install processaudiotap
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
from processaudiotap import ProcessAudioTap, StreamConfig

def on_chunk(pcm: bytes, frames: int):
    print(f"Received {len(pcm)} bytes ({frames} frames)")

pid = 12345  # Target process ID

tap = ProcessAudioTap(pid, StreamConfig(), on_data=on_chunk)
tap.start()

input("Recording... Press Enter to stop.\n")

tap.close()
```

---

## 🔁 Async Usage (Async Generator)

```python
import asyncio
from processaudiotap import ProcessAudioTap

async def main():
    tap = ProcessAudioTap(pid=12345)
    tap.start()

    async for chunk in tap.iter_chunks():
        print(f"PCM chunk size: {len(chunk)} bytes")

asyncio.run(main())
```

---

## 📄 API Overview

### `class ProcessAudioTap`

| Method | Description |
|--------|-------------|
| `start()` | Start WASAPI per-process capture |
| `stop()` | Stop capture |
| `close()` | Release native resources |
| `iter_chunks()` | Async generator yielding PCM chunks |

### `StreamConfig`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `sample_rate` | 48000 | Sampling rate |
| `channels` | 2 | Stereo |
| `frames_per_buffer` | 480 | 10 ms @ 48 kHz |

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
from processaudiotap import ProcessAudioTap
import wave

pid = 12345

wav = wave.open("output.wav", "wb")
wav.setnchannels(2)
wav.setsampwidth(2)  # 16-bit PCM
wav.setframerate(48000)

def on_data(pcm, frames):
    wav.writeframes(pcm)

with ProcessAudioTap(pid, on_data=on_data):
    input("Recording... Press Enter to stop.\n")

wav.close()
```

---

## 🏗 Build From Source

```bash
git clone https://github.com/m96-chan/ProcessAudioTap
cd ProcessAudioTap
pip install -e .
```

**Requirements:**
- Visual Studio Build Tools
- Windows SDK
- CMake (if you modularize the C++ code)

---

## 🔧 Project Structure

```
ProcessAudioTap/
├─ LICENSE
├─ README.md
├─ pyproject.toml
├─ setup.cfg
├─ setup.py
├─ src/
│  └─ processaudiotap/
│     ├─ __init__.py
│     ├─ core.py
│     ├─ _native.cpp
│     └─ _native.pyi
├─ examples/
│  └─ record_vrchat_to_wav.py
└─ .github/
   └─ workflows/
      └─ build-wheels.yml
```

---

## 🛠 GitHub Action (Wheel Build)

```yaml
name: Build and publish wheels

on:
  push:
    tags:
      - "v*.*.*"
  workflow_dispatch: {}

jobs:
  build-wheels:
    runs-on: windows-latest

    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install build tools
        run: |
          pip install --upgrade pip
          pip install build

      - name: Build wheel
        run: |
          python -m build --wheel

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: wheels-py${{ matrix.python-version }}
          path: dist/*.whl

  publish:
    needs: build-wheels
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/v')
    steps:
      - uses: actions/download-artifact@v4
        with:
          path: dist

      - name: Flatten wheels
        shell: bash
        run: |
          mkdir -p upload
          find dist -name '*.whl' -exec cp {} upload/ \;

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@v1.12.4
        with:
          user: __token__
          password: ${{ secrets.PYPI_API_TOKEN }}
          packages_dir: upload
```

---

## 🤝 Contributing

Contributions are welcome!

- Bug fixes
- Feature requests
- Performance improvements
- Type hints / async extension
- Documentation improvements

PRs from WASAPI/C++ experts are especially appreciated.

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
