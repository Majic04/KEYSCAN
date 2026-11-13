"""
Mise à jour d'une base créée par une version précédente de KeyScan, sans rien perdre.
Chaque étape ne fait quelque chose que si la base en a besoin ; on peut donc l'exécuter à chaque démarrage.

  1.0  colonnes ajoutées au fil des versions (avancement, empreinte, responsable d'un dossier)
  1.0  mots-clés communs à tous les profs → une liste par prof
  1.1  une liste par prof → une liste par dossier (+ la liste par défaut de chaque prof)
  1.0  seuils communs → des seuils par prof
Et à chaque démarrage : empreinte des fichiers qui n'en ont pas, profil créé pour chaque membre de l'équipe,
responsable donné aux dossiers qui n'en ont pas.
"""
from __future__ import annotations

import json

from engine.text import normalize

from .database import file_fingerprint

DEFAULT_TEAM = ["Franck Plestan", "Mohamed Hamida"]
DEFAULT_THRESHOLDS = {"present_thr": 85, "review_thr": 50, "min_quality": 70}


def _columns(db, table: str) -> list[str]:
    return [row["name"] for row in db.execute(f"PRAGMA table_info({table})")]


def _settings(db) -> dict:
    return {row["key"]: json.loads(row["value"]) for row in db.execute("SELECT key, value FROM settings")}


def upgrade(db):
    for column, sql_type in (("progress_done", "INTEGER"), ("progress_total", "INTEGER"), ("started_at", "REAL"), ("sha256", "TEXT")):
        if column not in _columns(db, "documents"):
            db.execute(f"ALTER TABLE documents ADD COLUMN {column} {sql_type}")
    if "owner" not in _columns(db, "dossiers"):
        db.execute("ALTER TABLE dossiers ADD COLUMN owner TEXT")

    team = _settings(db).get("operators", DEFAULT_TEAM)
    _keywords_per_profile(db, team)
    _keywords_per_dossier(db)
    _thresholds_per_profile(db, team)
    _fingerprints(db)
    _owner_for_every_dossier(db, team)


def _keywords_per_profile(db, team: list[str]):
    """Version 1.0 : une seule liste de mots-clés pour tous. Elle est recopiée dans le profil de chaque prof."""
    if "owner" in _columns(db, "keywords"):
        return
    old = [dict(row) for row in db.execute("SELECT term, created_by, created_at FROM keywords")]
    db.execute("DROP TABLE keywords")
    db.execute("""CREATE TABLE keywords (id INTEGER PRIMARY KEY, owner TEXT NOT NULL, term TEXT NOT NULL, norm TEXT NOT NULL,
                  created_by TEXT, created_at TEXT, UNIQUE(owner, norm))""")
    for person in team:
        for keyword in old:
            db.execute("INSERT OR IGNORE INTO keywords(owner, term, norm, created_by, created_at) VALUES (?,?,?,?,?)",
                       (person, keyword["term"], " ".join(normalize(keyword["term"]).split()), keyword["created_by"], keyword["created_at"]))


def _keywords_per_dossier(db):
    """
    Version 1.1 : chaque dossier a ses propres mots-clés. L'ancienne liste du prof devient sa liste par défaut,
    et chacun de ses dossiers en reçoit une copie : les résultats déjà obtenus ne changent pas.
    """
    if "dossier_id" in _columns(db, "keywords"):
        return
    old = [dict(row) for row in db.execute("SELECT owner, term, norm, created_by, created_at FROM keywords")]
    db.execute("DROP TABLE keywords")
    db.execute("""CREATE TABLE keywords (id INTEGER PRIMARY KEY, owner TEXT NOT NULL, dossier_id INTEGER NOT NULL DEFAULT 0,
                  term TEXT NOT NULL, norm TEXT NOT NULL, created_by TEXT, created_at TEXT, UNIQUE(owner, dossier_id, norm))""")
    dossiers_of = {}
    for row in db.execute("SELECT id, owner FROM dossiers"):
        dossiers_of.setdefault(row["owner"], []).append(row["id"])
    for keyword in old:
        for dossier_id in [0] + dossiers_of.get(keyword["owner"], []):
            db.execute("INSERT OR IGNORE INTO keywords(owner, dossier_id, term, norm, created_by, created_at) VALUES (?,?,?,?,?,?)",
                       (keyword["owner"], dossier_id, keyword["term"], keyword["norm"], keyword["created_by"], keyword["created_at"]))


def _thresholds_per_profile(db, team: list[str]):
    """Chaque membre de l'équipe a ses seuils (les anciens seuils communs sont repris s'il y en avait)."""
    settings = _settings(db)
    old_common = {key: settings[key] for key in DEFAULT_THRESHOLDS if key in settings}
    for person in team:
        if f"profile:{person}" not in settings:
            values = {key: float(value) for key, value in {**DEFAULT_THRESHOLDS, **old_common}.items()}
            db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (f"profile:{person}", json.dumps(values)))
    for key in DEFAULT_THRESHOLDS:
        db.execute("DELETE FROM settings WHERE key=?", (key,))


def _fingerprints(db):
    """Empreinte des fichiers déposés avant la détection des doublons."""
    for row in db.execute("SELECT id, path FROM documents WHERE sha256 IS NULL").fetchall():
        fingerprint = file_fingerprint(row["path"])
        if fingerprint:
            db.execute("UPDATE documents SET sha256=? WHERE id=?", (fingerprint, row["id"]))


def _owner_for_every_dossier(db, team: list[str]):
    """Un dossier sans responsable (ou dont le responsable a quitté l'équipe) va à son créateur, sinon au premier prof."""
    if not team:
        return
    for row in db.execute("SELECT id, owner, created_by FROM dossiers").fetchall():
        if row["owner"] not in team:
            new_owner = row["created_by"] if row["created_by"] in team else team[0]
            db.execute("UPDATE dossiers SET owner=? WHERE id=?", (new_owner, row["id"]))
