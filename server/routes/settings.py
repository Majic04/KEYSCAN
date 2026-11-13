"""Les réglages : les seuils du profil ouvert, la composition de l'équipe, et l'état du serveur."""
from flask import Blueprint, abort, jsonify, request, session

from engine.ocr import find_tesseract

from ..analysis import handwriting_status, waiting_documents
from ..database import connect, read_setting, write_setting
from ..migrations import DEFAULT_THRESHOLDS
from ..profiles import (current_owner, note_failure, pin_is_correct, pin_record, refuse_if_blocked, save_thresholds,
                        settings_for, team)

routes = Blueprint("settings", __name__)


@routes.get("/api/settings")
def get_settings():
    return jsonify(settings_for(current_owner()))


@routes.post("/api/settings")
def change_settings():
    """
    {"present_thr", "review_thr", "min_quality"} : les seuils du profil ouvert.
    {"operators": [noms], "pin": code} : la nouvelle équipe. Retirer un AUTRE prof protégé par un code exige son code,
    et un prof qui a encore des dossiers ne peut pas être retiré.
    """
    body = request.get_json(force=True)
    me = current_owner()
    if "operators" in body:
        _change_team(body["operators"], body.get("pin"), me)
    values = {key: body[key] for key in DEFAULT_THRESHOLDS if key in body}
    if values and me in team():
        save_thresholds(me, values)
    if me not in team():                         # on vient de retirer son propre profil
        session.clear()
    return jsonify(settings_for(me))


def _change_team(names, pin, me: str):
    new_team = list(dict.fromkeys(name.strip() for name in names if isinstance(name, str) and name.strip()))
    if not new_team:
        abort(400, "Il faut au moins un prof")
    old_team = team()
    removed = [person for person in old_team if person not in new_team]
    with connect() as db:
        dossiers = {row["owner"]: row["n"] for row in db.execute("SELECT owner, COUNT(*) AS n FROM dossiers GROUP BY owner")}
    for person in removed:
        if dossiers.get(person):
            abort(409, f"{person} a encore {dossiers[person]} dossier(s) : confiez-les d'abord à un autre prof")
    for person in removed:
        if person != me and pin_record(person):
            refuse_if_blocked(person)
            if not pin_is_correct(person, pin):
                note_failure(person)
                abort(403, f"Code de {person} incorrect")
    with connect() as db:
        write_setting("operators", new_team, db)
        for person in new_team:                  # nouveau prof : seuils par défaut, aucun mot-clé
            if person not in old_team:
                write_setting(f"profile:{person}", {key: float(value) for key, value in DEFAULT_THRESHOLDS.items()}, db)
        for person in removed:                   # prof retiré (sans dossier) : son profil disparaît
            db.execute("DELETE FROM keywords WHERE owner=? AND dossier_id=0", (person,))
            db.execute("DELETE FROM settings WHERE key IN (?, ?)", (f"profile:{person}", f"pin:{person}"))


@routes.get("/api/status")
def status():
    return jsonify({"queue": waiting_documents.qsize(), "tesseract": find_tesseract(), "handwriting": handwriting_status(),
                    "engine_version": read_setting("engine_version")})
