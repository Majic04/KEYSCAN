"""
KeyScan — détection de mots-clés dans des dossiers de candidature (PDF, scans, photos, écriture manuscrite).
Projet Master 2027 — Centrale Nantes.

    python app.py                          puis ouvrir http://127.0.0.1:5000
    python app.py --host 0.0.0.0           accès depuis un autre poste du réseau local
    python app.py --reset-pin "Nom Prénom" code PIN oublié

Le code est rangé en deux parties :
    engine/   la lecture des documents et la recherche des mots-clés (sans interface)
    server/   l'application web : base de données, profils, API, lecture en arrière-plan
"""
import importlib.util
import sys

# console Windows : les accents ne doivent jamais faire planter l'affichage
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

# bibliothèques manquantes : un message clair plutôt qu'une erreur Python
REQUIRED = {"flask": "flask", "pytesseract": "pytesseract", "rapidfuzz": "rapidfuzz", "PIL": "pillow", "numpy": "numpy"}
missing = [package for module, package in REQUIRED.items() if importlib.util.find_spec(module) is None]
if importlib.util.find_spec("pymupdf") is None and importlib.util.find_spec("fitz") is None:
    missing.append("pymupdf")
if missing:
    print("\n[KeyScan] Bibliothèques Python manquantes : " + ", ".join(missing))
    print(f'Pour les installer, exécutez dans ce dossier :\n    "{sys.executable}" -m pip install -r requirements.txt\n')
    sys.exit(1)

import argparse  # noqa: E402
import threading  # noqa: E402
import webbrowser  # noqa: E402

from server import create_app, start  # noqa: E402
from server.profiles import forget_pin, reset_pins_on_new_version, team  # noqa: E402,F401 — utilisés par desktop.py

app = create_app()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--reset-pin", metavar="NOM", help="efface le code PIN d'un profil (code oublié)")
    options = parser.parse_args()

    if options.reset_pin:
        if forget_pin(options.reset_pin):
            print(f"Code de « {options.reset_pin} » effacé : un nouveau code sera demandé à la prochaine ouverture du profil.")
        else:
            print(f"Aucun code trouvé pour « {options.reset_pin} ». Profils : {', '.join(team())}")
        return

    start()
    url = f"http://{'127.0.0.1' if options.host == '0.0.0.0' else options.host}:{options.port}"
    print(f"\nKeyScan est lancé : {url}\n(Ctrl+C pour arrêter)\n")
    if not options.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=options.host, port=options.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
