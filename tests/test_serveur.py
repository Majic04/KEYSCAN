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
from server.analysis import waiting_documents  # noqa: E402
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

groups = group_by_candidate([("Lot/Candidats/Dupont/cv.pdf", b"1"), ("Lot/Candidats/Martin/cv.pdf", b"2")], "Import")
check("plusieurs dossiers englobants traversés", sorted(groups) == ["Dupont", "Martin"], str(sorted(groups)))
groups = group_by_candidate([("Dupont/cv.pdf", b"1"), ("Dupont/diplomes/master.pdf", b"2")], "Import")
check("un candidat avec un sous-dossier reste un seul dossier", list(groups) == ["Dupont"] and len(groups["Dupont"]) == 2, str(groups))


def zip_of(entries: dict) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return archive.getvalue()


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

# un .zip déposé dans un dossier existant : ses documents y sont ajoutés
durand = response["ids"][0]
archive = io.BytesIO()
with zipfile.ZipFile(archive, "w") as z:
    z.writestr("pieces/releve.pdf", pdf_b)
    z.writestr("pieces/annexes/lettre.pdf", pdf_c)
    z.writestr("pieces/cv.pdf", pdf_a)                 # déjà dans le dossier : doublon
    z.writestr("pieces/notes.txt", b"x")               # format refusé
    z.writestr("__MACOSX/pieces/._releve.pdf", b"y")   # fichier caché du Mac : ignoré
answer = franck.post(f"/api/dossiers/{durand}/files", data={"files": [(io.BytesIO(archive.getvalue()), "pieces.zip"),
                                                                      (io.BytesIO(b"pas un zip"), "abime.zip")]},
                     content_type="multipart/form-data").get_json()
check(".zip dans un dossier : documents ajoutés", len(answer["added"]) == 2, str(answer))
check(".zip dans un dossier : doublon, format refusé et archive abîmée signalés",
      len(answer["duplicates"]) == 1 and sorted(answer["rejected"]) == ["abime.zip", "notes.txt"], str(answer))

# actions sur plusieurs dossiers
answer = franck.post("/api/dossiers/batch", json={"ids": ids, "action": "add_keywords", "terms": "Kalman, Python"}).get_json()
check("mots-clés ajoutés à 2 dossiers", answer["changed"] == 4, str(answer))
answer = franck.post("/api/dossiers/batch", json={"ids": ids, "action": "remove_keywords", "terms": "THESE"}).get_json()
check("retrait sans tenir compte des accents ni des majuscules", answer["changed"] == 2, str(answer))
check("liste par défaut inchangée", sorted(k["term"] for k in franck.get("/api/keywords").get_json()) == ["robotique", "thèse"])
check("autre prof : action refusée", mohamed.post("/api/dossiers/batch", json={"ids": ids, "action": "delete"}).status_code == 404)
check("action inconnue refusée", franck.post("/api/dossiers/batch", json={"ids": ids, "action": "rien"}).status_code == 400)

# réglage « Mot non trouvé » : absent (par défaut) ou prudent, propre à chaque profil
check("mot non trouvé : « absent » par défaut", franck.get("/api/settings").get_json()["absence"] == "absent")
franck.post("/api/settings", json={"absence": "prudent"})
check("mot non trouvé : « prudent » enregistré", franck.get("/api/settings").get_json()["absence"] == "prudent"
      and mohamed.get("/api/settings").get_json()["absence"] == "absent")
franck.post("/api/settings", json={"absence": "n'importe quoi"})
check("mot non trouvé : valeur inconnue ignorée", franck.get("/api/settings").get_json()["absence"] == "prudent")
franck.post("/api/settings", json={"absence": "absent"})

# un .zip qui contient plusieurs dossiers, ou un .zip par candidat : un dossier KeyScan par candidat, lecture lancée
before = waiting_documents.qsize()
lot = zip_of({"Candidats/Leroy Hugo/cv.pdf": tiny_pdf("Leroy cv"), "Candidats/Leroy Hugo/notes/releve.pdf": tiny_pdf("Leroy releve"),
              "Candidats/Petit Emma/lettre.pdf": tiny_pdf("Petit lettre"), "__MACOSX/Candidats/._x": b"y"})
response = franck.post("/api/import-zip", data={"archive": (io.BytesIO(lot), "candidats 2027.zip")},
                       content_type="multipart/form-data").get_json()
check(".zip à plusieurs dossiers : un dossier par candidat", sorted(response["dossiers"]) == ["Leroy Hugo", "Petit Emma"], str(response))
check(".zip à plusieurs dossiers : les 3 documents sont mis en lecture", waiting_documents.qsize() - before == 3)
zips = zip_of({"Roux Lea.zip": zip_of({"cv.pdf": tiny_pdf("Roux cv")}), "Blanc Tom.zip": zip_of({"Blanc Tom/cv.pdf": tiny_pdf("Blanc cv")})})
response = franck.post("/api/import-zip", data={"archive": (io.BytesIO(zips), "lot.zip")}, content_type="multipart/form-data").get_json()
check(".zip de .zip : un dossier par .zip", sorted(response["dossiers"]) == ["Blanc Tom", "Roux Lea"], str(response))
response = franck.post("/api/import-folder", data={
    "files": [(io.BytesIO(zip_of({"cv.pdf": tiny_pdf("Noir cv")})), "Noir Max.zip"), (io.BytesIO(zip_of({"cv.pdf": tiny_pdf("Vert cv")})), "Vert Ana.zip")],
    "paths": ["Noir Max.zip", "Vert Ana.zip"]}, content_type="multipart/form-data").get_json()
check("plusieurs .zip déposés : un dossier par .zip", sorted(response["dossiers"]) == ["Noir Max", "Vert Ana"], str(response))
check(".zip abîmé : refusé avec un message", franck.post("/api/import-zip", data={"archive": (io.BytesIO(b"rien"), "x.zip")},
                                                       content_type="multipart/form-data").status_code == 400)
imported = [d["id"] for d in franck.get("/api/results").get_json()["dossiers"] if d["name"] in ("Leroy Hugo", "Petit Emma", "Roux Lea", "Blanc Tom", "Noir Max", "Vert Ana")]
franck.post("/api/dossiers/batch", json={"ids": imported, "action": "delete"})

# export : une ligne par document, une colonne par mot-clé, la fréquence dans chaque case ; rangé par profil puis dossier
from server.analysis import _read_one  # noqa: E402
long_text = "Projet robotique en Python, robotique, robotique."
mohamed.post("/api/dossiers", json={"name": "Zola Ines", "terms": "robotique, Matlab"})
zola = next(d for d in mohamed.get("/api/results").get_json()["dossiers"] if d["name"] == "Zola Ines")["id"]
mohamed.post(f"/api/dossiers/{zola}/files", data={"files": [(io.BytesIO(tiny_pdf(long_text)), "cv.pdf")]}, content_type="multipart/form-data")
franck.post(f"/api/dossiers/{ids[0]}/files", data={"files": [(io.BytesIO(tiny_pdf("Kalman. " + long_text)), "projet.pdf")]},
            content_type="multipart/form-data")
for d in franck.get("/api/results").get_json()["dossiers"] + mohamed.get("/api/results").get_json()["dossiers"]:
    for document in d["documents"]:
        if document["filename"] in ("cv.pdf", "projet.pdf") and d["name"] in ("Dupont", "Zola Ines"):
            _read_one(document["id"])                    # lecture faite ici, sans attendre les ouvriers
lines = list(csv.reader(io.StringIO(franck.get("/export.csv").data.decode("utf-8-sig")), delimiter=";"))
head, rows = lines[0], lines[1:]
check("export : colonnes Profil, Dossier, Document, État puis les mots-clés", head[:4] == ["Profil", "Dossier", "Document", "État"]
      and sorted(head[4:], key=str.lower) == head[4:] and "robotique" in head and "Matlab" in head, str(head))
check("export : une ligne par document", len(rows) == sum(len(d["documents"]) for who in (franck, mohamed)
                                                       for d in who.get("/api/results").get_json()["dossiers"]), str(len(rows)))
check("export : rangé par profil puis par dossier", [r[0] for r in rows] == sorted((r[0] for r in rows), key=["Franck Plestan", "Mohamed Hamida"].index)
      and rows[-1][:3] == ["Mohamed Hamida", "Zola Ines", "cv.pdf"], str([r[:3] for r in rows]))
col = {name: i for i, name in enumerate(head)}
projet = next(r for r in rows if r[2] == "projet.pdf")
check("export : fréquence d'un mot dans un document", projet[col["robotique"]] == "3" and projet[col["Kalman"]] == "1", str(projet))
check("export : case vide si le mot n'est pas recherché dans ce dossier", projet[col["Matlab"]] == "", str(projet))
zola_row = rows[-1]
check("export : dossier d'un autre profil", zola_row[col["robotique"]] == "3" and zola_row[col["Matlab"]] == "0" and zola_row[col["Kalman"]] == "", str(zola_row))
waiting_row = next(r for r in rows if r[2] == "b.pdf")
check("export : document pas encore lu, cases vides", waiting_row[3] == "En attente" and set(waiting_row[4:]) == {""}, str(waiting_row))
lines = list(csv.reader(io.StringIO(franck.get(f"/export.csv?ids={ids[1]}").data.decode("utf-8-sig")), delimiter=";"))
check("export d'une sélection", {line[1] for line in lines[1:]} == {"Martin"}, str(lines[1:]))

answer = franck.post("/api/dossiers/batch", json={"ids": ids, "action": "delete"}).get_json()
names = [d["name"] for d in franck.get("/api/results").get_json()["dossiers"]]
check("suppression groupée", names == ["Durand"], str(names))

print("\nÉchecs : " + ", ".join(failures) if failures else "\nTous les tests du serveur sont passés.")
sys.exit(1 if failures else 0)
