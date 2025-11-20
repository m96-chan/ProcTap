# Experimental macOS Backends (Archived)

This directory contains experimental macOS audio capture backends that are not used in production.

## Files

### macos.py
- **Description**: Core Audio Process Tap implementation using Swift CLI helper
- **Target**: macOS 14.4+ (Sonoma)
- **Status**: Experimental, superseded by ScreenCaptureKit backend
- **Issue**: Requires AMFI disable on Apple Silicon

### macos_native.py
- **Description**: Native C extension backend for Core Audio Process Tap
- **Target**: macOS 14.4+ (Sonoma)
- **Status**: Experimental, Phase 4 optimization attempt
- **Performance Goal**: <500ms initial latency
- **Issue**: Requires native compilation and AMFI disable on Apple Silicon

### _native_macos.m
- **Description**: Objective-C source code for native macOS extension
- **Target**: macOS 14.4+ (Sonoma)
- **Status**: Experimental, not built in production
- **Issue**: Requires native compilation and AMFI disable on Apple Silicon

## Why Archived?

These backends were developed during the investigation of per-process audio capture on macOS. They are archived because:

1. **ScreenCaptureKit is the recommended solution**: Works on macOS 13+ with simple TCC permissions
2. **AMFI limitations**: These implementations require disabling AMFI on Apple Silicon
3. **Complexity**: Native extensions add build complexity without significant benefits
4. **Stability**: PyObjC fallback provides adequate compatibility for older systems

## Production Backends (macOS)

The production codebase uses:

1. **ScreenCaptureKit** (Recommended): `src/proctap/backends/macos_screencapture.py`
   - macOS 13+ (Ventura)
   - BundleID-based capture
   - Swift CLI helper
   - No AMFI issues on Apple Silicon

2. **PyObjC** (Fallback): `src/proctap/backends/macos_pyobjc.py`
   - macOS 14.4+ (Sonoma)
   - Core Audio Process Tap via PyObjC
   - IOProc callback limitations
   - Fallback only when ScreenCaptureKit unavailable

## Related Investigation

See `archive/apple-silicon-investigation-20251120/` for detailed investigation notes on Apple Silicon AMFI limitations and Process Tap API exploration.
