"""
Le calcul des résultats : pour chaque dossier et chacun de SES mots-clés, une décision
(Présent, À vérifier, Absent, Absence incertaine) et la liste des endroits où le mot a été lu.

Chaque dossier est jugé avec les seuils de son responsable. Deux règles de fiabilité :
  - un fichier déposé deux fois (même contenu) n'est compté qu'une fois ;
  - si un document du dossier n'a pas pu être lu, aucune absence n'est affirmée.

Le calcul est refait à chaque demande : il est rapide, car les documents ne sont lus qu'une fois
(voir analysis.py) et les recherches de mots sont gardées en mémoire.
"""
from __future__ import annotations

import json

from engine.decision import PRESENT, TO_CHECK, evaluate

from .analysis import handwriting_status, occurrences, progress
from .database import connect
from .profiles import settings_for, thresholds


def all_results(owner: str, dossier_ids: list[int] | None = None) -> dict:
    """
    Les résultats des dossiers d'un prof (ou seulement de certains d'entre eux), et ce qu'il faut à l'interface :
        keywords        sa liste de mots-clés par défaut
        dossiers        les dossiers, chacun avec ses documents et ses « cells » (une par mot-clé)
        settings        ses seuils et l'équipe
        owners          nombre de dossiers de chaque prof
        keyword_counts  nombre de mots-clés par défaut de chaque prof
        engine          état du module manuscrit
    """
    with connect() as db:
        dossiers = _load_dossiers(db, owner, dossier_ids)
        default_keywords = [dict(row) for row in db.execute(
            "SELECT id, owner, term, created_by FROM keywords WHERE dossier_id=0 ORDER BY lower(term)")]
        dossiers_per_owner = {row["owner"]: row["n"] for row in db.execute("SELECT owner, COUNT(*) AS n FROM dossiers GROUP BY owner")}

    keyword_counts: dict[str, int] = {}
    for keyword in default_keywords:
        keyword_counts[keyword["owner"]] = keyword_counts.get(keyword["owner"], 0) + 1
    handwriting = handwriting_status()
    return {
        "keywords": [keyword for keyword in default_keywords if keyword["owner"] == owner],
        "dossiers": [dossier_result(dossier) for dossier in dossiers],
        "settings": settings_for(owner),
        "owners": dossiers_per_owner,
        "keyword_counts": keyword_counts,
        "engine": {"handwriting": {"ready": handwriting.get("ready", False), "libraries": handwriting.get("libraries", False),
                                   "label": handwriting.get("label")}},
    }


def _load_dossiers(db, owner: str, dossier_ids: list[int] | None) -> list[dict]:
    """Les dossiers du prof, chacun avec ses documents (« documents ») et ses mots-clés (« keywords »)."""
    sql, args = "SELECT * FROM dossiers WHERE owner=?", [owner]
    if dossier_ids is not None:
        sql += f" AND id IN ({','.join('?' * len(dossier_ids))})"
        args += dossier_ids
    dossiers = [dict(row) for row in db.execute(sql + " ORDER BY created_at DESC, id DESC", args)]
    for dossier in dossiers:
        dossier["documents"] = [dict(row) for row in db.execute(
            "SELECT id, filename, status, error, pages, quality, uploaded_by, uploaded_at, analysed_at, "
            "progress_done, progress_total, started_at, sha256 FROM documents WHERE dossier_id=? ORDER BY id", (dossier["id"],))]
        dossier["keywords"] = [dict(row) for row in db.execute(
            "SELECT id, term, created_by FROM keywords WHERE dossier_id=? ORDER BY lower(term)", (dossier["id"],))]
    return dossiers


def dossier_result(dossier: dict) -> dict:
    """Le résultat d'un dossier (mêmes clés que l'interface attend)."""
    limits = thresholds(dossier["owner"])
    documents = dossier["documents"]
    _mark_duplicates(documents)
    counted = [document for document in documents if not document["duplicate_of"]]
    read = [document for document in counted if document["status"] == "ok"]
    unread = [document for document in counted if document["status"] == "erreur"]
    quality = min((document["quality"] or 0) for document in read) if read else 0.0      # le document le moins bien lu
    pages = [page for document in read for page in _pages(document)]

    cells = {keyword["id"]: _cell(keyword["term"], read, quality, pages, len(unread), limits)
             for keyword in dossier["keywords"]}
    hits = _hits_per_document(cells, limits["present_thr"])
    return {
        "id": dossier["id"], "name": dossier["name"], "owner": dossier["owner"],
        "created_by": dossier["created_by"], "created_at": dossier["created_at"],
        "quality": round(quality, 1),
        "pending": sum(1 for document in counted if document["status"] in ("en_attente", "en_cours")),
        "unread": [document["filename"] for document in unread],
        "keywords": dossier["keywords"],
        "documents": [{
            "id": document["id"], "filename": document["filename"], "status": document["status"], "error": document["error"],
            "quality": document["quality"], "pages": _pages(document),
            "uploaded_by": document["uploaded_by"], "uploaded_at": document["uploaded_at"],
            "progress": progress(document), "duplicate_of": document["duplicate_of"],
            "hits": hits.get(document["id"], []),
        } for document in documents],
        "cells": cells,
    }


def _pages(document: dict) -> list[dict]:
    return json.loads(document["pages"]) if document["pages"] else []


def _mark_duplicates(documents: list[dict]):
    """« duplicate_of » = nom du premier document au contenu identique dans le dossier (sinon None)."""
    first_with_fingerprint: dict[str, str] = {}
    for document in documents:
        fingerprint = document["sha256"]
        document["duplicate_of"] = first_with_fingerprint.get(fingerprint) if fingerprint else None
        if fingerprint and not document["duplicate_of"]:
            first_with_fingerprint[fingerprint] = document["filename"]


def _cell(term: str, read_documents: list[dict], quality: float, pages: list[dict], unread: int, limits: dict) -> dict:
    """La case (dossier, mot-clé) : score, décision, fiabilité, et toutes les occurrences trouvées."""
    found = [{**occurrence, "doc_id": document["id"], "filename": document["filename"]}
             for document in read_documents for occurrence in occurrences(document["id"], term)]
    score, decision = evaluate(term, found, quality, pages, limits["present_thr"], limits["review_thr"],
                               limits["min_quality"], unread=unread)
    return {
        "term": term, "score": score, "decision": decision,
        # fiabilité : le score si le mot est trouvé, la qualité de lecture s'il ne l'est pas
        "reliability": score if decision in (PRESENT, TO_CHECK) else round(quality, 1),
        "count": len(found),
        "occurrences": found,
        # où le mot a été lu (fichier, page), sans doublon
        "where": [{"file": file, "page": page} for file, page in dict.fromkeys((o["filename"], o["page"]) for o in found)],
    }


def is_sure(occurrence: dict, present_threshold: float) -> bool:
    """Une occurrence « sûre » : lue avec certitude et avec un score au-dessus du seuil « Présent »."""
    return occurrence.get("certain", True) and occurrence["score"] * 100 >= present_threshold


def _hits_per_document(cells: dict, present_threshold: float) -> dict[int, list]:
    """
    Pour chaque document : les mots-clés trouvés, leurs pages, et s'il y a une occurrence à vérifier.
    Les mots à vérifier viennent en premier.
    """
    hits: dict[int, list] = {}
    for keyword_id, cell in cells.items():
        per_document: dict[int, dict] = {}
        for occurrence in cell["occurrences"]:
            hit = per_document.setdefault(occurrence["doc_id"], {
                "kid": keyword_id, "term": cell["term"], "decision": cell["decision"], "pages": [], "review": False})
            if occurrence["page"] not in hit["pages"]:
                hit["pages"].append(occurrence["page"])
            if not is_sure(occurrence, present_threshold):
                hit["review"] = True
        for document_id, hit in per_document.items():
            hits.setdefault(document_id, []).append(hit)
    for document_hits in hits.values():
        document_hits.sort(key=lambda hit: (not hit["review"], hit["term"].lower()))
    return hits
