# Tests de KeyScan : python tests.py
import io
import os
import sys
import tempfile

os.environ["KEYSCAN_DONNEES"] = tempfile.mkdtemp()      # base vide, juste pour les tests
os.environ["KEYSCAN_SANS_MANUSCRIT"] = "1"

import pymupdf

import app
import moteur

moteur.trouver_tesseract()
echecs = []


def test(nom, ok):
    print(("ok     " if ok else "ÉCHEC  ") + nom)
    if not ok:
        echecs.append(nom)


def mots(liste, source="texte", ecart=0.01):
    """Fabrique des mots lus, côte à côte sur une ligne."""
    toks, x = [], 0.05
    for i, m in enumerate(liste):
        largeur = 0.012 * len(m)
        toks += moteur.tokens_du_mot(m, 95, 1, source, i, [x, 0.1, x + largeur, 0.12])
        x += largeur + ecart
    return toks


def decision(liste, mot, source="texte", ecart=0.01, pages=None):
    occ = moteur.chercher(mots(liste, source, ecart), mot)
    return moteur.decider(mot, occ, 95, pages or [{"mode": "texte"}])[1]


# mots imbriqués
test("« pour » n'est pas dans « pourquoi »", decision(["pourquoi"], "pour") == "absent")
test("« pour- / quoi » coupé en fin de ligne", decision(["pour-", "quoi"], "pour") == "absent")
test("« pour » seul est trouvé", decision(["merci", "pour", "tout"], "pour") == "present")
test("élision : l'apprentissage", decision(["l'apprentissage"], "apprentissage") == "present")
test("mot composé : à vérifier", decision(["Master-Recherche"], "Master") == "a_verifier")
test("césure dans le mot-clé", decision(["apprentis-", "sage", "automatique"], "apprentissage automatique") == "present")
test("OCR : mots collés sur l'image", decision(["pour", "quoi"], "pour", "ocr", ecart=0.001) == "absent")

# un mot seulement proche ne devient jamais « présent », même répété
test("« these » x3 pour « thèse » : à vérifier", decision(["these"] * 3, "thèse") == "a_verifier")
test("« thèse » exact : présent", decision(["ma", "thèse"], "thèse") == "present")
test("OCR approché répété : pas présent", decision(["robotiqe"] * 5, "robotique", "ocr") != "present")

# quand on ne peut pas affirmer l'absence
test("mot de 2 lettres dans un scan", moteur.decider("IA", [], 95, [{"mode": "ocr"}])[1] == "absent_douteux")
test("écriture manuscrite", moteur.decider("stage", [], 95, [{"mode": "ocr", "manuscrit": 2}])[1] == "absent_douteux")
test("document illisible dans le dossier", moteur.decider("stage", [], 95, [{"mode": "texte"}], non_lus=1)[1] == "absent_douteux")
test("bien lu et pas trouvé : absent", moteur.decider("stage", [], 95, [{"mode": "texte"}])[1] == "absent")

# lecture d'un vrai PDF
pdf = pymupdf.open()
pdf.new_page().insert_text((72, 72), "Lettre de motivation pour le Master robotique")
chemin = os.path.join(tempfile.mkdtemp(), "lettre.pdf")
pdf.save(chemin)
lu = moteur.lire_document(chemin)
test("PDF lu", lu["qualite"] == 100 and moteur.decider("Master", moteur.chercher(lu["tokens"], "Master"), 100, lu["pages"])[1] == "present")

# le serveur
app.creer_tables()
c = app.app.test_client()
test("verrouillé sans code", c.get("/api/resultats").status_code == 401)
c.post("/api/connexion", json={"prof": "Franck Plestan", "code": "1234"})
c.post("/api/mots_cles", json={"dossier": 0, "mots": "Master, chimie"})
d = c.post("/api/dossiers", json={"nom": "Dupont"}).get_json()["id"]
contenu = open(chemin, "rb").read()
r = c.post(f"/api/dossiers/{d}/fichiers", data={"fichiers": [(io.BytesIO(contenu), "a.pdf"), (io.BytesIO(contenu), "b.pdf")]}).get_json()
test("doublon refusé", r == {"ok": 1, "refuse": 0, "doublon": 1})
app.lire(app.file_attente.get())    # on lit le document ici, sans attendre les fils d'exécution
cases = {c2["mot"]: c2["decision"] for c2 in c.get("/api/resultats").get_json()["dossiers"][0]["cases"].values()}
test("résultats du dossier", cases == {"Master": "present", "chimie": "absent"})

r = c.post("/api/import", data={"fichiers": [(io.BytesIO(contenu), "a.pdf"), (io.BytesIO(contenu), "c.pdf")],
                                "chemins": ["Candidats/Martin/a.pdf", "Candidats/Durand/c.pdf"]}).get_json()
test("import : un dossier par candidat", len(r["ids"]) == 2)
c.post("/api/lot", json={"ids": r["ids"], "action": "ajouter", "mots": "Python"})
noms = {x["nom"]: [m["mot"] for m in x["mots_cles"]] for x in c.get("/api/resultats").get_json()["dossiers"]}
test("mot ajouté aux dossiers cochés seulement", "Python" in noms["Martin"] and "Python" not in noms["Dupont"])
c.post("/api/lot", json={"ids": r["ids"], "action": "supprimer"})
test("suppression groupée", len(c.get("/api/resultats").get_json()["dossiers"]) == 1)

autre = app.app.test_client()
autre.post("/api/connexion", json={"prof": "Mohamed Hamida", "code": "5678"})
test("un prof ne voit pas les dossiers de l'autre", autre.get(f"/api/dossiers/{d}/mot/1").status_code == 404)

print("\n" + (f"{len(echecs)} échec(s)" if echecs else "Tous les tests sont passés."))
sys.exit(1 if echecs else 0)
