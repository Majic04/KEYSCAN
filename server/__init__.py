"""
Le serveur de KeyScan : une petite application Flask qui sert l'interface (templates/index.html)
et répond à ses demandes (/api/...).

    database.py     la base SQLite et le dossier des données
    migrations.py   mise à jour d'une base créée par une ancienne version
    profiles.py     l'équipe, les seuils de chacun, les codes PIN, la session
    keywords.py     les listes de mots-clés
    uploads.py      le dépôt des fichiers, l'import de plusieurs candidats d'un coup
    analysis.py     la lecture des documents en arrière-plan (plusieurs à la fois)
    results.py      le calcul des décisions pour chaque dossier et chaque mot-clé
    previews.py     l'image d'une page avec les mots surlignés
    routes/         les adresses de l'API, un fichier par sujet

Toutes les adresses /api/... et /export... exigent un profil ouvert (code PIN), sauf celles de
l'écran de verrouillage.
"""
from __future__ import annotations

import os
import secrets
import time

from flask import Flask, g, jsonify, render_template, request, session

from engine.ocr import find_tesseract

from .analysis import handwriting_status, reread_if_engine_changed, start_workers
from .database import DATA_DIR, ROOT, create_tables
from .profiles import session_owner
from .routes import ALL as ALL_ROUTES

OPEN_WITHOUT_PROFILE = {"/api/session", "/api/unlock", "/api/pin/setup", "/api/lock"}


def _secret_key() -> bytes:
    """La clé qui signe le cookie de session : créée une fois, gardée dans le dossier des données."""
    path = os.path.join(DATA_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(secrets.token_bytes(32))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    with open(path, "rb") as f:
        return f.read()


def create_app() -> Flask:
    app = Flask(__name__, root_path=ROOT)     # templates/ et static/ sont à la racine du projet
    app.secret_key = _secret_key()
    app.config.update(MAX_CONTENT_LENGTH=500 * 1024 * 1024,      # 500 Mo par envoi
                      SESSION_COOKIE_NAME="keyscan", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")

    # numéro ajouté aux adresses des fichiers de l'interface : il change dès qu'un fichier change,
    # donc le navigateur ne réutilise jamais une ancienne version
    static_files = [os.path.join(folder, name) for folder, _, names in os.walk(os.path.join(ROOT, "static")) for name in names]
    asset_version = str(int(max(os.path.getmtime(path) for path in static_files)))

    @app.get("/")
    def index():
        return render_template("index.html", v=asset_version)

    @app.before_request
    def require_open_profile():
        protected = request.path.startswith("/api/") or request.path.startswith("/export")
        if not protected or request.path in OPEN_WITHOUT_PROFILE:
            return None
        owner = session_owner()
        if not owner:
            session.clear()
            return jsonify({"locked": True, "error": "Profil verrouillé"}), 401
        if request.headers.get("X-Passive") != "1":     # le rafraîchissement automatique ne compte pas comme activité
            session["t"] = time.time()
        g.owner = owner
        return None

    for routes in ALL_ROUTES:
        app.register_blueprint(routes)
    return app


def start():
    """Prépare la base, vérifie Tesseract et le module manuscrit, puis démarre la lecture en arrière-plan."""
    create_tables()
    if not find_tesseract():
        print("\n⚠  Tesseract introuvable : l'OCR (PDF scannés, images) ne fonctionnera pas.\n"
              "   Installez-le (voir README) ou indiquez son chemin dans la variable TESSERACT_CMD.\n")
    reread_if_engine_changed()
    handwriting = handwriting_status()
    print("Écriture manuscrite : " + (f"activée ({handwriting.get('label')})" if handwriting.get("ready")
                                      else "non installée (python -m engine.trocr --install fr)"))
    print(f"Lecture en parallèle : {start_workers()} document(s) à la fois")
