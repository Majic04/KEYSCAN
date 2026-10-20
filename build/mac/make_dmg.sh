#!/bin/bash
# Finalise KeyScan.app (permissions, signature ad hoc) et crée l'image disque KeyScan-Mac.dmg.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="$ROOT/dist/KeyScan.app"
ARCH="$(uname -m)"
[ "$ARCH" = "arm64" ] && NAME="KeyScan-Mac-AppleSilicon" || NAME="KeyScan-Mac-Intel"

# Tesseract embarqué : doit rester exécutable
find "$APP" -path "*tesseract/tesseract" -type f -exec chmod +x {} \;
# signature ad hoc de l'ensemble (obligatoire pour lancer du code sur processeur Apple)
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP" && echo "Signature ad hoc vérifiée"

STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$ROOT/dist/$NAME.dmg"
hdiutil create -volname "KeyScan" -srcfolder "$STAGE" -ov -format ULFO "$ROOT/dist/$NAME.dmg"
ls -lh "$ROOT/dist/$NAME.dmg"
echo "DMG=$ROOT/dist/$NAME.dmg" >> "${GITHUB_ENV:-/dev/null}"
