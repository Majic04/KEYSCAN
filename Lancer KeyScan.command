#!/bin/bash
# Double-cliquez sur ce fichier pour lancer KeyScan (macOS).
# Laissez la fenêtre du Terminal ouverte pendant l'utilisation ; fermez-la pour arrêter KeyScan.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
pause(){ echo; read -n 1 -s -r -p "Appuyez sur une touche pour fermer…"; echo; }
clear
echo "KeyScan — démarrage"
echo

# --- 1. Python 3.9 ou plus récent (Homebrew, Miniconda/Anaconda, python.org…)
PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         "$HOME/miniconda3/bin/python3" "$HOME/anaconda3/bin/python3" "$HOME/opt/anaconda3/bin/python3" \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if [ -x "$c" ] && "$c" -c 'import sys,venv; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ] && xcode-select -p >/dev/null 2>&1 && /usr/bin/python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
  PY=/usr/bin/python3
fi
if [ -z "$PY" ]; then
  echo "Python 3 est introuvable."
  echo "Installez-le depuis https://www.python.org/downloads/ puis relancez ce fichier."
  pause; exit 1
fi

# --- 2. Tesseract (lecture des scans et photos) + langue française
if ! command -v tesseract >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installation de Tesseract (lecture des scans), une seule fois…"
    brew install tesseract tesseract-lang
  else
    echo "⚠  Tesseract n'est pas installé : les PDF texte seront lus, mais pas les scans ni les photos."
    echo "   Pour l'installer : https://brew.sh puis, dans le Terminal :  brew install tesseract tesseract-lang"
    echo
  fi
elif ! tesseract --list-langs 2>/dev/null | grep -qx "fra"; then
  command -v brew >/dev/null 2>&1 && { echo "Ajout du français à Tesseract…"; brew install tesseract-lang; }
fi

# --- 3. environnement Python local (.venv) et bibliothèques — rapide si déjà installées
if [ ! -x .venv/bin/python ]; then
  echo "Création de l'environnement Python local, une seule fois…"
  rm -rf .venv && "$PY" -m venv .venv || { echo "Impossible de créer l'environnement Python."; pause; exit 1; }
fi
echo "Vérification des bibliothèques…"
if ! .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt; then
  echo "Environnement abîmé : reconstruction…"
  rm -rf .venv && "$PY" -m venv .venv && .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt \
    || { echo "L'installation des bibliothèques a échoué (connexion Internet ?)."; pause; exit 1; }
fi

# --- 4. lancement (le navigateur s'ouvre tout seul)
echo
.venv/bin/python app.py "$@"
pause
