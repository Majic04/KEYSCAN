"""Ouvrir et fermer un profil : écran de verrouillage, premier code, changement de code."""
from flask import Blueprint, abort, jsonify, request, session

from ..database import connect
from ..profiles import (IDLE_MINUTES, check_member, check_pin_format, current_owner, note_failure, open_session,
                        pin_is_correct, pin_record, pin_reset_notice, refuse_if_blocked, session_owner, set_pin, team)

routes = Blueprint("session", __name__)


@routes.get("/api/session")
def get_session():
    """Le profil ouvert dans ce navigateur (ou aucun), et la liste des profils pour l'écran de verrouillage."""
    with connect() as db:
        dossiers = {row["owner"]: row["n"] for row in db.execute("SELECT owner, COUNT(*) AS n FROM dossiers GROUP BY owner")}
    profiles = []
    for person in team():
        record = pin_record(person)
        profiles.append({"name": person, "has_pin": bool(record), "pin_len": record["len"] if record else None,
                         "dossiers": dossiers.get(person, 0)})
    return jsonify({"owner": session_owner(), "profiles": profiles, "idle_minutes": IDLE_MINUTES,
                    "updated_to": pin_reset_notice(profiles)})


@routes.post("/api/unlock")
def unlock():
    body = request.get_json(force=True)
    person = check_member(body.get("owner"))
    record = pin_record(person)
    if not record:
        abort(409, "Ce profil n'a pas encore de code")
    refuse_if_blocked(person)
    if not pin_is_correct(person, body.get("pin")):
        note_failure(person)
        refuse_if_blocked(person)
        abort(403, "Code incorrect")
    open_session(person, record)
    return jsonify({"owner": person})


@routes.post("/api/pin/setup")
def setup_pin():
    """Premier code d'un profil qui n'en a pas encore ; le profil est ensuite ouvert."""
    body = request.get_json(force=True)
    person = check_member(body.get("owner"))
    if pin_record(person):
        abort(409, "Ce profil a déjà un code")
    open_session(person, set_pin(person, check_pin_format(body.get("pin"))))
    return jsonify({"owner": person})


@routes.post("/api/pin/change")
def change_pin():
    """Changer son code : l'ancien est exigé, et les autres navigateurs ouverts sur ce profil sont verrouillés."""
    body = request.get_json(force=True)
    person = current_owner()
    refuse_if_blocked(person)
    if not pin_is_correct(person, body.get("old")):
        note_failure(person)
        abort(403, "Code actuel incorrect")
    open_session(person, set_pin(person, check_pin_format(body.get("new"))))
    return jsonify({"ok": True})


@routes.post("/api/lock")
def lock():
    session.clear()
    return jsonify({"ok": True})
