"""
Les profils : l'équipe, les seuils de chaque personne, et les codes PIN.

Règles de sécurité :
  - un navigateur n'a qu'un profil ouvert à la fois, mémorisé dans un cookie signé ;
  - le serveur ne croit jamais un nom envoyé par le navigateur : chaque route utilise le profil ouvert ;
  - un code PIN n'est jamais enregistré en clair : on garde son empreinte (PBKDF2, 200 000 tours, sel aléatoire) ;
  - après 5 erreurs, il faut attendre (30 s, puis de plus en plus longtemps, 15 min au plus) ;
  - le profil se verrouille après 30 minutes sans activité ;
  - changer son code verrouille les autres navigateurs ouverts sur ce profil (le « nonce » change).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

from flask import abort, g, session

from .database import connect, create_tables, delete_setting, read_setting, write_setting
from .migrations import DEFAULT_TEAM, DEFAULT_THRESHOLDS

IDLE_MINUTES = 30


# =========================================================================== l'équipe et les seuils
def team() -> list[str]:
    return read_setting("operators", DEFAULT_TEAM)


def check_member(name) -> str:
    """Le nom doit être celui d'un membre de l'équipe (sinon : erreur 400)."""
    members = team()
    if name in members:
        return name
    abort(400, f"Prof inconnu : {name}" if members else "Aucun prof déclaré dans les réglages")


def thresholds(person: str | None) -> dict:
    """Les seuils de décision d'une personne : {"present_thr", "review_thr", "min_quality"}."""
    values = dict(DEFAULT_THRESHOLDS)
    if person:
        saved = read_setting(f"profile:{person}", {})
        values.update({key: value for key, value in saved.items() if key in DEFAULT_THRESHOLDS})
    return values


def settings_for(person: str | None) -> dict:
    """Ce que l'interface reçoit : l'équipe, les seuils de la personne et son nom."""
    result = {**thresholds(person), "operators": team()}
    if person:
        result["profile"] = person
    return result


def save_thresholds(person: str, values: dict, db=None):
    current = thresholds(person)
    for key, value in values.items():
        if key in DEFAULT_THRESHOLDS:
            current[key] = max(0.0, min(100.0, float(value)))
    write_setting(f"profile:{person}", current, db)


# =========================================================================== codes PIN
def pin_record(person: str) -> dict | None:
    """{"salt", "hash", "len", "nonce"} ou None si la personne n'a pas encore de code."""
    return read_setting(f"pin:{person}") if person else None


def _pin_hash(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 200_000).hex()


def set_pin(person: str, pin: str) -> dict:
    salt = secrets.token_bytes(16)
    record = {"salt": salt.hex(), "hash": _pin_hash(pin, salt), "len": len(pin), "nonce": secrets.token_hex(8)}
    write_setting(f"pin:{person}", record)
    return record


def pin_is_correct(person: str, pin) -> bool:
    record = pin_record(person)
    if not record:
        return False
    return hmac.compare_digest(record["hash"], _pin_hash(str(pin), bytes.fromhex(record["salt"])))


def check_pin_format(pin) -> str:
    pin = str(pin or "")
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        abort(400, "Le code doit contenir de 4 à 8 chiffres")
    return pin


def reset_pins_on_new_version(version: str) -> bool:
    """
    Application installée : à la première ouverture d'une nouvelle version, les codes PIN sont effacés et
    chaque profil en choisit un nouveau. Dossiers, mots-clés et réglages sont conservés.
    Retourne True si des codes viennent d'être effacés.
    """
    create_tables()
    if read_setting("app_version") == version:
        return False
    with connect() as db:
        erased = db.execute("DELETE FROM settings WHERE key LIKE 'pin:%'").rowcount
        write_setting("app_version", version, db)
        if erased:
            write_setting("pin_reset_notice", version, db)    # message affiché sur l'écran d'accueil
    return bool(erased)


# =========================================================================== trop d'essais
_failures: dict[str, dict] = {}          # personne → {"count": erreurs, "blocked_until": heure}
_failures_lock = threading.Lock()


def refuse_if_blocked(person: str):
    with _failures_lock:
        blocked_until = _failures.get(person, {}).get("blocked_until", 0.0)
    wait = blocked_until - time.time()
    if wait > 0:
        abort(429, f"Trop d'essais : réessayez dans {int(wait) + 1} s")


def note_failure(person: str):
    """Toutes les 5 erreurs : blocage de 30 s, puis 60 s, 120 s… (15 minutes au plus)."""
    with _failures_lock:
        entry = _failures.setdefault(person, {"count": 0, "blocked_until": 0.0})
        entry["count"] += 1
        if entry["count"] % 5 == 0:
            entry["blocked_until"] = time.time() + min(900, 30 * 2 ** (entry["count"] // 5 - 1))


# =========================================================================== session (profil ouvert dans ce navigateur)
def open_session(person: str, record: dict):
    session.clear()
    session["owner"], session["nonce"], session["t"] = person, record["nonce"], time.time()
    with _failures_lock:
        _failures.pop(person, None)


def session_owner() -> str | None:
    """Le profil ouvert dans ce navigateur, s'il est toujours valable (code inchangé, pas d'inactivité trop longue)."""
    person = session.get("owner")
    if not person or person not in team():
        return None
    record = pin_record(person)
    if not record or record["nonce"] != session.get("nonce"):
        return None
    if time.time() - session.get("t", 0) > IDLE_MINUTES * 60:
        return None
    return person


def current_owner() -> str:
    """Le profil de la requête en cours (fixé par la vérification faite avant chaque requête)."""
    return g.owner


def pin_reset_notice(profiles: list[dict]) -> str | None:
    """Après une mise à jour : version affichée tant qu'un profil n'a pas recréé son code."""
    notice = read_setting("pin_reset_notice")
    if notice and all(p["has_pin"] for p in profiles):
        delete_setting("pin_reset_notice")
        return None
    return notice


# =========================================================================== à qui appartient quoi
def require_own_dossier(dossier_id: int):
    """Le dossier doit appartenir au profil ouvert ; sinon on répond « introuvable » (sans dire qu'il existe)."""
    with connect() as db:
        row = db.execute("SELECT owner FROM dossiers WHERE id=?", (dossier_id,)).fetchone()
    if not row or row["owner"] != current_owner():
        abort(404, "Dossier introuvable")


def require_own_document(document_id: int):
    with connect() as db:
        row = db.execute("SELECT s.owner FROM documents d JOIN dossiers s ON s.id = d.dossier_id WHERE d.id=?",
                         (document_id,)).fetchone()
    if not row or row["owner"] != current_owner():
        abort(404, "Document introuvable")


def forget_pin(person: str) -> bool:
    """Code oublié : efface le code d'un profil (un nouveau sera demandé). Retourne False s'il n'y en avait pas."""
    create_tables()
    with connect() as db:
        return db.execute("DELETE FROM settings WHERE key=?", (f"pin:{person}",)).rowcount > 0
