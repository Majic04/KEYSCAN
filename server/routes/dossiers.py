"""
Les dossiers de candidature : créer, renommer, confier à un autre prof, supprimer, déposer des fichiers.
Et pour travailler sur plusieurs dossiers à la fois : importer tout un dossier de candidats (ou un .zip),
et appliquer une action à une sélection de dossiers.
"""
import os

from flask import Blueprint, abort, jsonify, request

from ..analysis import forget, queue_document
from ..database import connect, now, remove_file
from ..keywords import DEFAULT_LIST, add_terms, copy_list, normalized_form, parse_terms
from ..profiles import check_member, current_owner, require_own_dossier
from ..uploads import import_candidates, save_files, zip_entries

routes = Blueprint("dossiers", __name__)


@routes.post("/api/dossiers")
def create_dossier():
    """
    {"name": nom, "keywords_from": "default" | "none" | <dossier>, "terms": "mots-clés en plus"}
    Les mots-clés du nouveau dossier : la liste par défaut (si rien n'est précisé), ceux d'un autre dossier, ou aucun.
    """
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    if not name:
        abort(400, "Nom de dossier requis")
    me = current_owner()
    source = body.get("keywords_from", "default")
    if source not in (None, "", "none", "default"):
        require_own_dossier(int(source))
    with connect() as db:
        dossier_id = db.execute("INSERT INTO dossiers(name, owner, created_by, created_at) VALUES (?,?,?,?)",
                                (name, me, me, now())).lastrowid
        if source == "default":
            copy_list(db, me, me, DEFAULT_LIST, dossier_id)
        elif source not in (None, "", "none"):
            copy_list(db, me, me, int(source), dossier_id)
        add_terms(db, me, dossier_id, parse_terms(body.get("terms", "")))
    return jsonify({"id": dossier_id, "owner": me})


@routes.patch("/api/dossiers/<int:dossier_id>")
def change_dossier(dossier_id):
    """Renommer un dossier ({"name"}) et/ou le confier à un autre prof ({"owner"}) : ses mots-clés le suivent."""
    require_own_dossier(dossier_id)
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    with connect() as db:
        if name:
            db.execute("UPDATE dossiers SET name=? WHERE id=?", (name, dossier_id))
        if "owner" in body:
            new_owner = check_member(body["owner"])
            db.execute("UPDATE dossiers SET owner=? WHERE id=?", (new_owner, dossier_id))
            db.execute("UPDATE keywords SET owner=? WHERE dossier_id=?", (new_owner, dossier_id))
    return jsonify({"ok": True})


def _delete_dossier(db, dossier_id: int):
    for row in db.execute("SELECT id, path FROM documents WHERE dossier_id=?", (dossier_id,)).fetchall():
        remove_file(row["path"])
        forget(row["id"])
    db.execute("DELETE FROM keywords WHERE dossier_id=?", (dossier_id,))
    db.execute("DELETE FROM dossiers WHERE id=?", (dossier_id,))          # ses documents sont supprimés avec lui


@routes.delete("/api/dossiers/<int:dossier_id>")
def delete_dossier(dossier_id):
    require_own_dossier(dossier_id)
    with connect() as db:
        _delete_dossier(db, dossier_id)
    return jsonify({"ok": True})


@routes.post("/api/dossiers/<int:dossier_id>/files")
def upload_files(dossier_id):
    require_own_dossier(dossier_id)
    files = [(f.filename, f.read()) for f in request.files.getlist("files")]
    return jsonify(save_files(dossier_id, files, current_owner()))


# =========================================================================== plusieurs dossiers à la fois
@routes.post("/api/import-folder")
def import_folder():
    """
    Un dossier entier choisi dans le navigateur : les fichiers (« files ») et leur chemin relatif (« paths »,
    dans le même ordre). Chaque sous-dossier devient un dossier de candidature.
    """
    uploaded = request.files.getlist("files")
    paths = request.form.getlist("paths")
    if not uploaded:
        abort(400, "Aucun fichier reçu")
    files = [(paths[i] if i < len(paths) and paths[i] else f.filename, f.read()) for i, f in enumerate(uploaded)]
    return jsonify(import_candidates(files, request.form.get("name") or "Import", current_owner()))


@routes.post("/api/import-zip")
def import_zip():
    """Un .zip : chaque dossier qu'il contient devient un dossier de candidature."""
    archive = request.files.get("archive")
    if not archive:
        abort(400, "Archive manquante")
    fallback_name = os.path.splitext(os.path.basename(archive.filename or "Import"))[0]
    return jsonify(import_candidates(zip_entries(archive.read()), fallback_name, current_owner()))


@routes.post("/api/dossiers/batch")
def batch():
    """
    Une action sur plusieurs dossiers : {"ids": [dossiers], "action": ..., "terms": "..."}
        "add_keywords"      ajoute les mots-clés « terms » à chaque dossier
        "remove_keywords"   retire les mots-clés « terms » de chaque dossier
        "copy_default"      ajoute la liste par défaut à chaque dossier
        "reread"            relit tous les documents
        "delete"            supprime les dossiers
    """
    body = request.get_json(force=True)
    dossier_ids = [int(dossier_id) for dossier_id in body.get("ids", [])]
    if not dossier_ids:
        abort(400, "Aucun dossier choisi")
    for dossier_id in dossier_ids:
        require_own_dossier(dossier_id)
    action, me = body.get("action"), current_owner()
    terms = parse_terms(body.get("terms", ""))
    changed, to_reread = 0, []
    with connect() as db:
        for dossier_id in dossier_ids:
            if action == "add_keywords":
                changed += len(add_terms(db, me, dossier_id, terms)[0])
            elif action == "remove_keywords":
                for term in terms:
                    changed += db.execute("DELETE FROM keywords WHERE dossier_id=? AND norm=?",
                                          (dossier_id, normalized_form(term))).rowcount
            elif action == "copy_default":
                changed += copy_list(db, me, me, DEFAULT_LIST, dossier_id)
            elif action == "reread":
                rows = db.execute("SELECT id FROM documents WHERE dossier_id=?", (dossier_id,)).fetchall()
                db.execute("UPDATE documents SET status='en_attente', progress_done=0 WHERE dossier_id=?", (dossier_id,))
                to_reread += [row["id"] for row in rows]
                changed += len(rows)
            elif action == "delete":
                _delete_dossier(db, dossier_id)
                changed += 1
            else:
                abort(400, f"Action inconnue : {action}")
    for document_id in to_reread:                # après l'enregistrement, pour que les ouvriers voient « en_attente »
        queue_document(document_id)
    return jsonify({"ok": True, "changed": changed})
