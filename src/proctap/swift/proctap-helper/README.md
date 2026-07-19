# proctap-helper — PID-based Core Audio Process Tap helper (macOS)

A Swift CLI that captures audio from a **specific PID** using the Core Audio
Process Tap API (`AudioHardwareCreateProcessTap` + `CATapDescription`), streaming
raw PCM to stdout. This gives macOS the same per-process (PID) capture semantics
as the Windows (WASAPI) and Linux (PipeWire/PulseAudio) backends, instead of the
bundleID-based ScreenCaptureKit backend.

Revived from `archive/apple-silicon-investigation-20251120/` for issue #57.

## Requirements

- macOS 14.4+ (Process Tap API; developed/verified on macOS 15.6)
- A valid **Developer ID Application** signature (see below) — the API works on
  a normal SIP/AMFI-enabled system, it just requires a validly signed binary.
- TCC consent at runtime (Microphone + Screen Recording), granted once.

## Build & sign

```bash
# Build + bundle + sign (auto-detects a Developer ID Application identity):
./build.sh

# Or sign headlessly from a .p12 (works in non-interactive sessions):
./build.sh --no-sign
./sign_with_p12.sh /path/to/DeveloperID.p12 /path/to/password-file

# Output: .build/<arch>-apple-macosx/release/proctap-helper.app
```

Run: `proctap-helper.app/Contents/MacOS/proctap-helper <PID>` → raw PCM on stdout
(48 kHz, 2 ch, float32 interleaved), diagnostics on stderr.

For redistribution, notarize + staple the `.app` (see build.sh footer).

## What was fixed reviving it (all in `Sources/proctap-helper/main.swift`)

The archived helper reached "implementation complete, blocked only by signing".
After signing it still failed; the real blockers were:

1. **Wrong selector FourCC.** It used `'pid2'` (`0x70696432`) for
   `kAudioHardwarePropertyTranslatePIDToProcessObject`; the correct code is
   `'id2p'`. This — not AMFI — caused the `status=2003332927` ("wat?") failure.
   Now uses the named SDK constant.
2. **Fragile Objective-C runtime construction of `CATapDescription`** (via
   `unsafeBitCast`/`perform`) crashed with a bus error on macOS 15. `CATapDescription`
   is public since macOS 14.4, so it is now constructed directly:
   `CATapDescription(stereoMixdownOfProcesses:)`.
3. **Swift 6 concurrency trap.** The IOProc block inherited `@main`'s MainActor
   isolation and hit `_dispatch_assert_queue_fail` when CoreAudio invoked it on
   its own dispatch queue. Fixed by building in **Swift 5 language mode**
   (`Package.swift` → `swiftLanguageModes: [.v5]`).

With a Developer ID signature these fixes let the full pipeline run on Apple
Silicon **without disabling SIP or AMFI**: translate-PID → Process Tap →
Aggregate Device → IOProc streams PCM to stdout at 48 kHz/2 ch/float32.

## Verifying real audio content (interactive)

Automated/headless runs stream buffers at the correct rate but may capture
silence if the OS isn't actually rendering the target's audio in that session.
Verify from a normal Terminal while real audio plays:

```bash
APP=".build/$(uname -m)-apple-macosx/release/proctap-helper.app/Contents/MacOS/proctap-helper"
# Play something audible (Music.app, a browser video, etc.), find its PID, then:
"$APP" <PID> > /tmp/cap.f32
# Convert float32 PCM -> WAV and listen:
ffmpeg -f f32le -ar 48000 -ac 2 -i /tmp/cap.f32 /tmp/cap.wav && afplay /tmp/cap.wav
```

Grant the Microphone + Screen Recording prompts the first time.
