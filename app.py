"""
KeyScan — outil local de détection de mots-clés dans des dossiers de documents hétérogènes
(PDF texte, PDF scannés, images). Projet Master 2027 — Centrale Nantes.

Lancement :  python app.py        puis ouvrir http://127.0.0.1:5000
Options    :  python app.py --host 0.0.0.0 --port 5000   (accès depuis un autre poste du réseau local)
"""
from __future__ import annotations

import sys

# --- console Windows : les accents et symboles ne doivent jamais faire planter l'affichage
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

# --- vérification des bibliothèques avant tout import (message clair plutôt qu'une erreur Python)
import importlib.util  # noqa: E402

_REQUIRED = {"flask": "flask", "pytesseract": "pytesseract", "rapidfuzz": "rapidfuzz", "PIL": "pillow", "numpy": "numpy"}
_missing = [pkg for mod, pkg in _REQUIRED.items() if importlib.util.find_spec(mod) is None]
if importlib.util.find_spec("pymupdf") is None and importlib.util.find_spec("fitz") is None:
    _missing.append("pymupdf")
if _missing:
    print("\n[KeyScan] Bibliothèques Python manquantes : " + ", ".join(_missing))
    print("Pour les installer, exécutez dans ce dossier :")
    print(f'    "{sys.executable}" -m pip install -r requirements.txt\n')
    sys.exit(1)

import argparse  # noqa: E402
import csv
import hashlib
import hmac
import secrets
import time
import io
import json
import os
import queue
import re
import sqlite3
import threading
import traceback
import webbrowser
import zipfile
from datetime import datetime

try:
    import pymupdf as fitz  # PyMuPDF ≥ 1.24.3
except ImportError:  # anciennes versions de PyMuPDF
    import fitz
from flask import Flask, abort, g, jsonify, render_template, request, send_file, session
from PIL import Image, ImageDraw, ImageFont, ImageOps
from werkzeug.utils import secure_filename

from engine import ENGINE_VERSION
from engine.extract import (ALLOWED_EXT, IMAGE_EXT, configure_tesseract, extract_document, handwriting_enabled,
                            normalize, page_count)
from engine.matcher import evaluate, find_keyword

BASE = os.path.dirname(os.path.abspath(__file__))
# données : dossier « data » à côté du code, ou dossier utilisateur fourni par l'application de bureau
DATA = os.environ.get("KEYSCAN_DATA") or os.path.join(BASE, "data")
FILES = os.path.join(DATA, "files")
DB_PATH = os.path.join(DATA, "keyscan.db")
os.makedirs(FILES, exist_ok=True)

# Réglages propres à chaque profil (chaque prof a les siens)
PROFILE_DEFAULTS = {
    "present_thr": 85,     # score ≥ → « Présent »
    "review_thr": 50,      # score entre review_thr et present_thr → « À vérifier »
    "min_quality": 70,     # qualité de lecture minimale pour conclure « Absent »
}
# Réglages communs : uniquement la composition de l'équipe
DEFAULT_SETTINGS = {**PROFILE_DEFAULTS, "operators": ["Franck Plestan", "Mohamed Hamida"]}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 Mo par envoi


def _secret_key() -> bytes:
    """Clé qui signe le cookie de session ; créée une fois, gardée dans data/ (jamais partagée)."""
    path = os.path.join(DATA, "secret.key")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(secrets.token_bytes(32))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    with open(path, "rb") as f:
        return f.read()


app.secret_key = _secret_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_NAME="keyscan")
IDLE_MINUTES = 30          # verrouillage automatique après 30 min sans activité


# =========================================================================== base de données
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    with db() as con:
        con.executescript(
            """
            -- dossier_id = 0 : liste par défaut du prof (proposée à chaque nouveau dossier) ;
            -- sinon : mots-clés propres à ce dossier
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY, owner TEXT NOT NULL, dossier_id INTEGER NOT NULL DEFAULT 0,
                term TEXT NOT NULL, norm TEXT NOT NULL,
                created_by TEXT, created_at TEXT, UNIQUE(owner, dossier_id, norm));
            CREATE TABLE IF NOT EXISTS dossiers (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_by TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                dossier_id INTEGER NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
                filename TEXT NOT NULL, path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'en_attente',   -- en_attente | en_cours | ok | erreur
                error TEXT, pages TEXT, quality REAL, tokens TEXT,
                uploaded_by TEXT, uploaded_at TEXT, analysed_at TEXT);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            """
        )
        dcols = [r["name"] for r in con.execute("PRAGMA table_info(documents)")]
        for col, typ in (("progress_done", "INTEGER"), ("progress_total", "INTEGER"), ("started_at", "REAL"), ("sha256", "TEXT")):
            if col not in dcols:
                con.execute(f"ALTER TABLE documents ADD COLUMN {col} {typ}")
        cols = [r["name"] for r in con.execute("PRAGMA table_info(dossiers)")]
        if "owner" not in cols:  # base créée avec une version précédente
            con.execute("ALTER TABLE dossiers ADD COLUMN owner TEXT")
        ops = get_settings()["operators"]

        # mots-clés : un jeu par profil (avant : un jeu commun, recopié à chaque prof pour ne rien perdre)
        kcols = [r["name"] for r in con.execute("PRAGMA table_info(keywords)")]
        if "owner" not in kcols:
            old = [dict(r) for r in con.execute("SELECT term, norm, created_by, created_at FROM keywords")]
            con.execute("DROP TABLE keywords")
            con.execute("""CREATE TABLE keywords (
                id INTEGER PRIMARY KEY, owner TEXT NOT NULL, term TEXT NOT NULL, norm TEXT NOT NULL,
                created_by TEXT, created_at TEXT, UNIQUE(owner, norm))""")
            for o in ops:
                for k in old:
                    norm = " ".join(normalize(k["term"]).split())
                    con.execute("INSERT OR IGNORE INTO keywords(owner, term, norm, created_by, created_at) VALUES (?,?,?,?,?)",
                                (o, k["term"], norm, k["created_by"], k["created_at"]))

        # mots-clés par dossier (avant : une seule liste par prof pour tous ses dossiers).
        # L'ancienne liste devient la liste par défaut, et chaque dossier existant en reçoit une copie :
        # les résultats déjà obtenus ne changent pas.
        kcols = [r["name"] for r in con.execute("PRAGMA table_info(keywords)")]
        if "dossier_id" not in kcols:
            old = [dict(r) for r in con.execute("SELECT owner, term, norm, created_by, created_at FROM keywords")]
            con.execute("DROP TABLE keywords")
            con.execute("""CREATE TABLE keywords (
                id INTEGER PRIMARY KEY, owner TEXT NOT NULL, dossier_id INTEGER NOT NULL DEFAULT 0,
                term TEXT NOT NULL, norm TEXT NOT NULL,
                created_by TEXT, created_at TEXT, UNIQUE(owner, dossier_id, norm))""")
            dossiers_by_owner: dict[str, list[int]] = {}
            for r in con.execute("SELECT id, owner FROM dossiers"):
                dossiers_by_owner.setdefault(r["owner"], []).append(r["id"])
            for k in old:
                for did in [0] + dossiers_by_owner.get(k["owner"], []):
                    con.execute("INSERT OR IGNORE INTO keywords(owner, dossier_id, term, norm, created_by, created_at) VALUES (?,?,?,?,?,?)",
                                (k["owner"], did, k["term"], k["norm"], k["created_by"], k["created_at"]))
        # empreinte des fichiers déjà déposés (détection des doublons)
        for r in con.execute("SELECT id, path FROM documents WHERE sha256 IS NULL").fetchall():
            h = file_sha256(r["path"])
            if h:
                con.execute("UPDATE documents SET sha256=? WHERE id=?", (h, r["id"]))

        # seuils : un jeu par profil (avant : un jeu commun, recopié à chaque prof)
        rows = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM settings")}
        legacy = {k: rows[k] for k in PROFILE_DEFAULTS if k in rows}
        for o in ops:
            if f"profile:{o}" not in rows:
                save_profile(con, o, {**PROFILE_DEFAULTS, **legacy})
        con.execute(f"DELETE FROM settings WHERE key IN ({','.join('?' * len(PROFILE_DEFAULTS))})", tuple(PROFILE_DEFAULTS))

        # tout dossier sans responsable (ou dont le responsable n'existe plus) est confié au premier prof
        if ops:
            con.execute(
                f"UPDATE dossiers SET owner = COALESCE(CASE WHEN created_by IN ({','.join('?' * len(ops))}) THEN created_by END, ?) "
                f"WHERE owner IS NULL OR owner NOT IN ({','.join('?' * len(ops))})",
                (*ops, ops[0], *ops),
            )


def reset_pins_on_new_version(version: str) -> bool:
    """
    Application installée : à la première ouverture d'une nouvelle version, les codes PIN sont effacés
    (chaque profil en choisit un nouveau). Dossiers, mots-clés et réglages sont conservés.
    Retourne True si les codes viennent d'être effacés.
    """
    init_db()
    with db() as con:
        r = con.execute("SELECT value FROM settings WHERE key='app_version'").fetchone()
        if r and json.loads(r["value"]) == version:
            return False
        n = con.execute("DELETE FROM settings WHERE key LIKE 'pin:%'").rowcount
        con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('app_version', ?)", (json.dumps(version),))
        if n:
            con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('pin_reset_notice', ?)", (json.dumps(version),))
    return bool(n)


def get_settings(owner: str | None = None) -> dict:
    """
    Réglages vus par un profil : la liste de l'équipe (commune) + les seuils de CE profil.
    Sans profil : valeurs par défaut des seuils.
    """
    s = dict(DEFAULT_SETTINGS)
    with db() as con:
        rows = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM settings")}
    s["operators"] = rows.get("operators", s["operators"])
    if owner:
        s.update({k: v for k, v in rows.get(f"profile:{owner}", {}).items() if k in PROFILE_DEFAULTS})
        s["profile"] = owner
    return s


def save_profile(con, owner: str, values: dict):
    cur = con.execute("SELECT value FROM settings WHERE key=?", (f"profile:{owner}",)).fetchone()
    prof = json.loads(cur["value"]) if cur else {}
    prof.update({k: max(0.0, min(100.0, float(v))) for k, v in values.items() if k in PROFILE_DEFAULTS})
    con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?,?)", (f"profile:{owner}", json.dumps(prof)))


def file_sha256(path: str) -> str | None:
    """Empreinte du contenu d'un fichier : deux fichiers identiques ont la même, quel que soit leur nom."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# =========================================================================== file d'analyse (OCR en arrière-plan)
jobs: "queue.Queue[int]" = queue.Queue()
_token_cache: dict[int, list] = {}
_match_cache: dict[tuple[int, str], list] = {}
_preview_cache: dict[tuple, bytes] = {}
_cache_lock = threading.Lock()


def worker():
    while True:
        doc_id = jobs.get()
        try:
            with db() as con:
                row = con.execute("SELECT path FROM documents WHERE id=?", (doc_id,)).fetchone()
                if not row:
                    continue
                con.execute("UPDATE documents SET status='en_cours', progress_done=0, progress_total=?, started_at=? WHERE id=?",
                            (page_count(row["path"]), time.time(), doc_id))

            def progress(done, total, _id=doc_id):
                with db() as c:
                    c.execute("UPDATE documents SET progress_done=?, progress_total=? WHERE id=?", (done, total, _id))

            res = extract_document(row["path"], progress=progress)
            with db() as con:
                con.execute(
                    "UPDATE documents SET status='ok', error=NULL, pages=?, quality=?, tokens=?, analysed_at=? WHERE id=?",
                    (json.dumps(res["pages"]), res["quality"], json.dumps(res["tokens"]), now(), doc_id),
                )
            forget_doc(doc_id)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            with db() as con:
                con.execute("UPDATE documents SET status='erreur', error=? WHERE id=?", (str(e)[:500], doc_id))
        finally:
            jobs.task_done()


def forget_doc(doc_id: int):
    with _cache_lock:
        _token_cache.pop(doc_id, None)
        for k in [k for k in _match_cache if k[0] == doc_id]:
            _match_cache.pop(k, None)


def doc_tokens(doc_id: int) -> list:
    with _cache_lock:
        if doc_id in _token_cache:
            return _token_cache[doc_id]
    with db() as con:
        r = con.execute("SELECT tokens FROM documents WHERE id=?", (doc_id,)).fetchone()
    toks = json.loads(r["tokens"]) if r and r["tokens"] else []
    with _cache_lock:
        _token_cache[doc_id] = toks
    return toks


def occurrences(doc_row, term: str) -> list:
    key = (doc_row["id"], normalize(term))
    with _cache_lock:
        if key in _match_cache:
            return _match_cache[key]
    occ = find_keyword(doc_tokens(doc_row["id"]), term)
    with _cache_lock:
        _match_cache[key] = occ
    return occ


# =========================================================================== calcul des résultats
def dossier_results(dossier_id: int | None = None, owner: str | None = None) -> dict:
    """
    Résultats de tous les dossiers, d'un seul dossier, ou des dossiers d'un prof (owner).
    Chaque dossier est évalué avec SES mots-clés et les seuils du prof auquel il appartient.
    Règles de fiabilité :
      - un fichier déposé deux fois (même contenu) n'est compté qu'une fois ;
      - si un document du dossier n'a pas pu être lu, aucune absence n'est affirmée (« absence incertaine »).
    """
    s = get_settings(owner)
    where, args = [], []
    if dossier_id:
        where.append("id=?"); args.append(dossier_id)
    if owner:
        where.append("owner=?"); args.append(owner)
    with db() as con:
        q = "SELECT * FROM dossiers" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC, id DESC"
        dossiers = [dict(r) for r in con.execute(q, args)]
        ids = [d["id"] for d in dossiers]
        ph = ",".join("?" * len(ids))
        docs = [dict(r) for r in con.execute(
            "SELECT id, dossier_id, filename, status, error, pages, quality, uploaded_by, uploaded_at, analysed_at, "
            f"progress_done, progress_total, started_at, sha256 FROM documents WHERE dossier_id IN ({ph}) ORDER BY id", ids)] if ids else []
        kws = [dict(r) for r in con.execute(
            f"SELECT id, dossier_id, term, created_by FROM keywords WHERE dossier_id IN ({ph}) ORDER BY lower(term)", ids)] if ids else []
        defaults = [dict(r) for r in con.execute(
            "SELECT id, owner, term, created_by FROM keywords WHERE dossier_id=0 ORDER BY lower(term)")]
        owners = {r["owner"]: r["n"] for r in con.execute("SELECT owner, COUNT(*) AS n FROM dossiers GROUP BY owner")}
    kw_counts: dict[str, int] = {}
    for k in defaults:
        kw_counts[k["owner"]] = kw_counts.get(k["owner"], 0) + 1
    prof_cache: dict[str, dict] = {}

    def prof(o):
        if o not in prof_cache:
            prof_cache[o] = get_settings(o)
        return prof_cache[o]

    out = []
    for d in dossiers:
        ps = prof(d["owner"])
        dkws = [k for k in kws if k["dossier_id"] == d["id"]]
        ddocs = [x for x in docs if x["dossier_id"] == d["id"]]
        # doublons : même contenu qu'un document déposé avant dans ce dossier → ignoré dans le calcul
        first_by_hash: dict[str, dict] = {}
        for x in ddocs:
            x["duplicate_of"] = None
            if x["sha256"]:
                if x["sha256"] in first_by_hash:
                    x["duplicate_of"] = first_by_hash[x["sha256"]]["filename"]
                else:
                    first_by_hash[x["sha256"]] = x
        counted = [x for x in ddocs if not x["duplicate_of"]]
        ready = [x for x in counted if x["status"] == "ok"]
        unread = [x for x in counted if x["status"] == "erreur"]
        pending = sum(1 for x in counted if x["status"] in ("en_attente", "en_cours"))
        quality = min((x["quality"] or 0) for x in ready) if ready else 0.0
        all_pages = [p for x in ready for p in (json.loads(x["pages"]) if x["pages"] else [])]
        cells = {}
        for k in dkws:
            occ = []
            for x in ready:
                for o in occurrences(x, k["term"]):
                    occ.append({**o, "doc_id": x["id"], "filename": x["filename"]})
            score, decision = evaluate(k["term"], occ, quality, all_pages, ps["present_thr"], ps["review_thr"],
                                       ps["min_quality"], unread=len(unread))
            # fiabilité de la décision : score si trouvé, qualité de lecture si absent
            reliability = score if decision in ("present", "a_verifier") else round(quality, 1)
            cells[k["id"]] = {
                "term": k["term"], "score": score, "decision": decision, "reliability": reliability,
                "count": len(occ), "occurrences": occ,
                # où le mot a été lu (fichier, page) : affiché dans la liste sans charger le détail
                "where": [{"file": f, "page": p} for f, p in dict.fromkeys((o["filename"], o["page"]) for o in occ)],
            }
        # pour chaque document : où sont les mots trouvés (et lesquels sont à vérifier), page par page
        hits: dict[int, list] = {}
        for kid, c in cells.items():
            per_doc: dict[int, dict] = {}
            for o in c["occurrences"]:
                h = per_doc.setdefault(o["doc_id"], {"kid": kid, "term": c["term"], "decision": c["decision"],
                                                      "pages": [], "review": False})
                if o["page"] not in h["pages"]:
                    h["pages"].append(o["page"])
                if not (o.get("certain", True) and o["score"] * 100 >= ps["present_thr"]):
                    h["review"] = True
            for doc_id, h in per_doc.items():
                hits.setdefault(doc_id, []).append(h)
        out.append({
            "id": d["id"], "name": d["name"], "owner": d["owner"], "created_by": d["created_by"], "created_at": d["created_at"],
            "quality": round(quality, 1), "pending": pending,
            "unread": [x["filename"] for x in unread],
            "keywords": [{"id": k["id"], "term": k["term"], "created_by": k["created_by"]} for k in dkws],
            "documents": [{
                "id": x["id"], "filename": x["filename"], "status": x["status"], "error": x["error"],
                "quality": x["quality"], "pages": json.loads(x["pages"]) if x["pages"] else [],
                "uploaded_by": x["uploaded_by"], "uploaded_at": x["uploaded_at"],
                "progress": _progress(x), "duplicate_of": x["duplicate_of"],
                "hits": sorted(hits.get(x["id"], []), key=lambda h: (not h["review"], h["term"].lower())),
            } for x in ddocs],
            "cells": cells,
        })
    shown = [k for k in defaults if k["owner"] == owner] if owner else []
    hw = handwriting_status()
    engine = {"handwriting": {"ready": hw.get("ready", False), "libraries": hw.get("libraries", False), "label": hw.get("label")}}
    return {"keywords": shown, "dossiers": out, "settings": s, "owners": owners, "keyword_counts": kw_counts, "engine": engine}


_HW_CACHE = {"t": 0.0, "v": None}


def handwriting_status() -> dict:
    if time.time() - _HW_CACHE["t"] > 60 or _HW_CACHE["v"] is None:
        try:
            from engine import handwriting
            st = handwriting.status()
        except Exception as e:  # noqa: BLE001
            st = {"libraries": False, "ready": False, "error": str(e)}
        _HW_CACHE.update(t=time.time(), v=st)
    return _HW_CACHE["v"]


def engine_version() -> str:
    """Version effective du moteur : change quand le module manuscrit est installé → documents relus."""
    st = handwriting_status()
    return ENGINE_VERSION + (f"+manuscrit-{st.get('model')}" if st.get("ready") else "")


def _progress(x: dict) -> dict | None:
    """Avancement d'une analyse : pages faites / total, temps restant estimé (secondes)."""
    if x["status"] not in ("en_cours", "en_attente"):
        return None
    done, total = x.get("progress_done") or 0, x.get("progress_total") or 0
    eta = None
    if x["status"] == "en_cours" and done and total and x.get("started_at"):
        eta = round((time.time() - x["started_at"]) / done * (total - done))
    return {"done": done, "total": total, "eta": eta}


# =========================================================================== profils protégés par code PIN
# Un navigateur n'a qu'un seul profil déverrouillé à la fois (cookie de session signé).
# Toutes les routes de données utilisent ce profil : le nom envoyé par le navigateur n'est jamais cru.
PUBLIC = {"index", "static", "get_session", "unlock", "setup_pin", "lock"}
_fails: dict[str, list] = {}          # anti-force brute : profil -> [échecs, bloqué_jusqu_à]
_fails_lock = threading.Lock()


def _pin_record(owner: str) -> dict | None:
    with db() as con:
        r = con.execute("SELECT value FROM settings WHERE key=?", (f"pin:{owner}",)).fetchone()
    return json.loads(r["value"]) if r else None


def _hash_pin(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 200_000).hex()


def _set_pin(owner: str, pin: str) -> dict:
    salt = secrets.token_bytes(16)
    rec = {"salt": salt.hex(), "hash": _hash_pin(pin, salt), "len": len(pin), "nonce": secrets.token_hex(8)}
    with db() as con:
        con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?,?)", (f"pin:{owner}", json.dumps(rec)))
    return rec


def _check_pin(owner: str, pin: str) -> bool:
    rec = _pin_record(owner)
    return bool(rec) and hmac.compare_digest(rec["hash"], _hash_pin(str(pin), bytes.fromhex(rec["salt"])))


def _valid_pin_format(pin) -> str:
    pin = str(pin or "")
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        abort(400, "Le code doit contenir de 4 à 8 chiffres")
    return pin


def _throttle(owner: str):
    with _fails_lock:
        n, until = _fails.get(owner, [0, 0.0])
    wait = until - time.time()
    if wait > 0:
        abort(429, f"Trop d'essais : réessayez dans {int(wait) + 1} s")


def _fail(owner: str):
    with _fails_lock:
        n, _ = _fails.get(owner, [0, 0.0])
        n += 1
        until = time.time() + min(900, 30 * 2 ** (n // 5 - 1)) if n % 5 == 0 else 0.0
        _fails[owner] = [n, until]


def _open_session(owner: str, rec: dict):
    session.clear()
    session["owner"], session["nonce"], session["t"] = owner, rec["nonce"], time.time()
    with _fails_lock:
        _fails.pop(owner, None)


@app.before_request
def require_profile():
    if request.endpoint in PUBLIC or not (request.path.startswith("/api/") or request.path.startswith("/export")):
        return None
    owner = session.get("owner")
    rec = _pin_record(owner) if owner else None
    idle = time.time() - session.get("t", 0)
    if (not owner or owner not in get_settings()["operators"] or not rec or rec["nonce"] != session.get("nonce")
            or idle > IDLE_MINUTES * 60):
        session.clear()
        return jsonify({"locked": True, "error": "Profil verrouillé"}), 401
    if request.headers.get("X-Passive") != "1":     # le rafraîchissement automatique ne compte pas comme activité
        session["t"] = time.time()
    g.owner = owner
    return None


@app.get("/api/session")
def get_session():
    """Profil déverrouillé (ou aucun) et liste des profils, pour l'écran de verrouillage."""
    owner = session.get("owner")
    rec = _pin_record(owner) if owner else None
    ok = bool(owner and rec and rec["nonce"] == session.get("nonce") and time.time() - session.get("t", 0) <= IDLE_MINUTES * 60)
    ops = get_settings()["operators"]
    with db() as con:
        counts = {r["owner"]: r["n"] for r in con.execute("SELECT owner, COUNT(*) AS n FROM dossiers GROUP BY owner")}
    profiles = []
    for o in ops:
        r = _pin_record(o)
        profiles.append({"name": o, "has_pin": bool(r), "pin_len": r["len"] if r else None, "dossiers": counts.get(o, 0)})
    # après une mise à jour : codes effacés, message affiché jusqu'à ce que chaque profil ait recréé le sien
    notice = None
    with db() as con:
        r = con.execute("SELECT value FROM settings WHERE key='pin_reset_notice'").fetchone()
        if r:
            if all(p["has_pin"] for p in profiles):
                con.execute("DELETE FROM settings WHERE key='pin_reset_notice'")
            else:
                notice = json.loads(r["value"])
    return jsonify({"owner": owner if ok else None, "profiles": profiles, "idle_minutes": IDLE_MINUTES, "updated_to": notice})


@app.post("/api/unlock")
def unlock():
    body = request.get_json(force=True)
    owner = valid_owner(body.get("owner"))
    rec = _pin_record(owner)
    if not rec:
        abort(409, "Ce profil n'a pas encore de code")
    _throttle(owner)
    if not _check_pin(owner, body.get("pin")):
        _fail(owner)
        _throttle(owner)
        abort(403, "Code incorrect")
    _open_session(owner, rec)
    return jsonify({"owner": owner})


@app.post("/api/pin/setup")
def setup_pin():
    """Premier code d'un profil qui n'en a pas encore (puis déverrouillage)."""
    body = request.get_json(force=True)
    owner = valid_owner(body.get("owner"))
    if _pin_record(owner):
        abort(409, "Ce profil a déjà un code")
    rec = _set_pin(owner, _valid_pin_format(body.get("pin")))
    _open_session(owner, rec)
    return jsonify({"owner": owner})


@app.post("/api/pin/change")
def change_pin():
    """Changer son code : l'ancien est exigé ; les autres navigateurs ouverts sur ce profil sont verrouillés."""
    body = request.get_json(force=True)
    _throttle(g.owner)
    if not _check_pin(g.owner, body.get("old")):
        _fail(g.owner)
        abort(403, "Code actuel incorrect")
    rec = _set_pin(g.owner, _valid_pin_format(body.get("new")))
    _open_session(g.owner, rec)
    return jsonify({"ok": True})


@app.post("/api/lock")
def lock():
    session.clear()
    return jsonify({"ok": True})


def own_dossier(did: int):
    """Le dossier doit appartenir au profil déverrouillé (sinon : introuvable)."""
    with db() as con:
        r = con.execute("SELECT owner FROM dossiers WHERE id=?", (did,)).fetchone()
    if not r or r["owner"] != g.owner:
        abort(404, "Dossier introuvable")


def own_document(doc_id: int):
    with db() as con:
        r = con.execute("SELECT s.owner FROM documents d JOIN dossiers s ON s.id=d.dossier_id WHERE d.id=?", (doc_id,)).fetchone()
    if not r or r["owner"] != g.owner:
        abort(404, "Document introuvable")


# =========================================================================== routes : interface
@app.get("/")
def index():
    return render_template("index.html")


# --------------------------------------------------------------------------- mots-clés
def parse_terms(raw: str) -> list[str]:
    """Une liste collée : un mot-clé par ligne, ou séparés par « ; » ou « , »."""
    return [t.strip() for t in re.split(r"[\n;,]", raw or "") if t.strip()]


def keyword_target(dossier) -> int:
    """0 = liste par défaut du profil ; sinon un dossier qui doit appartenir au profil."""
    did = int(dossier or 0)
    if did:
        own_dossier(did)
    return did


def insert_keywords(con, owner: str, did: int, terms: list[str]) -> tuple[list[str], list[str]]:
    added, skipped = [], []
    for t in terms:
        n = " ".join(normalize(t).split())
        if not any(ch.isalnum() for ch in n):
            skipped.append(t)
            continue
        try:
            con.execute("INSERT INTO keywords(owner, dossier_id, term, norm, created_by, created_at) VALUES (?,?,?,?,?,?)",
                        (owner, did, t, n, owner, now()))
            added.append(t)
        except sqlite3.IntegrityError:
            skipped.append(t)
    return added, skipped


def copy_keyword_list(con, owner: str, src_owner: str, src_did: int, dst_did: int) -> int:
    before = con.execute("SELECT COUNT(*) FROM keywords WHERE owner=? AND dossier_id=?", (owner, dst_did)).fetchone()[0]
    con.execute("""INSERT OR IGNORE INTO keywords(owner, dossier_id, term, norm, created_by, created_at)
                   SELECT ?, ?, term, norm, created_by, ? FROM keywords WHERE owner=? AND dossier_id=?""",
                (owner, dst_did, now(), src_owner, src_did))
    return con.execute("SELECT COUNT(*) FROM keywords WHERE owner=? AND dossier_id=?", (owner, dst_did)).fetchone()[0] - before


@app.get("/api/keywords")
def list_keywords():
    did = keyword_target(request.args.get("dossier"))
    with db() as con:
        return jsonify([dict(r) for r in con.execute(
            "SELECT id, dossier_id, term, created_by, created_at FROM keywords WHERE owner=? AND dossier_id=? ORDER BY lower(term)",
            (g.owner, did))])


@app.post("/api/keywords")
def add_keywords():
    """Ajoute des mots-clés à la liste par défaut (dossier absent ou 0) ou à un dossier."""
    body = request.get_json(force=True)
    did = keyword_target(body.get("dossier"))
    with db() as con:
        added, skipped = insert_keywords(con, g.owner, did, parse_terms(body.get("terms", "")))
    return jsonify({"added": added, "skipped": skipped})


@app.post("/api/keywords/copy")
def copy_keywords():
    """
    Reprendre une liste de mots-clés (ceux déjà présents sont ignorés) :
      {"from": "<prof>"}                       liste par défaut d'un autre prof → ma liste par défaut
      {"dossier": D, "source": "default"}      ma liste par défaut → dossier D
      {"dossier": D, "source": <id dossier>}   mots-clés d'un autre de mes dossiers → dossier D
    """
    body = request.get_json(force=True)
    with db() as con:
        if body.get("dossier"):
            dst = keyword_target(body["dossier"])
            src = body.get("source", "default")
            src_did = 0 if src == "default" else keyword_target(src)
            n = copy_keyword_list(con, g.owner, g.owner, src_did, dst)
        else:
            n = copy_keyword_list(con, g.owner, valid_owner(body.get("from")), 0, 0)
    return jsonify({"added": n})


@app.delete("/api/keywords/<int:kid>")
def delete_keyword(kid):
    with db() as con:
        con.execute("DELETE FROM keywords WHERE id=? AND owner=?", (kid, g.owner))
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- dossiers et documents
def _save_upload(dossier_id: int, filename: str, data: bytes, operator: str | None) -> int | str | None:
    """
    Enregistre un document et le met en file d'analyse. Retourne son id, None s'il est refusé (format),
    ou le nom du document identique déjà présent dans le dossier (doublon : il n'est pas ajouté).
    """
    name = os.path.basename(filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT or not data:
        return None
    digest = hashlib.sha256(data).hexdigest()
    with db() as con:
        same = con.execute("SELECT filename FROM documents WHERE dossier_id=? AND sha256=?", (dossier_id, digest)).fetchone()
        if same:
            return same["filename"]
        cur = con.execute(
            "INSERT INTO documents(dossier_id, filename, path, uploaded_by, uploaded_at, sha256) VALUES (?,?,?,?,?,?)",
            (dossier_id, name, "", operator, now(), digest),
        )
        doc_id = cur.lastrowid
        path = os.path.join(FILES, f"{doc_id}_{secure_filename(name) or 'fichier' + ext}")
        with open(path, "wb") as f:
            f.write(data)
        # nombre de pages connu dès le dépôt : la file d'attente affiche « 0/30 pages »
        con.execute("UPDATE documents SET path=?, progress_done=0, progress_total=? WHERE id=?", (path, page_count(path), doc_id))
    jobs.put(doc_id)
    return doc_id


@app.post("/api/dossiers")
def create_dossier():
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    if not name:
        abort(400, "Nom de dossier requis")
    owner = g.owner
    # mots-clés du nouveau dossier : la liste par défaut (par défaut), ceux d'un autre dossier, ou aucun ;
    # plus d'éventuels mots-clés saisis à la création
    source = body.get("keywords_from", "default")
    with db() as con:
        cur = con.execute("INSERT INTO dossiers(name, owner, created_by, created_at) VALUES (?,?,?,?)",
                          (name, owner, owner, now()))
        did = cur.lastrowid
        if source == "default":
            copy_keyword_list(con, owner, owner, 0, did)
        elif source not in (None, "none", ""):
            src = con.execute("SELECT owner FROM dossiers WHERE id=?", (int(source),)).fetchone()
            if not src or src["owner"] != owner:
                abort(404, "Dossier introuvable")
            copy_keyword_list(con, owner, owner, int(source), did)
        insert_keywords(con, owner, did, parse_terms(body.get("terms", "")))
    return jsonify({"id": did, "owner": owner})


def valid_owner(name: str | None) -> str:
    """Le responsable doit être un prof déclaré dans les réglages."""
    ops = get_settings()["operators"]
    if name in ops:
        return name
    if not ops:
        abort(400, "Aucun prof déclaré dans les réglages")
    abort(400, f"Prof inconnu : {name}")


@app.patch("/api/dossiers/<int:did>")
def rename_dossier(did):
    """Renommer un dossier et/ou le confier à un autre prof."""
    own_dossier(did)
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    with db() as con:
        if name:
            con.execute("UPDATE dossiers SET name=? WHERE id=?", (name, did))
        if "owner" in body:
            new = valid_owner(body["owner"])
            con.execute("UPDATE dossiers SET owner=? WHERE id=?", (new, did))
            con.execute("UPDATE keywords SET owner=? WHERE dossier_id=?", (new, did))   # ses mots-clés le suivent
    return jsonify({"ok": True})


@app.delete("/api/dossiers/<int:did>")
def delete_dossier(did):
    own_dossier(did)
    with db() as con:
        for r in con.execute("SELECT id, path FROM documents WHERE dossier_id=?", (did,)).fetchall():
            _remove_file(r["path"])
            forget_doc(r["id"])
        con.execute("DELETE FROM keywords WHERE dossier_id=?", (did,))
        con.execute("DELETE FROM dossiers WHERE id=?", (did,))
    return jsonify({"ok": True})


@app.post("/api/dossiers/<int:did>/files")
def upload_files(did):
    own_dossier(did)
    operator = g.owner
    ids, rejected, duplicates = [], [], []
    for f in request.files.getlist("files"):
        doc_id = _save_upload(did, f.filename, f.read(), operator)
        if isinstance(doc_id, str):
            duplicates.append({"file": f.filename, "same_as": doc_id})
        elif doc_id:
            ids.append(doc_id)
        else:
            rejected.append(f.filename)
    return jsonify({"added": ids, "rejected": rejected, "duplicates": duplicates})


@app.post("/api/import-zip")
def import_zip():
    """Import d'un lot : chaque dossier de premier niveau dans le .zip devient un dossier de candidature."""
    f = request.files.get("archive")
    operator = owner = g.owner
    if not f:
        abort(400, "Archive manquante")
    created, rejected = {}, []
    with zipfile.ZipFile(io.BytesIO(f.read())) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX") or "/." in "/" + info.filename:
                continue
            parts = [p for p in info.filename.replace("\\", "/").split("/") if p]
            folder = parts[0] if len(parts) > 1 else os.path.splitext(f.filename)[0]
            if os.path.splitext(parts[-1])[1].lower() not in ALLOWED_EXT:
                rejected.append(info.filename)
                continue
            if folder not in created:
                with db() as con:
                    created[folder] = con.execute(
                        "INSERT INTO dossiers(name, owner, created_by, created_at) VALUES (?,?,?,?)", (folder, owner, operator, now())
                    ).lastrowid
                    copy_keyword_list(con, owner, owner, 0, created[folder])   # liste par défaut
            _save_upload(created[folder], parts[-1], z.read(info), operator)
    return jsonify({"dossiers": list(created), "rejected": rejected})


@app.delete("/api/documents/<int:doc_id>")
def delete_document(doc_id):
    own_document(doc_id)
    with db() as con:
        r = con.execute("SELECT path FROM documents WHERE id=?", (doc_id,)).fetchone()
        if r:
            _remove_file(r["path"])
        con.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    forget_doc(doc_id)
    return jsonify({"ok": True})


@app.post("/api/documents/<int:doc_id>/reanalyse")
def reanalyse(doc_id):
    own_document(doc_id)
    with db() as con:
        con.execute("UPDATE documents SET status='en_attente', progress_done=0 WHERE id=?", (doc_id,))
    jobs.put(doc_id)
    return jsonify({"ok": True})


def _remove_file(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


@app.get("/api/documents/<int:doc_id>/file")
def original_file(doc_id):
    own_document(doc_id)
    with db() as con:
        r = con.execute("SELECT path, filename FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not r:
        abort(404)
    return send_file(r["path"], download_name=r["filename"])


@app.get("/api/documents/<int:doc_id>/page/<int:page>.png")
def page_preview(doc_id, page):
    """
    Rendu d'une page avec des occurrences encadrées (vert : présent ; orange : à vérifier) :
      ?kw=<id>        occurrences d'un mot-clé
      ?all=1          occurrences de tous les mots-clés du dossier, avec leur nom
      &crop=x0,y0,x1,y1  zoom sur une zone (coordonnées 0-1), pour montrer précisément où est le mot
    """
    own_document(doc_id)
    with db() as con:
        r = con.execute("""SELECT d.id, d.path, d.status, d.pages, d.analysed_at, d.dossier_id, s.owner FROM documents d
                           JOIN dossiers s ON s.id = d.dossier_id WHERE d.id=?""", (doc_id,)).fetchone()
        if request.args.get("all"):
            kws = [x["term"] for x in con.execute("SELECT term FROM keywords WHERE dossier_id=? AND owner=? ORDER BY lower(term)",
                                                  (r["dossier_id"] if r else 0, g.owner))]
        else:
            kw = con.execute("SELECT term FROM keywords WHERE id=? AND owner=?", (request.args.get("kw", 0), g.owner)).fetchone()
            kws = [kw["term"]] if kw else []
    if not r:
        abort(404)
    crop = None
    if request.args.get("crop"):
        try:
            crop = [min(1.0, max(0.0, float(v))) for v in request.args["crop"].split(",")][:4]
            assert len(crop) == 4 and crop[2] > crop[0] and crop[3] > crop[1]
        except (ValueError, AssertionError):
            abort(400, "Zone invalide")
    thr = get_settings(r["owner"])["present_thr"]
    ckey = (doc_id, page, tuple(kws), r["analysed_at"], thr, tuple(crop or ()))
    with _cache_lock:
        cached = _preview_cache.get(ckey)
    if cached:
        return _png(cached)
    pages = json.loads(r["pages"]) if r["pages"] else []
    info = pages[page - 1] if 0 < page <= len(pages) else {}
    rot, skew = info.get("rot", 0), info.get("skew", 0)
    if os.path.splitext(r["path"])[1].lower() in IMAGE_EXT:
        with Image.open(r["path"]) as im:
            if getattr(im, "n_frames", 1) > 1:
                im.seek(page - 1)
            img = ImageOps.exif_transpose(im.copy()).convert("RGB")
    else:
        with fitz.open(r["path"]) as d:
            pix = d[page - 1].get_pixmap(dpi=200 if crop else 110)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if rot:
        img = img.rotate(-rot, expand=True)
    if skew:  # même redressement que pendant l'OCR, pour que les cadres tombent juste
        img = img.rotate(skew, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)
    if not crop and max(img.size) > 1600:
        img.thumbnail((1600, 1600))
    if kws and r["status"] == "ok":
        draw = ImageDraw.Draw(img, "RGBA")
        W, H = img.size
        lw = max(3, W // 500)
        try:
            font = ImageFont.load_default(size=max(14, W // 70))
        except TypeError:          # Pillow < 10.1
            font = ImageFont.load_default()
        for term in kws:
            for o in occurrences(r, term):
                if o["page"] != page:
                    continue
                x0, y0, x1, y1 = o["box"]
                box = [x0 * W - 4, y0 * H - 3, x1 * W + 4, y1 * H + 3]
                sure = o["score"] * 100 >= thr and o.get("certain", True)
                # mêmes couleurs que les surligneurs de l'interface : vert = présent, jaune = à vérifier
                fill, edge = ((90, 210, 150, 95), (20, 110, 70, 255)) if sure else ((255, 214, 40, 110), (150, 110, 0, 255))
                draw.rectangle(box, fill=fill, outline=edge, width=max(2, lw - 1))
                if len(kws) > 1:     # vue d'ensemble : nom du mot-clé au-dessus du cadre
                    tw = draw.textlength(term, font=font)
                    th = font.size + 6 if hasattr(font, "size") else 16
                    ty = box[1] - th - 2 if box[1] - th - 2 > 0 else box[3] + 2
                    draw.rectangle([box[0], ty, box[0] + tw + 12, ty + th], fill=fill[:3] + (240,))
                    draw.text((box[0] + 6, ty + 2), term, fill=(28, 43, 63), font=font)
    if crop:   # zoom : la zone et un peu de contexte (la ligne entière et ses voisines)
        W, H = img.size
        x0, y0, x1, y1 = crop
        bh = max(y1 - y0, 0.01)
        cx0, cx1 = max(0.0, x0 - 0.25), min(1.0, x1 + 0.25)
        cy0, cy1 = max(0.0, y0 - 2.2 * bh), min(1.0, y1 + 2.2 * bh)
        img = img.crop((int(cx0 * W), int(cy0 * H), int(cx1 * W), int(cy1 * H)))
        if img.width > 1400:
            img.thumbnail((1400, 1400))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False, compress_level=3)
    data = buf.getvalue()
    with _cache_lock:
        _preview_cache[ckey] = data
        while len(_preview_cache) > 120:         # petit cache : les 120 derniers aperçus
            _preview_cache.pop(next(iter(_preview_cache)))
    return _png(data)


def _png(data: bytes):
    resp = send_file(io.BytesIO(data), mimetype="image/png")
    resp.headers["Cache-Control"] = "private, max-age=600"
    return resp


# --------------------------------------------------------------------------- résultats, réglages, export
@app.get("/api/results")
def results():
    data = dossier_results(owner=g.owner)
    # la matrice n'a besoin que du résumé : on allège la réponse
    for d in data["dossiers"]:
        for c in d["cells"].values():
            c.pop("occurrences")
    return jsonify(data)


@app.get("/api/dossiers/<int:did>/keyword/<int:kid>")
def cell_detail(did, kid):
    own_dossier(did)
    data = dossier_results(did, owner=g.owner)
    if not data["dossiers"]:
        abort(404)
    cell = data["dossiers"][0]["cells"].get(kid)
    if cell is None:
        abort(404)
    return jsonify(cell)


@app.get("/api/settings")
def read_settings():
    return jsonify(get_settings(g.owner))


@app.post("/api/settings")
def write_settings():
    body = request.get_json(force=True)
    if "operators" in body:
        ops = [o.strip() for o in body["operators"] if isinstance(o, str) and o.strip()]
        ops = list(dict.fromkeys(ops))
        if not ops:
            abort(400, "Il faut au moins un prof")
        with db() as con:
            busy = {r["owner"]: r["n"] for r in con.execute("SELECT owner, COUNT(*) AS n FROM dossiers GROUP BY owner")}
        removed = [o for o in get_settings()["operators"] if o not in ops]
        gone = [o for o in removed if busy.get(o)]
        if gone:
            abort(409, f"{gone[0]} a encore {busy[gone[0]]} dossier(s) : confiez-les d'abord à un autre prof")
        # retirer un AUTRE profil protégé exige son code
        for o in removed:
            if o != g.owner and _pin_record(o):
                _throttle(o)
                if not _check_pin(o, body.get("pin")):
                    _fail(o)
                    abort(403, f"Code de {o} incorrect")
        body["operators"] = ops
    owner = g.owner                      # les seuils réglés sont toujours ceux du profil déverrouillé
    thresholds = {k: body[k] for k in PROFILE_DEFAULTS if k in body}
    with db() as con:
        if "operators" in body:
            old = get_settings()["operators"]
            con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('operators', ?)", (json.dumps(body["operators"]),))
            for o in body["operators"]:          # nouveau prof : profil vierge (seuils par défaut, aucun mot-clé)
                if o not in old:
                    save_profile(con, o, PROFILE_DEFAULTS)
            for o in old:                        # prof retiré (sans dossier) : son profil disparaît
                if o not in body["operators"]:
                    con.execute("DELETE FROM keywords WHERE owner=? AND dossier_id=0", (o,))
                    con.execute("DELETE FROM settings WHERE key IN (?, ?)", (f"profile:{o}", f"pin:{o}"))
        if thresholds:
            save_profile(con, owner, thresholds)
    if owner not in body.get("operators", [owner]):  # on vient de retirer son propre profil
        session.clear()
    return jsonify(get_settings(owner))


LABELS = {"present": "Présent", "a_verifier": "À vérifier", "absent": "Absent", "absent_douteux": "Absence incertaine"}


@app.get("/export.csv")
def export_csv():
    """Export tableur : une ligne par (dossier, mot-clé). Séparateur ';' pour Excel en français."""
    owner = g.owner
    data = dossier_results(owner=owner)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Dossier", "Responsable", "Mot-clé", "Décision", "Score de présence (%)", "Fiabilité de la décision (%)",
                "Nb occurrences", "Documents (pages)", "Qualité de lecture du dossier (%)", "Documents en attente",
                "Documents non lus"])
    for d in data["dossiers"]:
        for c in sorted(d["cells"].values(), key=lambda c: c["term"].lower()):  # mots-clés du prof du dossier
            where = {}
            for o in c["occurrences"]:
                where.setdefault(o["filename"], set()).add(o["page"])
            loc = " | ".join(f"{f} (p. {', '.join(map(str, sorted(p)))})" for f, p in where.items())
            w.writerow([d["name"], d["owner"], c["term"], LABELS[c["decision"]], str(c["score"]).replace(".", ","),
                        str(c["reliability"]).replace(".", ","), c["count"], loc,
                        str(d["quality"]).replace(".", ","), d["pending"],
                        f"{len(d['unread'])}" + (f" ({' | '.join(d['unread'])})" if d["unread"] else "")])
    data_bytes = ("﻿" + buf.getvalue()).encode("utf-8")
    return send_file(io.BytesIO(data_bytes), mimetype="text/csv",
                     download_name=f"keyscan_{secure_filename(owner) + '_' if owner else ''}{datetime.now():%Y%m%d_%H%M}.csv", as_attachment=True)


@app.get("/api/status")
def status():
    return jsonify({"queue": jobs.qsize(), "tesseract": pytesseract_cmd, "handwriting": handwriting_status(),
                    "engine_version": engine_version()})


# =========================================================================== démarrage
pytesseract_cmd = None


def start():
    global pytesseract_cmd
    init_db()
    pytesseract_cmd = configure_tesseract()
    if not pytesseract_cmd:
        print("\n⚠  Tesseract introuvable : l'OCR (PDF scannés, images) ne fonctionnera pas.\n"
              "   Installez-le (voir README) ou indiquez son chemin dans la variable TESSERACT_CMD.\n")
    # nouveau moteur de détection : on relit tous les documents avec lui
    with db() as con:
        version = engine_version()
        old = con.execute("SELECT value FROM settings WHERE key='engine_version'").fetchone()
        if not old or json.loads(old["value"]) != version:
            n = con.execute("UPDATE documents SET status='en_attente', progress_done=0 WHERE status IN ('ok','erreur')").rowcount
            con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('engine_version', ?)", (json.dumps(version),))
            if n:
                print(f"Moteur {version} : {n} document(s) vont être ré-analysés.")
    hw = handwriting_status()
    print("Écriture manuscrite : " + (f"activée ({hw.get('label')})" if hw.get("ready") else
          "non installée (python -m engine.handwriting --install)"))
    # reprise des analyses interrompues
    with db() as con:
        for r in con.execute("SELECT id FROM documents WHERE status IN ('en_attente','en_cours')"):
            jobs.put(r["id"])
    n_workers = max(1, min(4, (os.cpu_count() or 2) - 1))
    if n_workers > 1:
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # un cœur par Tesseract, sinon ils se gênent
    for _ in range(n_workers):
        threading.Thread(target=worker, daemon=True).start()
    print(f"Analyse en parallèle : {n_workers} document(s) à la fois")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--reset-pin", metavar="NOM", help="efface le code PIN d'un profil (code oublié)")
    a = ap.parse_args()
    if a.reset_pin:
        init_db()
        with db() as con:
            n = con.execute("DELETE FROM settings WHERE key=?", (f"pin:{a.reset_pin}",)).rowcount
        print(f"Code de « {a.reset_pin} » effacé : un nouveau code sera demandé à la prochaine ouverture du profil."
              if n else f"Aucun code trouvé pour « {a.reset_pin} ». Profils : {', '.join(get_settings()['operators'])}")
        sys.exit(0)
    start()
    url = f"http://{'127.0.0.1' if a.host == '0.0.0.0' else a.host}:{a.port}"
    print(f"\nKeyScan est lancé : {url}\n(Ctrl+C pour arrêter)\n")
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=a.host, port=a.port, debug=False, threaded=True)
