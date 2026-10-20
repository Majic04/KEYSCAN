#!/bin/bash
# Prépare Tesseract autonome pour l'application Mac : binaire + bibliothèques + langues fra/eng/osd
# dans build/tesseract/, sans dépendre de Homebrew sur l'ordinateur de l'utilisateur.
# Prérequis (machine de construction) : brew install tesseract dylibbundler
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/build/tesseract"
rm -rf "$OUT" && mkdir -p "$OUT/libs" "$OUT/tessdata"

SRC="$(brew --prefix tesseract)/bin/tesseract"
cp "$SRC" "$OUT/tesseract"
chmod u+w "$OUT/tesseract"
# copie toutes les bibliothèques nécessaires et réécrit leurs chemins (relatifs au binaire)
dylibbundler -of -cd -b -x "$OUT/tesseract" -d "$OUT/libs" -p @executable_path/libs/

# langues : modèles officiels « tessdata » (meilleure précision que tessdata_fast)
for L in fra eng osd; do
  curl -fsSL -o "$OUT/tessdata/$L.traineddata" "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/$L.traineddata"
done

# les binaires modifiés doivent être re-signés (obligatoire sur processeur Apple)
codesign --force --sign - "$OUT"/libs/*.dylib
codesign --force --sign - "$OUT/tesseract"

# vérification : le binaire autonome fonctionne sans Homebrew dans le chemin
TESSDATA_PREFIX="$OUT/tessdata" env -i PATH=/usr/bin:/bin "$OUT/tesseract" --list-langs
otool -L "$OUT/tesseract" | grep -v -E "@executable_path|/usr/lib|/System" && { echo "Dépendance hors du paquet !"; exit 1; } || true
du -sh "$OUT"
