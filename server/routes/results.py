"""Les résultats : le tableau de tous les dossiers, le détail d'une case, et l'export pour Excel (fréquences)."""
import csv
import io
from datetime import datetime

from flask import Blueprint, abort, jsonify, request, send_file

from ..database import connect
from ..profiles import current_owner, require_own_dossier, team
from ..results import all_results

routes = Blueprint("results", __name__)


@routes.get("/api/results")
def results():
    data = all_results(current_owner())
    for dossier in data["dossiers"]:            # le tableau n'a besoin que du résumé de chaque case
        for cell in dossier["cells"].values():
            del cell["occurrences"]
    return jsonify(data)


@routes.get("/api/dossiers/<int:dossier_id>/keyword/<int:keyword_id>")
def cell_detail(dossier_id, keyword_id):
    """Une case (dossier, mot-clé) avec toutes ses occurrences."""
    require_own_dossier(dossier_id)
    dossiers = all_results(current_owner(), [dossier_id])["dossiers"]
    cell = dossiers[0]["cells"].get(keyword_id) if dossiers else None
    if cell is None:
        abort(404)
    return jsonify(cell)


@routes.get("/export.csv")
def export_csv():
    """
    Le tableau des fréquences, pour Excel (séparateur « ; » du français) :
        une ligne par document, une colonne par mot-clé,
        dans chaque case : combien de fois le mot a été lu dans ce document.
    Les lignes sont rangées par profil, puis par dossier, puis par document :
        Profil          Dossier        Document     État   robotique  Python ...
        Franck Plestan  Dupont Alice   cv.pdf       Lu     2          1
        Franck Plestan  Dupont Alice   lettre.pdf   Lu     0          0
        Franck Plestan  Martin Paul    cv.pdf       Lu     1
    Case vide : le mot n'est pas recherché dans ce dossier, ou le document n'a pas été lu.
    ?ids=1,2,3 : seulement ces dossiers du profil ouvert ; sinon les dossiers de toute l'équipe.
    """
    me = current_owner()
    chosen = [int(value) for value in request.args.get("ids", "").split(",") if value.strip().isdigit()] or None
    by_name = lambda dossier: dossier["name"].lower()           # noqa: E731 — les dossiers par ordre alphabétique
    if chosen:
        dossiers = sorted(all_results(me, chosen)["dossiers"], key=by_name)
    else:                                                         # les profils dans l'ordre de l'équipe
        with connect() as db:
            owners = [row["owner"] for row in db.execute("SELECT DISTINCT owner FROM dossiers")]
        members = team()
        owners.sort(key=lambda owner: (members.index(owner) if owner in members else len(members), owner.lower()))
        dossiers = [dossier for owner in owners for dossier in sorted(all_results(owner)["dossiers"], key=by_name)]

    # les colonnes : tous les mots-clés recherchés, une seule fois chacun (« Python » et « python » : une colonne)
    columns: dict[str, str] = {}
    for dossier in dossiers:
        for keyword in dossier["keywords"]:
            columns.setdefault(keyword["term"].lower(), keyword["term"])
    keys = sorted(columns)

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Profil", "Dossier", "Document", "État"] + [columns[key] for key in keys])
    for dossier in dossiers:                      # déjà dans l'ordre des profils
        counts = _count_per_document(dossier)
        searched = {keyword["term"].lower() for keyword in dossier["keywords"]}
        for document in sorted(dossier["documents"], key=lambda document: document["filename"].lower()):
            state = _state(document)
            read = state == "Lu"
            row = [dossier["owner"], dossier["name"], document["filename"], state]
            row += [counts.get((document["id"], key), 0) if read and key in searched else "" for key in keys]
            writer.writerow(row)
    data = ("\ufeff" + buffer.getvalue()).encode("utf-8")          # le « BOM » : Excel reconnaît l'UTF-8 (accents)
    return send_file(io.BytesIO(data), mimetype="text/csv", as_attachment=True,
                     download_name=f"keyscan_frequences_{datetime.now():%Y%m%d_%H%M}.csv")


def _count_per_document(dossier: dict) -> dict[tuple[int, str], int]:
    """{(document, mot-clé en minuscules): nombre de fois où le mot a été lu dans ce document}"""
    counts: dict[tuple[int, str], int] = {}
    for cell in dossier["cells"].values():
        for occurrence in cell["occurrences"]:
            key = (occurrence["doc_id"], cell["term"].lower())
            counts[key] = counts.get(key, 0) + 1
    return counts


def _state(document: dict) -> str:
    if document["duplicate_of"]:
        return f"Doublon de {document['duplicate_of']}"
    return {"ok": "Lu", "erreur": "Illisible", "en_attente": "En attente", "en_cours": "En cours de lecture"}.get(document["status"], "")
