#!/bin/bash
# Sign the already-built proctap-helper.app using a Developer ID identity stored
# in a .p12 (PKCS#12) file. This works from a non-interactive session (where the
# login keychain's private key is inaccessible -> errSecInternalComponent) by
# importing the .p12 into a throwaway keychain, signing, then deleting it.
#
# The .p12 password is read from a FILE (never passed on the command line or
# printed) so it does not leak into shell history / logs.
#
# Usage:
#   ./sign_with_p12.sh <path-to.p12> <path-to-password-file>
#
# Create the password file privately, e.g. in your own Terminal:
#   printf '%s' 'YOUR_P12_PASSWORD' > ~/.proctap_p12_pw && chmod 600 ~/.proctap_p12_pw
#
# The .p12 must contain the "Developer ID Application" certificate AND its
# private key (export the identity from Keychain Access as .p12).

set -euo pipefail

cd "$(dirname "$0")"

P12_PATH="${1:?usage: sign_with_p12.sh <p12> <password-file>}"
PW_FILE="${2:?usage: sign_with_p12.sh <p12> <password-file>}"
ENTITLEMENTS="proctap-helper.entitlements"

[[ -f "$P12_PATH" ]] || { echo "ERROR: .p12 not found: $P12_PATH" >&2; exit 1; }
[[ -f "$PW_FILE" ]]  || { echo "ERROR: password file not found: $PW_FILE" >&2; exit 1; }

APP_BUNDLE="$(swift build -c release --show-bin-path)/proctap-helper.app"
[[ -d "$APP_BUNDLE" ]] || { echo "ERROR: build first (./build.sh --no-sign): $APP_BUNDLE" >&2; exit 1; }

P12_PW="$(cat "$PW_FILE")"

# Throwaway keychain (auto-cleaned on exit).
TMPDIR_KC="$(mktemp -d)"
KEYCHAIN="${TMPDIR_KC}/proctap-signing.keychain-db"
KC_PW="proctap-$$-temp"

cleanup() {
    security delete-keychain "$KEYCHAIN" 2>/dev/null || true
    rm -rf "$TMPDIR_KC"
}
trap cleanup EXIT

echo "==> Creating temporary keychain"
security create-keychain -p "$KC_PW" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KC_PW" "$KEYCHAIN"

echo "==> Importing .p12"
security import "$P12_PATH" -k "$KEYCHAIN" -P "$P12_PW" \
    -T /usr/bin/codesign -T /usr/bin/security
# Allow codesign to use the key without an interactive prompt.
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KC_PW" "$KEYCHAIN" >/dev/null

# Prepend our keychain to the search list so codesign can find the identity.
ORIG_KEYCHAINS="$(security list-keychains -d user | sed -e 's/^[[:space:]]*//' -e 's/"//g')"
# shellcheck disable=SC2086
security list-keychains -d user -s "$KEYCHAIN" $ORIG_KEYCHAINS

restore_keychains() {
    # shellcheck disable=SC2086
    security list-keychains -d user -s $ORIG_KEYCHAINS 2>/dev/null || true
    cleanup
}
trap restore_keychains EXIT

IDENTITY="$(security find-identity -v -p codesigning "$KEYCHAIN" \
    | awk -F'"' '/Developer ID Application/{print $2; exit}')"
[[ -n "$IDENTITY" ]] || { echo "ERROR: no Developer ID Application identity in .p12" >&2; exit 1; }

echo "==> Signing with: $IDENTITY"
codesign --force \
         --sign "$IDENTITY" \
         --keychain "$KEYCHAIN" \
         --entitlements "$ENTITLEMENTS" \
         --options runtime \
         --timestamp \
         "$APP_BUNDLE"

echo "==> Verifying"
codesign --verify --strict --verbose=2 "$APP_BUNDLE"
codesign -dv --verbose=4 "$APP_BUNDLE" 2>&1 | grep -E "Identifier|Authority|TeamIdentifier|Runtime" || true

echo ""
echo "Signed: $APP_BUNDLE"
