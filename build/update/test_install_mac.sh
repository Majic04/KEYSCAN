#!/bin/bash
# Test (GitHub, Mac) : une « ancienne » KeyScan.app est remplacée par celle de l'image disque qu'on vient de construire.
#   bash build/update/test_install_mac.sh <image disque .dmg>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="$(sed -n 's/^APP_VERSION = "\([^"]*\)".*/\1/p' "$ROOT/desktop.py")"
WORK="$(mktemp -d)"; APP="$WORK/Applications/KeyScan.app"; mkdir -p "$WORK/Applications" "$WORK/maj"
ditto "$ROOT/dist/KeyScan.app" "$APP"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString 0.0.1" "$APP/Contents/Info.plist"   # se fait passer pour une ancienne version
cp "$1" "$WORK/maj/test.dmg"
sleep 2 & PID=$!                                   # « KeyScan » qui se ferme au bout de 2 secondes
bash "$ROOT/build/update/install_mac.sh" "$PID" "$WORK/maj/test.dmg" "$APP" 0
cat "$WORK/maj/installation.log"
INSTALLED="$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")"
check() { if eval "$2"; then echo "OK     $1"; else echo "ÉCHEC  $1"; FAIL=1; fi; }
FAIL=0
check "nouvelle version installée ($INSTALLED)" '[ "$INSTALLED" = "$VERSION" ]'
check "application exécutable" '[ -x "$APP/Contents/MacOS/KeyScan" ]'
check "signature intacte" 'codesign --verify --deep "$APP"'
check "ancienne version retirée" '[ ! -e "$APP.ancienne" ]'
check "image disque supprimée" '[ ! -e "$WORK/maj/test.dmg" ]'
check "image disque démontée" '! mount | grep -q keyscan-maj'
rm -rf "$WORK"
exit $FAIL
