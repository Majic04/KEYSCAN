"""Les mots-clés : la liste par défaut du prof (dossier 0) et la liste propre à chaque dossier."""
from flask import Blueprint, jsonify, request

from ..database import connect
from ..keywords import DEFAULT_LIST, add_terms, copy_list, parse_terms
from ..profiles import check_member, current_owner, require_own_dossier

routes = Blueprint("keywords", __name__)


def _which_list(dossier) -> int:
    """0 (ou rien) = la liste par défaut ; sinon un dossier, qui doit appartenir au profil ouvert."""
    dossier_id = int(dossier or DEFAULT_LIST)
    if dossier_id != DEFAULT_LIST:
        require_own_dossier(dossier_id)
    return dossier_id


@routes.get("/api/keywords")
def list_keywords():
    dossier_id = _which_list(request.args.get("dossier"))
    with connect() as db:
        rows = db.execute("SELECT id, dossier_id, term, created_by, created_at FROM keywords "
                          "WHERE owner=? AND dossier_id=? ORDER BY lower(term)", (current_owner(), dossier_id))
        return jsonify([dict(row) for row in rows])


@routes.post("/api/keywords")
def add_keywords():
    body = request.get_json(force=True)
    dossier_id = _which_list(body.get("dossier"))
    with connect() as db:
        added, skipped = add_terms(db, current_owner(), dossier_id, parse_terms(body.get("terms", "")))
    return jsonify({"added": added, "skipped": skipped})


@routes.post("/api/keywords/copy")
def copy_keywords():
    """
    Reprendre une liste de mots-clés (ceux déjà présents sont ignorés) :
        {"from": "<prof>"}                      la liste par défaut d'un autre prof → ma liste par défaut
        {"dossier": D, "source": "default"}     ma liste par défaut → le dossier D
        {"dossier": D, "source": <dossier>}     les mots-clés d'un autre de mes dossiers → le dossier D
    """
    body = request.get_json(force=True)
    me = current_owner()
    with connect() as db:
        if body.get("dossier"):
            target = _which_list(body["dossier"])
            source = body.get("source", "default")
            added = copy_list(db, me, me, DEFAULT_LIST if source == "default" else _which_list(source), target)
        else:
            added = copy_list(db, me, check_member(body.get("from")), DEFAULT_LIST, DEFAULT_LIST)
    return jsonify({"added": added})


@routes.delete("/api/keywords/<int:keyword_id>")
def delete_keyword(keyword_id):
    with connect() as db:
        db.execute("DELETE FROM keywords WHERE id=? AND owner=?", (keyword_id, current_owner()))
    return jsonify({"ok": True})
