"""Les résultats : le tableau de tous les dossiers, le détail d'une case, et l'export pour Excel."""
import csv
import io
from datetime import datetime

from flask import Blueprint, abort, jsonify, request, send_file
from werkzeug.utils import secure_filename

from engine.decision import LABELS

from ..profiles import current_owner, require_own_dossier
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


def _french_number(value) -> str:
    return str(value).replace(".", ",")


@routes.get("/export.csv")
def export_csv():
    """
    Une ligne par (dossier, mot-clé), avec le séparateur « ; » d'Excel en français.
    ?ids=1,2,3 : seulement ces dossiers (sinon tous les dossiers du prof).
    """
    me = current_owner()
    chosen = [int(value) for value in request.args.get("ids", "").split(",") if value.strip().isdigit()] or None
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Dossier", "Responsable", "Mot-clé", "Décision", "Score de présence (%)", "Fiabilité de la décision (%)",
                     "Nb occurrences", "Documents (pages)", "Qualité de lecture du dossier (%)", "Documents en attente",
                     "Documents non lus"])
    for dossier in all_results(me, chosen)["dossiers"]:
        unread = f"{len(dossier['unread'])}" + (f" ({' | '.join(dossier['unread'])})" if dossier["unread"] else "")
        for cell in sorted(dossier["cells"].values(), key=lambda cell: cell["term"].lower()):
            pages_per_file: dict[str, set] = {}
            for occurrence in cell["occurrences"]:
                pages_per_file.setdefault(occurrence["filename"], set()).add(occurrence["page"])
            where = " | ".join(f"{file} (p. {', '.join(map(str, sorted(pages)))})" for file, pages in pages_per_file.items())
            writer.writerow([dossier["name"], dossier["owner"], cell["term"], LABELS[cell["decision"]],
                             _french_number(cell["score"]), _french_number(cell["reliability"]), cell["count"], where,
                             _french_number(dossier["quality"]), dossier["pending"], unread])
    data = ("﻿" + buffer.getvalue()).encode("utf-8")          # le « BOM » : Excel reconnaît l'UTF-8 (accents)
    return send_file(io.BytesIO(data), mimetype="text/csv", as_attachment=True,
                     download_name=f"keyscan_{secure_filename(me)}_{datetime.now():%Y%m%d_%H%M}.csv")
