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

# fichiers de configuration de Tesseract (indispensables : sortie « tsv » mot par mot utilisée par KeyScan)
cp -R "$(brew --prefix tesseract)/share/tessdata/configs" "$OUT/tessdata/"
[ -d "$(brew --prefix tesseract)/share/tessdata/tessconfigs" ] && cp -R "$(brew --prefix tesseract)/share/tessdata/tessconfigs" "$OUT/tessdata/"
# langues : modèles officiels « tessdata » (meilleure précision que tessdata_fast)
for L in fra eng osd; do
  curl -fsSL -o "$OUT/tessdata/$L.traineddata" "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/$L.traineddata"
done

# les binaires modifiés doivent être re-signés (obligatoire sur processeur Apple)
codesign --force --sign - "$OUT"/libs/*.dylib
codesign --force --sign - "$OUT/tesseract"

# vérification : le binaire autonome fonctionne sans Homebrew dans le chemin
TESSDATA_PREFIX="$OUT/tessdata" env -i PATH=/usr/bin:/bin "$OUT/tesseract" --list-langs
# aucune bibliothèque ne doit encore pointer vers Homebrew (la 1re ligne d'otool est le nom du fichier)
if otool -L "$OUT/tesseract" "$OUT"/libs/*.dylib | grep -E "^\s" | grep -q -E "/opt/homebrew|/usr/local/(opt|Cellar)"; then
  echo "Dépendance hors du paquet :"; otool -L "$OUT/tesseract" "$OUT"/libs/*.dylib | grep -E "/opt/homebrew|/usr/local/(opt|Cellar)"; exit 1
fi
# essai réel : lecture d'une image en sortie « tsv », comme KeyScan
python3 -c "from PIL import Image, ImageDraw; im=Image.new('L',(600,120),255); ImageDraw.Draw(im).text((20,40),'Master robotique',fill=0); im.save('/tmp/t.png')" 2>/dev/null \
  && TESSDATA_PREFIX="$OUT/tessdata" env -i PATH=/usr/bin:/bin "$OUT/tesseract" /tmp/t.png /tmp/t -l fra+eng tsv \
  && grep -c . /tmp/t.tsv && grep -i "master" /tmp/t.tsv
du -sh "$OUT"
