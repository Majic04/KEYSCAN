#!/bin/bash
# Installe le module optionnel « écriture manuscrite » de KeyScan (Mac). À faire une seule fois.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
pause(){ echo; read -n 1 -s -r -p "Appuyez sur une touche pour fermer…"; echo; }
clear
echo "KeyScan — installation du module d'écriture manuscrite"
echo "========================================================"
echo
if [ ! -x .venv/bin/python ]; then
  echo "Lancez d'abord « Lancer KeyScan.command » une fois (il prépare Python), puis relancez ce fichier."
  pause; exit 1
fi
echo "Quel modèle installer ?"
echo "  1) Français (recommandé) : TrOCR affiné sur l'écriture manuscrite française, ≈ 2,3 Go"
echo "  2) Anglais, plus léger et plus rapide : TrOCR base, ≈ 1,3 Go"
read -r -p "Votre choix [1] : " choix
[ "$choix" = "2" ] && MODELE=en || MODELE=fr
echo
echo "1/3  Installation de PyTorch et Transformers (quelques minutes)…"
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-manuscrit.txt \
  || { echo; echo "L'installation a échoué (connexion Internet ?)."; pause; exit 1; }
echo
echo "2/3  Téléchargement du modèle (une seule fois)…"
.venv/bin/python -m engine.handwriting --install "$MODELE" \
  || { echo; echo "Le téléchargement a échoué (connexion Internet ?). Relancez ce fichier pour reprendre."; pause; exit 1; }
echo
echo "3/3  Test de lecture sur exemples/manuscrit.png…"
.venv/bin/python -m engine.handwriting --selftest
echo
echo "Terminé. Fermez la fenêtre de KeyScan si elle est ouverte, puis relancez « Lancer KeyScan.command » :"
echo "les documents déjà déposés seront relus avec l'écriture manuscrite."
pause
