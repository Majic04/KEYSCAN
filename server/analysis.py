"""
La lecture des documents, en arrière-plan.

Quand un document est déposé, son numéro est mis dans une file d'attente. Plusieurs « ouvriers »
(des fils d'exécution) prennent les documents de la file et les lisent en même temps : jusqu'à 4
documents à la fois, quel que soit leur dossier. Pendant la lecture, l'avancement (pages lues / pages
en tout) est écrit dans la base, ce qui permet à l'interface d'afficher la progression.

Les mots lus sont enregistrés une fois pour toutes. Chercher un mot-clé est ensuite instantané :
ajouter un mot-clé ne relance pas la lecture.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import traceback

from engine import ENGINE_VERSION
from engine.extract import page_count, read_document
from engine.search import find_keyword
from engine.text import normalize

from .database import connect, now, read_setting, write_setting

waiting_documents: "queue.Queue[int]" = queue.Queue()

# Mémoire de travail : mots lus de chaque document, et occurrences déjà cherchées (document, mot-clé).
_words_of_document: dict[int, list] = {}
_found_in_document: dict[tuple[int, str], list] = {}
_memory_lock = threading.Lock()


# =========================================================================== la file d'attente
def queue_document(document_id: int):
    waiting_documents.put(document_id)


def _read_one(document_id: int):
    """Lit un document et enregistre le résultat (ou l'erreur) dans la base."""
    with connect() as db:
        row = db.execute("SELECT path FROM documents WHERE id=?", (document_id,)).fetchone()
        if not row:
            return                                         # supprimé entre-temps
        db.execute("UPDATE documents SET status='en_cours', progress_done=0, progress_total=?, started_at=? WHERE id=?",
                   (page_count(row["path"]), time.time(), document_id))

    def report_progress(pages_done, pages_total):
        with connect() as db:
            db.execute("UPDATE documents SET progress_done=?, progress_total=? WHERE id=?", (pages_done, pages_total, document_id))

    try:
        result = read_document(row["path"], progress=report_progress)
    except Exception as error:  # noqa: BLE001 — fichier corrompu, protégé… : signalé dans l'interface
        traceback.print_exc()
        with connect() as db:
            db.execute("UPDATE documents SET status='erreur', error=? WHERE id=?", (str(error)[:500], document_id))
        return
    with connect() as db:
        db.execute("UPDATE documents SET status='ok', error=NULL, pages=?, quality=?, tokens=?, analysed_at=? WHERE id=?",
                   (json.dumps(result["pages"]), result["quality"], json.dumps(result["tokens"]), now(), document_id))
    forget(document_id)


def _worker():
    while True:
        document_id = waiting_documents.get()
        try:
            _read_one(document_id)
        except Exception:  # noqa: BLE001 — un ouvrier ne doit jamais s'arrêter
            traceback.print_exc()
        finally:
            waiting_documents.task_done()


def start_workers() -> int:
    """Démarre les ouvriers (un de moins que le nombre de cœurs, 4 au plus) et reprend les lectures interrompues."""
    with connect() as db:
        for row in db.execute("SELECT id FROM documents WHERE status IN ('en_attente', 'en_cours')"):
            queue_document(row["id"])
    count = max(1, min(4, (os.cpu_count() or 2) - 1))
    if count > 1:
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")   # un cœur par Tesseract, sinon ils se gênent
    for _ in range(count):
        threading.Thread(target=_worker, daemon=True).start()
    return count


def progress(document: dict) -> dict | None:
    """Avancement d'une lecture : {"done": pages lues, "total": pages, "eta": secondes restantes estimées}."""
    if document["status"] not in ("en_cours", "en_attente"):
        return None
    done, total = document.get("progress_done") or 0, document.get("progress_total") or 0
    eta = None
    if document["status"] == "en_cours" and done and total and document.get("started_at"):
        eta = round((time.time() - document["started_at"]) / done * (total - done))
    return {"done": done, "total": total, "eta": eta}


# =========================================================================== recherche (avec mémoire)
def forget(document_id: int):
    """Oublie ce qu'on a gardé en mémoire pour un document (relu ou supprimé)."""
    with _memory_lock:
        _words_of_document.pop(document_id, None)
        for key in [key for key in _found_in_document if key[0] == document_id]:
            del _found_in_document[key]


def _words(document_id: int) -> list:
    with _memory_lock:
        if document_id in _words_of_document:
            return _words_of_document[document_id]
    with connect() as db:
        row = db.execute("SELECT tokens FROM documents WHERE id=?", (document_id,)).fetchone()
    words = json.loads(row["tokens"]) if row and row["tokens"] else []
    with _memory_lock:
        _words_of_document[document_id] = words
    return words


def occurrences(document_id: int, term: str) -> list[dict]:
    """Les occurrences d'un mot-clé dans un document (cherchées une fois, puis gardées en mémoire)."""
    key = (document_id, normalize(term))
    with _memory_lock:
        if key in _found_in_document:
            return _found_in_document[key]
    found = find_keyword(_words(document_id), term)
    with _memory_lock:
        _found_in_document[key] = found
    return found


# =========================================================================== version du moteur
_handwriting = {"checked_at": 0.0, "status": None}


def handwriting_status() -> dict:
    """État du module d'écriture manuscrite (vérifié au plus une fois par minute)."""
    if _handwriting["status"] is None or time.time() - _handwriting["checked_at"] > 60:
        try:
            from engine import trocr
            _handwriting["status"] = trocr.status()
        except Exception as error:  # noqa: BLE001
            _handwriting["status"] = {"libraries": False, "ready": False, "error": str(error)}
        _handwriting["checked_at"] = time.time()
    return _handwriting["status"]


def reread_if_engine_changed():
    """Nouveau moteur (ou module manuscrit installé) : tous les documents sont relus avec lui."""
    status = handwriting_status()
    version = ENGINE_VERSION + (f"+manuscrit-{status.get('model')}" if status.get("ready") else "")
    if read_setting("engine_version") == version:
        return
    with connect() as db:
        count = db.execute("UPDATE documents SET status='en_attente', progress_done=0 WHERE status IN ('ok', 'erreur')").rowcount
        write_setting("engine_version", version, db)
    if count:
        print(f"Moteur {version} : {count} document(s) vont être relus.")
