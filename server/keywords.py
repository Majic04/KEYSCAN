"""
Les listes de mots-clés.

Chaque dossier a sa propre liste. Chaque prof a aussi une « liste par défaut » (dossier_id = 0),
recopiée dans ses nouveaux dossiers. Deux mots-clés qui ne diffèrent que par les accents ou les
majuscules sont le même mot-clé (on compare leur forme normalisée, colonne « norm »).
"""
from __future__ import annotations

import re
import sqlite3

from engine.text import normalize

from .database import now

DEFAULT_LIST = 0


def parse_terms(raw: str) -> list[str]:
    """Une liste collée : un mot-clé par ligne, ou séparés par « ; » ou « , »."""
    return [term.strip() for term in re.split(r"[\n;,]", raw or "") if term.strip()]


def normalized_form(term: str) -> str:
    return " ".join(normalize(term).split())


def add_terms(db, owner: str, dossier_id: int, terms: list[str]) -> tuple[list[str], list[str]]:
    """Ajoute des mots-clés à une liste. Retourne (ajoutés, ignorés : vides ou déjà présents)."""
    added, skipped = [], []
    for term in terms:
        norm = normalized_form(term)
        if not any(character.isalnum() for character in norm):
            skipped.append(term)
            continue
        try:
            db.execute("INSERT INTO keywords(owner, dossier_id, term, norm, created_by, created_at) VALUES (?,?,?,?,?,?)",
                       (owner, dossier_id, term, norm, owner, now()))
            added.append(term)
        except sqlite3.IntegrityError:                # déjà dans la liste
            skipped.append(term)
    return added, skipped


def copy_list(db, owner: str, from_owner: str, from_dossier: int, to_dossier: int) -> int:
    """Recopie une liste dans une autre (les mots déjà présents sont ignorés). Retourne le nombre de mots ajoutés."""
    def size():
        return db.execute("SELECT COUNT(*) FROM keywords WHERE owner=? AND dossier_id=?", (owner, to_dossier)).fetchone()[0]
    before = size()
    db.execute("""INSERT OR IGNORE INTO keywords(owner, dossier_id, term, norm, created_by, created_at)
                  SELECT ?, ?, term, norm, created_by, ? FROM keywords WHERE owner=? AND dossier_id=?""",
               (owner, to_dossier, now(), from_owner, from_dossier))
    return size() - before
