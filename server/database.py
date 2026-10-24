"""
Où sont rangées les données, et la base SQLite.

Dossier des données : « data » à côté du code, ou le dossier de l'utilisateur fourni par l'application
de bureau (variable KEYSCAN_DATA). On y trouve :
    keyscan.db    la base : profils, dossiers, documents, mots-clés, réglages
    files/        les fichiers déposés
    secret.key    la clé qui signe le cookie de session

Les tables :
    dossiers   un candidat : id, name, owner (le responsable), created_by, created_at
    documents  un fichier déposé dans un dossier, et le résultat de sa lecture :
               status (en_attente, en_cours, ok, erreur), pages, quality, tokens (les mots lus, en JSON),
               progress_done / progress_total (pages lues / pages en tout), sha256 (empreinte du contenu)
    keywords   un mot-clé : owner, dossier_id (0 = liste par défaut du responsable), term, norm (forme normalisée)
    settings   réglages en clé → valeur JSON : "operators" (l'équipe), "profile:<nom>" (seuils),
               "pin:<nom>" (code PIN haché), "engine_version", "app_version"…
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("KEYSCAN_DATA") or os.path.join(ROOT, "data")
FILES_DIR = os.path.join(DATA_DIR, "files")
DATABASE = os.path.join(DATA_DIR, "keyscan.db")
os.makedirs(FILES_DIR, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS dossiers (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner TEXT, created_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    dossier_id INTEGER NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    filename TEXT NOT NULL, path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'en_attente',
    error TEXT, pages TEXT, quality REAL, tokens TEXT,
    uploaded_by TEXT, uploaded_at TEXT, analysed_at TEXT,
    progress_done INTEGER, progress_total INTEGER, started_at REAL, sha256 TEXT);
CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY, owner TEXT NOT NULL, dossier_id INTEGER NOT NULL DEFAULT 0,
    term TEXT NOT NULL, norm TEXT NOT NULL, created_by TEXT, created_at TEXT,
    UNIQUE(owner, dossier_id, norm));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def connect() -> sqlite3.Connection:
    """
    Connexion à la base. À utiliser avec « with » : les changements sont enregistrés à la fin du bloc.
        with connect() as db:
            db.execute("UPDATE dossiers SET name=? WHERE id=?", (name, dossier_id))
    """
    connection = sqlite3.connect(DATABASE, timeout=30)
    connection.row_factory = sqlite3.Row             # les lignes se lisent comme des dictionnaires : row["name"]
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_tables():
    """Crée les tables si besoin, puis met à jour une base créée par une version précédente."""
    from .migrations import upgrade
    with connect() as db:
        db.executescript(SCHEMA)
        upgrade(db)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def file_fingerprint(path: str) -> str | None:
    """Empreinte du contenu d'un fichier (SHA-256) : deux fichiers identiques ont la même, quel que soit leur nom."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


# =========================================================================== réglages (table settings)
def read_setting(key: str, default=None):
    with connect() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def write_setting(key: str, value, db=None):
    """Enregistre un réglage (dans la connexion « db » si on est déjà dans un bloc « with connect() »)."""
    sql, args = "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, json.dumps(value))
    if db is not None:
        db.execute(sql, args)
    else:
        with connect() as own:
            own.execute(sql, args)


def delete_setting(key: str, db=None):
    if db is not None:
        db.execute("DELETE FROM settings WHERE key=?", (key,))
    else:
        with connect() as own:
            own.execute("DELETE FROM settings WHERE key=?", (key,))


def remove_file(path: str | None):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
