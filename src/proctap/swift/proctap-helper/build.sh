#!/bin/bash
# Build, bundle and (Developer ID) sign the ProcTap Process Tap helper.
#
# The Core Audio Process Tap API works on a normal (SIP/AMFI-enabled) system as
# long as the binary is validly signed with a Developer ID and the user grants
# the audio-capture TCC permission at runtime. This script produces a signed
# .app bundle ready for that.
#
# Usage:
#   ./build.sh                      # build + bundle + sign (auto-detect Developer ID)
#   CODESIGN_IDENTITY="Developer ID Application: NAME (TEAMID)" ./build.sh
#   ./build.sh --no-sign            # build + bundle only (ad-hoc, for local dev)
#
# Output: .build/<arch>-apple-macosx/release/proctap-helper.app

set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="proctap-helper"
BUNDLE_ID="com.proctap.helper"
ENTITLEMENTS="proctap-helper.entitlements"
INFO_PLIST="Info.plist"

SIGN=1
if [[ "${1:-}" == "--no-sign" ]]; then
    SIGN=0
fi

echo "==> swift build -c release"
swift build -c release

# Resolve the release build dir (architecture-specific).
BIN_PATH="$(swift build -c release --show-bin-path)"
APP_BUNDLE="${BIN_PATH}/${APP_NAME}.app"
MACOS_DIR="${APP_BUNDLE}/Contents/MacOS"

echo "==> Assembling app bundle: ${APP_BUNDLE}"
rm -rf "${APP_BUNDLE}"
mkdir -p "${MACOS_DIR}"
cp "${BIN_PATH}/${APP_NAME}" "${MACOS_DIR}/${APP_NAME}"
cp "${INFO_PLIST}" "${APP_BUNDLE}/Contents/Info.plist"

if [[ "${SIGN}" -eq 0 ]]; then
    echo "==> Ad-hoc signing (--no-sign): local dev only, not distributable"
    codesign --force --sign - --entitlements "${ENTITLEMENTS}" "${APP_BUNDLE}"
    codesign -dv "${APP_BUNDLE}" 2>&1 | grep -E "Identifier|Signature" || true
    echo "Done (ad-hoc): ${APP_BUNDLE}"
    exit 0
fi

# Auto-detect a Developer ID Application identity unless one is provided.
IDENTITY="${CODESIGN_IDENTITY:-}"
if [[ -z "${IDENTITY}" ]]; then
    IDENTITY="$(security find-identity -v -p codesigning \
        | awk -F'"' '/Developer ID Application/{print $2; exit}')"
fi

if [[ -z "${IDENTITY}" ]]; then
    echo "ERROR: No 'Developer ID Application' identity found." >&2
    echo "       Set CODESIGN_IDENTITY=... or run with --no-sign for local dev." >&2
    exit 1
fi

echo "==> Signing with: ${IDENTITY}"
codesign --force \
         --sign "${IDENTITY}" \
         --entitlements "${ENTITLEMENTS}" \
         --options runtime \
         --timestamp \
         "${APP_BUNDLE}"

echo "==> Verifying signature"
codesign --verify --strict --verbose=2 "${APP_BUNDLE}"
codesign -dv --verbose=4 "${APP_BUNDLE}" 2>&1 | grep -E "Identifier|Authority|TeamIdentifier|Runtime" || true

echo ""
echo "Signed bundle: ${APP_BUNDLE}"
echo "Executable:    ${MACOS_DIR}/${APP_NAME}"
echo ""
echo "Next (for redistribution): notarize with"
echo "  xcrun notarytool submit <zip> --keychain-profile <profile> --wait"
echo "  xcrun stapler staple \"${APP_BUNDLE}\""
