"""
Tests du serveur (sans navigateur) : profils, mots-clés par dossier, import de plusieurs candidats,
actions sur plusieurs dossiers, export. La lecture des documents n'est pas lancée ici (voir test_regles.py).

usage : python tests/test_serveur.py      (code de sortie 1 en cas d'échec)
"""
import csv
import io
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["KEYSCAN_DATA"] = tempfile.mkdtemp(prefix="keyscan-serveur-")   # une base vide, jetée après le test

import pymupdf  # noqa: E402

from server import create_app  # noqa: E402
from server.database import create_tables  # noqa: E402
from server.uploads import group_by_candidate  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("OK     " if cond else "ÉCHEC  ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def tiny_pdf(text: str) -> bytes:
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), text)
    return pdf.tobytes()


# --------------------------------------------------------------------------- rangement des fichiers par candidat
groups = group_by_candidate([("Candidats/Dupont/cv.pdf", b"1"), ("Candidats/Dupont/notes/releve.pdf", b"2"),
                             ("Candidats/Martin/lettre.pdf", b"3")], "Import")
check("dossier englobant ignoré, un dossier par candidat", sorted(groups) == ["Dupont", "Martin"], str(sorted(groups)))
check("sous-dossiers d'un candidat regroupés", [name for name, _ in groups["Dupont"]] == ["cv.pdf", "releve.pdf"])
groups = group_by_candidate([("Dupont/cv.pdf", b"1"), ("Martin/cv.pdf", b"2"), ("lisez-moi.pdf", b"3")], "Lot")
check("fichier à la racine : dossier au nom du lot", sorted(groups) == ["Dupont", "Lot", "Martin"], str(sorted(groups)))
groups = group_by_candidate([("Dupont Marie/cv.pdf", b"1"), ("Dupont Marie/.DS_Store", b"x"), ("__MACOSX/Dupont Marie/cv.pdf", b"y")], "Lot")
check("le dossier d'un seul candidat garde son nom ; fichiers cachés ignorés",
      list(groups) == ["Dupont Marie"] and len(groups["Dupont Marie"]) == 1, str(groups))

# --------------------------------------------------------------------------- l'API
create_tables()
app = create_app()
franck, mohamed = app.test_client(), app.test_client()
check("verrouillé sans code", franck.get("/api/results").status_code == 401)
franck.post("/api/pin/setup", json={"owner": "Franck Plestan", "pin": "1234"})
mohamed.post("/api/pin/setup", json={"owner": "Mohamed Hamida", "pin": "5678"})
check("profil ouvert", franck.get("/api/session").get_json()["owner"] == "Franck Plestan")
franck.post("/api/keywords", json={"terms": "thèse, robotique"})

pdf_a, pdf_b, pdf_c = tiny_pdf("Master robotique"), tiny_pdf("These de doctorat"), tiny_pdf("Lettre")
response = franck.post("/api/import-folder", data={
    "files": [(io.BytesIO(pdf_a), "a.pdf"), (io.BytesIO(pdf_b), "b.pdf"), (io.BytesIO(pdf_c), "c.pdf"), (io.BytesIO(b"x"), "d.txt")],
    "paths": ["Candidats/Dupont/a.pdf", "Candidats/Dupont/b.pdf", "Candidats/Martin/c.pdf", "Candidats/Martin/d.txt"],
}, content_type="multipart/form-data").get_json()
check("import d'un dossier : 2 candidats", response["dossiers"] == ["Dupont", "Martin"], str(response))
check("format refusé signalé", response["rejected"] == ["d.txt"])
ids = response["ids"]
results = franck.get("/api/results").get_json()
dupont = next(d for d in results["dossiers"] if d["name"] == "Dupont")
check("documents rangés et en attente de lecture", len(dupont["documents"]) == 2 and dupont["pending"] == 2)
check("liste par défaut recopiée", sorted(k["term"] for k in dupont["keywords"]) == ["robotique", "thèse"])

archive = io.BytesIO()
with zipfile.ZipFile(archive, "w") as z:
    z.writestr("Lot/Durand/cv.pdf", pdf_a)
    z.writestr("Lot/Durand/cv copie.pdf", pdf_a)
response = franck.post("/api/import-zip", data={"archive": (io.BytesIO(archive.getvalue()), "lot.zip")},
                       content_type="multipart/form-data").get_json()
check("import .zip", response["dossiers"] == ["Durand"] and len(response["duplicates"]) == 1, str(response))

# actions sur plusieurs dossiers
answer = franck.post("/api/dossiers/batch", json={"ids": ids, "action": "add_keywords", "terms": "Kalman, Python"}).get_json()
check("mots-clés ajoutés à 2 dossiers", answer["changed"] == 4, str(answer))
answer = franck.post("/api/dossiers/batch", json={"ids": ids, "action": "remove_keywords", "terms": "THESE"}).get_json()
check("retrait sans tenir compte des accents ni des majuscules", answer["changed"] == 2, str(answer))
check("liste par défaut inchangée", sorted(k["term"] for k in franck.get("/api/keywords").get_json()) == ["robotique", "thèse"])
check("autre prof : action refusée", mohamed.post("/api/dossiers/batch", json={"ids": ids, "action": "delete"}).status_code == 404)
check("action inconnue refusée", franck.post("/api/dossiers/batch", json={"ids": ids, "action": "rien"}).status_code == 400)

lines = list(csv.reader(io.StringIO(franck.get(f"/export.csv?ids={ids[0]}").data.decode("utf-8-sig")), delimiter=";"))
check("export d'une sélection", {line[0] for line in lines[1:]} == {"Dupont"} and len(lines) == 4, str(lines[1:]))

answer = franck.post("/api/dossiers/batch", json={"ids": ids, "action": "delete"}).get_json()
names = [d["name"] for d in franck.get("/api/results").get_json()["dossiers"]]
check("suppression groupée", names == ["Durand"], str(names))

print("\nÉchecs : " + ", ".join(failures) if failures else "\nTous les tests du serveur sont passés.")
sys.exit(1 if failures else 0)
