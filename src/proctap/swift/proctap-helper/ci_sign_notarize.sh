#!/bin/bash
# CI: build, Developer ID sign, notarize + staple proctap-helper.app, and stage
# it into the Python package (src/proctap/bin/proctap-helper.app) for wheel
# packaging.
#
# Driven entirely by environment variables (GitHub Actions secrets), so it runs
# only on tags / manual dispatch — never on untrusted pull requests.
#
#   Signing:
#     BUILD_CERTIFICATE_BASE64   base64 of the Developer ID Application .p12
#     P12_PASSWORD               .p12 export password
#     KEYCHAIN_PASSWORD          any random string (temporary keychain)
#   Notarization (App Store Connect API key):
#     ASC_KEY_ID                 API Key ID
#     ASC_ISSUER_ID              API Issuer ID
#     ASC_KEY_P8_BASE64          base64 of AuthKey_XXXX.p8
#
# RUNNER_TEMP defaults to a mktemp dir when run outside GitHub Actions.

set -euo pipefail

cd "$(dirname "$0")"

: "${BUILD_CERTIFICATE_BASE64:?}" ; : "${P12_PASSWORD:?}" ; : "${KEYCHAIN_PASSWORD:?}"
: "${ASC_KEY_ID:?}" ; : "${ASC_ISSUER_ID:?}" ; : "${ASC_KEY_P8_BASE64:?}"
: "${RUNNER_TEMP:=$(mktemp -d)}"

ENTITLEMENTS="proctap-helper.entitlements"
INFO_PLIST="Info.plist"
KEYCHAIN="$RUNNER_TEMP/proctap-signing.keychain-db"

cleanup() { security delete-keychain "$KEYCHAIN" 2>/dev/null || true; }
trap cleanup EXIT

echo "==> Import Developer ID cert into a temporary keychain"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
echo "$BUILD_CERTIFICATE_BASE64" | base64 --decode > "$RUNNER_TEMP/cert.p12"
security import "$RUNNER_TEMP/cert.p12" -k "$KEYCHAIN" -P "$P12_PASSWORD" \
    -T /usr/bin/codesign -T /usr/bin/security
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN" >/dev/null
# shellcheck disable=SC2046
security list-keychains -d user -s "$KEYCHAIN" $(security list-keychains -d user | sed -e 's/^[[:space:]]*//' -e 's/"//g')

IDENTITY="$(security find-identity -v -p codesigning "$KEYCHAIN" \
    | awk -F'"' '/Developer ID Application/{print $2; exit}')"
[ -n "$IDENTITY" ] || { echo "ERROR: no Developer ID Application identity in cert" >&2; exit 1; }
echo "    identity: $IDENTITY"

echo "==> swift build + bundle"
swift build -c release
BIN="$(swift build -c release --show-bin-path)"
APP="$BIN/proctap-helper.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN/proctap-helper" "$APP/Contents/MacOS/proctap-helper"
cp "$INFO_PLIST" "$APP/Contents/Info.plist"

echo "==> codesign (Developer ID, hardened runtime)"
codesign --force --sign "$IDENTITY" --keychain "$KEYCHAIN" \
    --entitlements "$ENTITLEMENTS" --options runtime --timestamp "$APP"
codesign --verify --strict --verbose=2 "$APP"

echo "==> notarize + staple"
KEYP8="$RUNNER_TEMP/AuthKey.p8"
echo "$ASC_KEY_P8_BASE64" | base64 --decode > "$KEYP8"
ZIP="$RUNNER_TEMP/proctap-helper.zip"
ditto -c -k --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" \
    --key "$KEYP8" --key-id "$ASC_KEY_ID" --issuer "$ASC_ISSUER_ID" --wait
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

echo "==> stage into package bin/ for wheel packaging"
DEST="../../bin/proctap-helper.app"
rm -rf "$DEST"
mkdir -p "../../bin"
cp -R "$APP" "$DEST"

echo "Done: signed + notarized $DEST"
