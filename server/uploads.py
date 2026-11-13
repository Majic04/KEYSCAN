"""
Le dépôt des fichiers.

Un fichier déposé est enregistré dans data/files, puis mis dans la file de lecture (voir analysis.py).
Un fichier au contenu identique à un document déjà présent dans le dossier n'est pas ajouté (doublon).

Plusieurs candidats d'un coup : on peut déposer un dossier entier (ou un .zip) qui contient un
sous-dossier par candidat. Chaque sous-dossier devient un dossier KeyScan, et tous les documents
sont lus en parallèle.
    Candidats/                       → dossiers « Dupont Marie » et « Martin Paul »
        Dupont Marie/cv.pdf
        Dupont Marie/releve.jpg
        Martin Paul/lettre.pdf
"""
from __future__ import annotations

import hashlib
import io
import os
import zipfile

from werkzeug.utils import secure_filename

from engine.extract import SUPPORTED_EXTENSIONS, page_count

from .analysis import queue_document
from .database import FILES_DIR, connect, now
from .keywords import DEFAULT_LIST, copy_list


def is_supported(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in SUPPORTED_EXTENSIONS


def save_file(dossier_id: int, filename: str, data: bytes, person: str) -> int | str | None:
    """
    Enregistre un document et le met en file de lecture. Retourne :
        son numéro           s'il est ajouté
        le nom d'un document si c'est un doublon de ce document (il n'est pas ajouté)
        None                 si le format n'est pas accepté (ou le fichier est vide)
    """
    name = os.path.basename(filename)
    extension = os.path.splitext(name)[1].lower()
    if not is_supported(name) or not data:
        return None
    fingerprint = hashlib.sha256(data).hexdigest()
    with connect() as db:
        same = db.execute("SELECT filename FROM documents WHERE dossier_id=? AND sha256=?", (dossier_id, fingerprint)).fetchone()
        if same:
            return same["filename"]
        document_id = db.execute(
            "INSERT INTO documents(dossier_id, filename, path, uploaded_by, uploaded_at, sha256) VALUES (?,?,?,?,?,?)",
            (dossier_id, name, "", person, now(), fingerprint)).lastrowid
        path = os.path.join(FILES_DIR, f"{document_id}_{secure_filename(name) or 'fichier' + extension}")
        with open(path, "wb") as f:
            f.write(data)
        # le nombre de pages est connu dès le dépôt : la file d'attente affiche « 0/30 pages »
        db.execute("UPDATE documents SET path=?, progress_done=0, progress_total=? WHERE id=?", (path, page_count(path), document_id))
    queue_document(document_id)
    return document_id


def save_files(dossier_id: int, files: list[tuple[str, bytes]], person: str) -> dict:
    """Dépose plusieurs fichiers [(nom, contenu)] dans un dossier → {"added", "rejected", "duplicates"}."""
    added, rejected, duplicates = [], [], []
    for filename, data in files:
        result = save_file(dossier_id, filename, data, person)
        if isinstance(result, str):
            duplicates.append({"file": filename, "same_as": result})
        elif result:
            added.append(result)
        else:
            rejected.append(filename)
    return {"added": added, "rejected": rejected, "duplicates": duplicates}


# =========================================================================== plusieurs candidats d'un coup
def group_by_candidate(files: list[tuple[str, bytes]], fallback_name: str) -> dict[str, list[tuple[str, bytes]]]:
    """
    Range des fichiers [(chemin relatif, contenu)] par candidat : le premier dossier du chemin donne le nom
    du candidat. Si tout est dans un seul dossier englobant (« Candidats/… »), on regarde à l'intérieur.
    Les fichiers posés à la racine vont dans un dossier nommé « fallback_name ».
    """
    entries = []
    for path, data in files:
        parts = [part for part in path.replace("\\", "/").split("/") if part]
        if parts and not any(part.startswith(".") or part == "__MACOSX" for part in parts):
            entries.append((parts, data))
    roots = {parts[0] for parts, _ in entries}
    if len(roots) == 1 and all(len(parts) > 1 for parts, _ in entries):
        fallback_name = roots.pop()                    # un seul dossier englobant : on entre dedans
        entries = [(parts[1:], data) for parts, data in entries]
    groups: dict[str, list[tuple[str, bytes]]] = {}
    for parts, data in entries:
        candidate = parts[0] if len(parts) > 1 else fallback_name
        groups.setdefault(candidate, []).append((parts[-1], data))
    return groups


def zip_entries(archive: bytes) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        return [(info.filename, z.read(info)) for info in z.infolist() if not info.is_dir()]


def import_candidates(files: list[tuple[str, bytes]], fallback_name: str, person: str) -> dict:
    """
    Crée un dossier par candidat (avec la liste de mots-clés par défaut du prof) et y dépose ses fichiers.
    → {"dossiers": [noms], "ids": [numéros], "rejected": [fichiers refusés], "duplicates": [...]}
    """
    names, ids, rejected, duplicates = [], [], [], []
    for candidate, candidate_files in group_by_candidate(files, fallback_name).items():
        accepted = [(name, data) for name, data in candidate_files if is_supported(name)]
        rejected += [name for name, _ in candidate_files if not is_supported(name)]
        if not accepted:
            continue
        with connect() as db:
            dossier_id = db.execute("INSERT INTO dossiers(name, owner, created_by, created_at) VALUES (?,?,?,?)",
                                    (candidate, person, person, now())).lastrowid
            copy_list(db, person, person, DEFAULT_LIST, dossier_id)
        result = save_files(dossier_id, accepted, person)
        names.append(candidate)
        ids.append(dossier_id)
        rejected += result["rejected"]
        duplicates += result["duplicates"]
    return {"dossiers": names, "ids": ids, "rejected": rejected, "duplicates": duplicates}
