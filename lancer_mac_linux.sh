#!/usr/bin/env bash
# Lanceur macOS / Linux : vérifie et installe les dépendances à chaque démarrage.
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then echo "Python 3 est introuvable : installez-le puis relancez."; exit 1; fi
if [ ! -x .venv/bin/python ]; then
  echo "Création de l'environnement Python local..."
  rm -rf .venv && "$PY" -m venv .venv || { echo "Impossible de créer .venv"; exit 1; }
fi
echo "Vérification des bibliothèques..."
if ! .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt; then
  echo "Environnement abîmé : reconstruction..."
  rm -rf .venv && "$PY" -m venv .venv && .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt || {
    echo "L'installation des bibliothèques a échoué (connexion Internet ?)"; exit 1; }
fi
exec .venv/bin/python app.py "$@"
