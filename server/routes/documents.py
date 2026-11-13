"""Un document : le supprimer, le relire, télécharger l'original, voir une page avec les mots surlignés."""
import io
import json

from flask import Blueprint, abort, jsonify, request, send_file

from ..analysis import forget, queue_document
from ..database import connect, remove_file
from ..previews import page_png
from ..profiles import current_owner, require_own_document, thresholds

routes = Blueprint("documents", __name__)


@routes.delete("/api/documents/<int:document_id>")
def delete_document(document_id):
    require_own_document(document_id)
    with connect() as db:
        row = db.execute("SELECT path FROM documents WHERE id=?", (document_id,)).fetchone()
        remove_file(row["path"] if row else None)
        db.execute("DELETE FROM documents WHERE id=?", (document_id,))
    forget(document_id)
    return jsonify({"ok": True})


@routes.post("/api/documents/<int:document_id>/reanalyse")
def reread(document_id):
    require_own_document(document_id)
    with connect() as db:
        db.execute("UPDATE documents SET status='en_attente', progress_done=0 WHERE id=?", (document_id,))
    queue_document(document_id)
    return jsonify({"ok": True})


@routes.get("/api/documents/<int:document_id>/file")
def original_file(document_id):
    require_own_document(document_id)
    with connect() as db:
        row = db.execute("SELECT path, filename FROM documents WHERE id=?", (document_id,)).fetchone()
    return send_file(row["path"], download_name=row["filename"])


@routes.get("/api/documents/<int:document_id>/page/<int:page>.png")
def page_image(document_id, page):
    """
    Une page, avec des occurrences surlignées :
        ?kw=<mot-clé>          les occurrences d'un mot-clé
        ?all=1                 les occurrences de tous les mots-clés du dossier, avec leur nom
        &crop=x0,y0,x1,y1      zoom sur une zone (fractions de la page, de 0 à 1)
    """
    require_own_document(document_id)
    me = current_owner()
    with connect() as db:
        document = dict(db.execute("""SELECT d.id, d.path, d.status, d.pages, d.analysed_at, d.dossier_id, s.owner
                                      FROM documents d JOIN dossiers s ON s.id = d.dossier_id WHERE d.id=?""",
                                   (document_id,)).fetchone())
        if request.args.get("all"):
            terms = [row["term"] for row in db.execute(
                "SELECT term FROM keywords WHERE dossier_id=? AND owner=? ORDER BY lower(term)", (document["dossier_id"], me))]
        else:
            row = db.execute("SELECT term FROM keywords WHERE id=? AND owner=?", (request.args.get("kw", 0), me)).fetchone()
            terms = [row["term"]] if row else []
    document["pages"] = json.loads(document["pages"]) if document["pages"] else []
    png = page_png(document, page, terms, thresholds(document["owner"])["present_thr"], _crop())
    response = send_file(io.BytesIO(png), mimetype="image/png")
    response.headers["Cache-Control"] = "private, max-age=600"
    return response


def _crop() -> list[float] | None:
    if not request.args.get("crop"):
        return None
    try:
        crop = [min(1.0, max(0.0, float(value))) for value in request.args["crop"].split(",")][:4]
    except ValueError:
        crop = []
    if len(crop) != 4 or crop[2] <= crop[0] or crop[3] <= crop[1]:
        abort(400, "Zone invalide")
    return crop
