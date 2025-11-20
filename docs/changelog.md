# Changelog

All notable changes to ProcTap will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2025-01-20

### 🎉 Major Features

#### macOS ScreenCaptureKit Backend (Official Support)
- **Added** ScreenCaptureKit backend for macOS 13.0+ (Ventura and later)
- **Apple Silicon Compatible**: No AMFI/SIP hacks required
- **Simple Permissions**: Screen Recording only (no Microphone/TCC complexity)
- **BundleID-Based Capture**: Automatically converts PID to bundleID
- **Low Latency**: ~10-15ms audio capture performance
- **Stable API**: Uses official Apple ScreenCaptureKit framework

### Changed

#### macOS Backend Architecture
- **ScreenCaptureKit is now the RECOMMENDED backend** for macOS
- PyObjC backend moved to fallback (has IOProc callback issues)
- Swift CLI helper and C extension moved to `experimental/` directory
- macOS support upgraded from "Experimental" to "Officially Supported"

#### Project Structure
- **Relocated Swift helper**: Moved from `swift/proctap-macos/` to `src/proctap/swift/screencapture-audio/`
- **Added MANIFEST.in**: Ensures Swift helper is included in source distributions
- **Archive directory**: Created `archive/apple-silicon-investigation-20251120/` for historical investigation docs

### Fixed

#### Type Safety
- Resolved all mypy type errors across the codebase
- Fixed type hints in macOS backends (ScreenCaptureKit, PyObjC, Native)
- Improved type annotations for better IDE support and static analysis

### Documentation

#### New Documentation
- **macOS Investigation Archive**: Comprehensive AMFI/SIP investigation docs in `archive/`
- **C Extension Investigation**: Detailed findings in `docs/experimental/c_extension_investigation/`
- **Implementation Summaries**: Session summaries and TCC implementation guides

#### Updated Documentation
- README.md: Updated platform support table (macOS now "Officially Supported")
- CLAUDE.md: Updated macOS backend information and recommendations
- CI/CD workflows: Updated for ScreenCaptureKit backend builds

### Technical Details

#### Backend Selection Priority (macOS)
1. **ScreenCaptureKit** (Recommended - macOS 13+)
2. **PyObjC** (Fallback - has IOProc callback issues)
3. **Swift CLI / C Extension** (Archived - experimental only)

#### Build System
- CI/CD workflows configured for ScreenCaptureKit backend
- Swift helper automatically built during installation (if Swift toolchain available)
- No breaking changes to existing Windows/Linux backends

### Migration Guide

#### For macOS Users
If you were using experimental backends:
- **Recommended**: Switch to ScreenCaptureKit backend (default in v0.4.0)
- **Requirements**: macOS 13.0+ and Screen Recording permission
- **No code changes needed**: Existing code works with new backend
- **Bundle ID capture**: Automatically handles PID → bundleID conversion

#### Breaking Changes
- None for Windows/Linux users
- macOS: Experimental Swift CLI moved to `experimental/` (still available but not recommended)

---

## [0.3.1] - 2025-01-XX

### Fixed
- Documentation fixes and clarifications

## [0.3.0] - 2025-01-XX

### Added
- Full Linux support with PipeWire/PulseAudio backends
- Per-process audio isolation on Linux
- Graceful fallback chain: Native → PipeWire → PulseAudio

## [0.2.1] - 2025-01-XX

### Added
- Audio format conversion support
- Sample rate, channel, and bit depth conversion
- High-quality resampling with libsamplerate (optional)

## [0.2.0] - 2025-01-XX

### Added
- Linux backend implementation (experimental)
- macOS backend investigation started

## [0.1.1] - 2025-01-XX

### Added
- Complete PyPI metadata (classifiers, keywords, project URLs)
- Comprehensive MkDocs documentation site
- GitHub issue templates (Bug Report, Feature Request, Performance, Type Hints, Documentation)

### Changed
- Renamed package from `processaudiotap` to `proctap` (PyPI: `proc-tap`)
- Improved README with status badges and structured contributing section
- Updated all documentation to English

### Fixed
- PyPI badges now display correctly with proper classifiers
- TestPyPI installation instructions with correct index URLs
- GitHub Actions workflows split into build (Windows) and publish (Linux) jobs

## [0.1.0] - 2025-01-XX

### Added
- Initial release
- Per-process audio capture using WASAPI `ActivateAudioInterfaceAsync`
- C++ native extension for high-performance audio capture
- Python API with callback and async iterator patterns
- Support for Windows 10/11 (20H1+)
- Support for Python 3.10, 3.11, 3.12, 3.13
- Fixed audio format: 44.1 kHz, stereo, 16-bit PCM
- Example scripts for recording to WAV
- Discord bot integration (contrib module)
- GitHub Actions workflows for building wheels

### Technical Details
- Native-only architecture (no Python fallback)
- Thread-safe audio capture
- Low-latency streaming (10ms buffer)
- No administrator privileges required

## Upcoming Features

See our [GitHub Issues](https://github.com/m96-chan/ProcTap/issues) for planned features and improvements.

### Planned for Future Releases

- [ ] Configurable audio format (sample rate, channels, bit depth)
- [ ] Multiple process capture simultaneously
- [ ] Audio effects and filters
- [ ] Real-time audio analysis utilities
- [ ] More example integrations (OBS, streaming tools)
- [ ] Performance optimizations
- [ ] Comprehensive test suite

## Contributing

We welcome contributions! See our [Contributing Guide](contributing/development.md) for details.

[0.1.1]: https://github.com/m96-chan/ProcTap/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/m96-chan/ProcTap/releases/tag/v0.1.0
