# macOS Process Tap helper — CI signing & notarization

The PID-based Process Tap backend ships a Swift helper (`proctap-helper.app`)
that must be **Developer ID signed and notarized** to capture audio on end-user
machines without disabling SIP/AMFI. The release workflows
([`publish-pypi.yml`](../.github/workflows/publish-pypi.yml),
[`release-testpypi.yml`](../.github/workflows/release-testpypi.yml)) build, sign,
notarize and stage the `.app` into the wheel via
[`src/proctap/swift/proctap-helper/ci_sign_notarize.sh`](../src/proctap/swift/proctap-helper/ci_sign_notarize.sh).

Signing runs only on version tags / manual dispatch (never on pull requests), so
secrets are never exposed to untrusted PRs. When the secrets are absent the step
is skipped and the wheel simply ships without the Process Tap helper —
ScreenCaptureKit (bundleID-based) remains the macOS backend.

## Required repository secrets

Settings → Secrets and variables → Actions (same set as the maintainer's other
Developer ID projects):

| Secret | Value |
|---|---|
| `BUILD_CERTIFICATE_BASE64` | `base64 -i DeveloperID.p12` (Developer ID Application cert + key) |
| `P12_PASSWORD` | the `.p12` export password |
| `KEYCHAIN_PASSWORD` | any random string (temporary CI keychain) |
| `ASC_KEY_ID` | App Store Connect API **Key ID** |
| `ASC_ISSUER_ID` | App Store Connect API **Issuer ID** |
| `ASC_KEY_P8_BASE64` | `base64 -i AuthKey_XXXX.p8` |

Notarization uses the App Store Connect API key (`notarytool --key`), so no
Apple ID / app-specific password is needed.

## What the CI step does

1. Imports the Developer ID cert into a throwaway keychain.
2. `swift build -c release`, assembles `proctap-helper.app` (+ `Info.plist`).
3. `codesign` with Developer ID, hardened runtime, `proctap-helper.entitlements`.
4. `notarytool submit --wait` + `stapler staple` + `stapler validate`.
5. Copies the signed/stapled `.app` to `src/proctap/bin/proctap-helper.app`, so
   `setup.py` includes it in the wheel (`package_data`).

## End-user requirement (runtime)

Even with a notarized helper, each user must grant **Screen Recording**
permission to `proctap-helper` once (System Settings › Privacy & Security ›
Screen Recording) — this gates the tapped audio content. The backend launches
the helper via LaunchServices so it registers there automatically on first run.

## Local dry run

You can exercise the same script locally with the maintainer's assets:

```bash
BUILD_CERTIFICATE_BASE64="$(base64 -i /path/DeveloperID.p12)" \
P12_PASSWORD="$(cat /path/p12_password.txt)" \
KEYCHAIN_PASSWORD=whatever \
ASC_KEY_ID=PSNK88F46K \
ASC_ISSUER_ID="$(cat /path/issuer.txt)" \
ASC_KEY_P8_BASE64="$(base64 -i /path/AuthKey_PSNK88F46K.p8)" \
  bash src/proctap/swift/proctap-helper/ci_sign_notarize.sh
```
