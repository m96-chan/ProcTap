# Changelog

All notable changes to ProcTap will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
