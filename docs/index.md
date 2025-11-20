# ProcTap

**Cross-Platform Per-Process Audio Capture**

[![PyPI version](https://img.shields.io/pypi/v/proc-tap?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/proc-tap/)
[![Python versions](https://img.shields.io/pypi/pyversions/proc-tap?logo=python&logoColor=white)](https://pypi.org/project/proc-tap/)
[![Downloads](https://img.shields.io/pypi/dm/proc-tap?logo=pypi&logoColor=white)](https://pypi.org/project/proc-tap/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/m96-chan/ProcTap/blob/main/LICENSE)

---

ProcTap is a cross-platform Python library that enables **per-process audio capture** with platform-optimized backends:

- **Windows**: WASAPI Process Loopback (C++ native extension)
- **Linux**: PipeWire Native / PulseAudio (fully supported)
- **macOS**: ScreenCaptureKit (officially supported, v0.4.0+)

It lets you capture audio from a **specific process only** — without system sounds or other app audio mixed in.

## Key Features

- 🎧 **Per-Process Audio Isolation** - Capture from a single target process (games, browsers, DAWs, etc.)
- 🌍 **Cross-Platform** - Windows 10/11+ | Linux (PipeWire/PulseAudio) | macOS 13+
- ⚡ **Platform-Optimized Backends** - WASAPI (Windows), PipeWire/PulseAudio (Linux), ScreenCaptureKit (macOS)
- 🧵 **Low-Latency Audio Engine** - 10-15ms latency across all platforms
- 🐍 **Python-Friendly API** - Callback-based and async iterator patterns
- 🔌 **Native Performance** - C++ extension (Windows), native APIs (Linux/macOS)

## Quick Example

```python
from proctap import ProcessAudioCapture
import wave

# Open WAV file for writing
wav = wave.open("output.wav", "wb")
wav.setnchannels(2)
wav.setsampwidth(2)  # 16-bit PCM
wav.setframerate(44100)

# Callback to write audio data
def on_data(pcm, frames):
    wav.writeframes(pcm)

# Start capturing from process ID 12345
with ProcessAudioCapture(pid=12345, on_data=on_data):
    input("Recording... Press Enter to stop.\n")

wav.close()
```

## Installation

```bash
pip install proc-tap
```

For development installation and building from source, see the [Installation Guide](getting-started/installation.md).

## Use Cases

- 🎮 Record audio from one game only
- 🕶 Capture VRChat audio cleanly (without system sounds)
- 🎙 Feed high-SNR audio into AI recognition models
- 📹 Alternative to OBS "Application Audio Capture"
- 🎧 Capture DAW/app playback for analysis tools

## Requirements

### Windows (Fully Supported)
- **OS**: Windows 10 / 11 (20H1 or later)
- **Python**: 3.10+
- **WASAPI**: Built into Windows
- **Privileges**: No administrator rights required

### Linux (Fully Supported)
- **OS**: Linux with PulseAudio or PipeWire
- **Python**: 3.10+
- **System Packages**: `pulseaudio-utils` or `pipewire`
- **Auto-detection**: Graceful fallback between backends

### macOS (Officially Supported - v0.4.0+)
- **OS**: macOS 13.0 (Ventura) or later
- **Python**: 3.10+
- **Backend**: ScreenCaptureKit (bundleID-based)
- **Permissions**: Screen Recording (automatically prompted)
- **Requirements**: Swift toolchain for building helper binary

## Next Steps

- [Installation Guide](getting-started/installation.md) - Install ProcTap
- [Quick Start](getting-started/quickstart.md) - Get started in 5 minutes
- [API Reference](api/processaudiotap.md) - Detailed API documentation
- [Examples](getting-started/examples.md) - More usage examples

## Support

- 🐛 [Report Bugs](https://github.com/m96-chan/ProcTap/issues/new?template=bug_report.yml)
- ✨ [Request Features](https://github.com/m96-chan/ProcTap/issues/new?template=feature_request.yml)
- 💬 [Discussions](https://github.com/m96-chan/ProcTap/discussions)
- 📖 [GitHub Repository](https://github.com/m96-chan/ProcTap)

## License

ProcTap is released under the [MIT License](https://github.com/m96-chan/ProcTap/blob/main/LICENSE).
