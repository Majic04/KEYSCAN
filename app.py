"""
KeyScan : serveur web local. Lancer avec  python app.py  puis ouvrir http://127.0.0.1:5000

Les données (base SQLite + fichiers déposés) sont dans le dossier « donnees ».
Les documents sont lus en arrière-plan par plusieurs fils d'exécution ; les mots lus sont gardés
dans la base, donc ajouter un mot-clé ne relance pas la lecture.
"""
import csv
import hashlib
import io
import json
import os
import queue
import re
import secrets
import sqlite3
import threading
import time
import zipfile
from datetime import datetime

from flask import Flask, abort, jsonify, request, send_file, session
from PIL import Image, ImageDraw, ImageOps
from werkzeug.utils import secure_filename

import moteur

PROFS = ["Franck Plestan", "Mohamed Hamida"]
ICI = os.path.dirname(os.path.abspath(__file__))
DONNEES = os.environ.get("KEYSCAN_DONNEES") or os.path.join(ICI, "donnees")
FICHIERS = os.path.join(DONNEES, "fichiers")
BASE = os.path.join(DONNEES, "keyscan.db")
os.makedirs(FICHIERS, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024


def cle_secrete():
    chemin = os.path.join(DONNEES, "secret.key")
    if not os.path.exists(chemin):
        with open(chemin, "wb") as f:
            f.write(secrets.token_bytes(32))
    with open(chemin, "rb") as f:
        return f.read()


app.secret_key = cle_secrete()


# ---------------------------------------------------------------------------------------------
# Base de données
# ---------------------------------------------------------------------------------------------

def db():
    con = sqlite3.connect(BASE, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def creer_tables():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS dossiers (id INTEGER PRIMARY KEY, nom TEXT, prof TEXT, cree_le TEXT);
        CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, dossier_id INTEGER, nom TEXT, chemin TEXT,
            empreinte TEXT, statut TEXT DEFAULT 'attente', erreur TEXT, pages TEXT, qualite REAL, tokens TEXT,
            fait INTEGER DEFAULT 0, total INTEGER DEFAULT 0);
        -- dossier_id = 0 : la liste par défaut du prof
        CREATE TABLE IF NOT EXISTS mots_cles (id INTEGER PRIMARY KEY, prof TEXT, dossier_id INTEGER, mot TEXT, norm TEXT,
            UNIQUE(prof, dossier_id, norm));
        CREATE TABLE IF NOT EXISTS codes (prof TEXT PRIMARY KEY, sel TEXT, hash TEXT);
        """)


def maintenant():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------------------------
# Lecture des documents en arrière-plan
# ---------------------------------------------------------------------------------------------

file_attente = queue.Queue()
cache_tokens = {}       # numéro de document -> mots lus
cache_occ = {}          # (document, mot-clé) -> occurrences
verrou = threading.Lock()


def oublier(doc_id):
    with verrou:
        cache_tokens.pop(doc_id, None)
        for cle in [c for c in cache_occ if c[0] == doc_id]:
            del cache_occ[cle]


def lire(doc_id):
    with db() as con:
        doc = con.execute("SELECT chemin FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            return
        con.execute("UPDATE documents SET statut='lecture', fait=0 WHERE id=?", (doc_id,))

    def avancement(fait, total):
        with db() as con:
            con.execute("UPDATE documents SET fait=?, total=? WHERE id=?", (fait, total, doc_id))

    try:
        r = moteur.lire_document(doc["chemin"], avancement)
        with db() as con:
            con.execute("UPDATE documents SET statut='ok', erreur=NULL, pages=?, qualite=?, tokens=? WHERE id=?",
                        (json.dumps(r["pages"]), r["qualite"], json.dumps(r["tokens"]), doc_id))
    except Exception as e:
        print("document illisible :", doc["chemin"], e)
        with db() as con:
            con.execute("UPDATE documents SET statut='erreur', erreur=? WHERE id=?", (str(e)[:300], doc_id))
    oublier(doc_id)


def ouvrier():
    while True:
        doc_id = file_attente.get()
        try:
            lire(doc_id)
        except Exception as e:
            print("erreur :", e)


def occurrences(doc_id, mot):
    cle = (doc_id, moteur.normaliser(mot))
    with verrou:
        if cle in cache_occ:
            return cache_occ[cle]
        tokens = cache_tokens.get(doc_id)
    if tokens is None:
        with db() as con:
            ligne = con.execute("SELECT tokens FROM documents WHERE id=?", (doc_id,)).fetchone()
        tokens = json.loads(ligne["tokens"]) if ligne and ligne["tokens"] else []
    occ = moteur.chercher(tokens, mot)
    with verrou:
        cache_tokens[doc_id] = tokens
        cache_occ[cle] = occ
    return occ


# ---------------------------------------------------------------------------------------------
# Profils et codes PIN
# ---------------------------------------------------------------------------------------------

def hacher(code, sel):
    return hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(sel), 100_000).hex()


def code_de(prof):
    with db() as con:
        return con.execute("SELECT sel, hash FROM codes WHERE prof=?", (prof,)).fetchone()


def enregistrer_code(prof, code):
    if not (code.isdigit() and 4 <= len(code) <= 8):
        abort(400, "Le code doit faire 4 à 8 chiffres")
    sel = secrets.token_hex(16)
    with db() as con:
        con.execute("INSERT OR REPLACE INTO codes VALUES (?,?,?)", (prof, sel, hacher(code, sel)))


def code_correct(prof, code):
    c = code_de(prof)
    if c and secrets.compare_digest(c["hash"], hacher(str(code), c["sel"])):
        return True
    time.sleep(1)   # ralentit qui essaierait tous les codes
    return False


@app.before_request
def verifier_profil():
    libres = ("/api/session", "/api/connexion", "/api/deconnexion")
    if (request.path.startswith("/api/") or request.path.startswith("/export")) and request.path not in libres:
        if session.get("prof") not in PROFS:
            return jsonify({"verrouille": True}), 401


def prof():
    return session["prof"]


def mon_dossier(dossier_id):
    with db() as con:
        d = con.execute("SELECT * FROM dossiers WHERE id=?", (dossier_id,)).fetchone()
    if not d or d["prof"] != prof():
        abort(404, "Dossier introuvable")
    return d


def mon_document(doc_id):
    with db() as con:
        doc = con.execute("SELECT d.*, s.prof FROM documents d JOIN dossiers s ON s.id=d.dossier_id WHERE d.id=?",
                          (doc_id,)).fetchone()
    if not doc or doc["prof"] != prof():
        abort(404, "Document introuvable")
    return doc


@app.get("/")
def accueil():
    return send_file(os.path.join(ICI, "index.html"))


@app.get("/api/session")
def get_session():
    return jsonify({"prof": session.get("prof"), "profs": [{"nom": p, "a_un_code": bool(code_de(p))} for p in PROFS]})


@app.post("/api/connexion")
def connexion():
    data = request.get_json()
    p, code = data.get("prof"), str(data.get("code", ""))
    if p not in PROFS:
        abort(400, "Profil inconnu")
    if not code_de(p):
        enregistrer_code(p, code)          # première connexion : on crée le code
    elif not code_correct(p, code):
        abort(403, "Code incorrect")
    session["prof"] = p
    return jsonify({"prof": p})


@app.post("/api/code")
def changer_code():
    data = request.get_json()
    if not code_correct(prof(), str(data.get("ancien", ""))):
        abort(403, "Code actuel incorrect")
    enregistrer_code(prof(), str(data.get("nouveau", "")))
    return jsonify({"ok": True})


@app.post("/api/deconnexion")
def deconnexion():
    session.clear()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------------------------
# Mots-clés
# ---------------------------------------------------------------------------------------------

def decouper(texte):
    """Une liste collée : un mot-clé par ligne ou séparés par des virgules / points-virgules."""
    return [m.strip() for m in re.split(r"[\n;,]", texte or "") if m.strip()]


def ajouter_mots(con, dossier_id, mots):
    ajoutes = 0
    for m in mots:
        norm = " ".join(moteur.normaliser(m).split())
        if any(c.isalnum() for c in norm):
            ajoutes += con.execute("INSERT OR IGNORE INTO mots_cles (prof, dossier_id, mot, norm) VALUES (?,?,?,?)",
                                   (prof(), dossier_id, m, norm)).rowcount
    return ajoutes


@app.post("/api/mots_cles")
def nouveaux_mots():
    data = request.get_json()
    dossier_id = int(data.get("dossier") or 0)
    if dossier_id:
        mon_dossier(dossier_id)
    with db() as con:
        n = ajouter_mots(con, dossier_id, decouper(data.get("mots")))
    return jsonify({"ajoutes": n})


@app.delete("/api/mots_cles/<int:mot_id>")
def supprimer_mot(mot_id):
    with db() as con:
        con.execute("DELETE FROM mots_cles WHERE id=? AND prof=?", (mot_id, prof()))
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------------------------
# Dossiers et documents
# ---------------------------------------------------------------------------------------------

def nouveau_dossier(con, nom, liste_defaut=True):
    dossier_id = con.execute("INSERT INTO dossiers (nom, prof, cree_le) VALUES (?,?,?)", (nom, prof(), maintenant())).lastrowid
    if liste_defaut:   # le nouveau dossier reçoit une copie de la liste par défaut
        mots = [m["mot"] for m in con.execute("SELECT mot FROM mots_cles WHERE prof=? AND dossier_id=0", (prof(),))]
        ajouter_mots(con, dossier_id, mots)
    return dossier_id


def deposer(dossier_id, nom, contenu):
    """Enregistre un fichier et le met en lecture. Retourne "ok", "refuse" (format) ou "doublon"."""
    nom = os.path.basename(nom)
    if os.path.splitext(nom)[1].lower() not in moteur.EXTENSIONS or not contenu:
        return "refuse"
    empreinte = hashlib.sha256(contenu).hexdigest()
    with db() as con:
        if con.execute("SELECT 1 FROM documents WHERE dossier_id=? AND empreinte=?", (dossier_id, empreinte)).fetchone():
            return "doublon"
        doc_id = con.execute("INSERT INTO documents (dossier_id, nom, empreinte) VALUES (?,?,?)",
                             (dossier_id, nom, empreinte)).lastrowid
        chemin = os.path.join(FICHIERS, f"{doc_id}_{secure_filename(nom) or 'fichier'}")
        with open(chemin, "wb") as f:
            f.write(contenu)
        con.execute("UPDATE documents SET chemin=?, total=? WHERE id=?", (chemin, moteur.nb_pages(chemin), doc_id))
    file_attente.put(doc_id)
    return "ok"


def supprimer_dossier(con, dossier_id):
    for doc in con.execute("SELECT id, chemin FROM documents WHERE dossier_id=?", (dossier_id,)).fetchall():
        if doc["chemin"] and os.path.exists(doc["chemin"]):
            os.remove(doc["chemin"])
        oublier(doc["id"])
    con.execute("DELETE FROM documents WHERE dossier_id=?", (dossier_id,))
    con.execute("DELETE FROM mots_cles WHERE dossier_id=?", (dossier_id,))
    con.execute("DELETE FROM dossiers WHERE id=?", (dossier_id,))


@app.post("/api/dossiers")
def creer_dossier():
    data = request.get_json()
    nom = (data.get("nom") or "").strip()
    if not nom:
        abort(400, "Il faut un nom")
    with db() as con:
        dossier_id = nouveau_dossier(con, nom, data.get("liste_defaut", True))
        ajouter_mots(con, dossier_id, decouper(data.get("mots")))
    return jsonify({"id": dossier_id})


@app.patch("/api/dossiers/<int:dossier_id>")
def renommer(dossier_id):
    mon_dossier(dossier_id)
    nom = (request.get_json().get("nom") or "").strip()
    if nom:
        with db() as con:
            con.execute("UPDATE dossiers SET nom=? WHERE id=?", (nom, dossier_id))
    return jsonify({"ok": True})


@app.delete("/api/dossiers/<int:dossier_id>")
def effacer_dossier(dossier_id):
    mon_dossier(dossier_id)
    with db() as con:
        supprimer_dossier(con, dossier_id)
    return jsonify({"ok": True})


@app.post("/api/dossiers/<int:dossier_id>/fichiers")
def ajouter_fichiers(dossier_id):
    mon_dossier(dossier_id)
    res = {"ok": 0, "refuse": 0, "doublon": 0}
    for f in request.files.getlist("fichiers"):
        res[deposer(dossier_id, f.filename, f.read())] += 1
    return jsonify(res)


@app.post("/api/import")
def importer():
    """
    Plusieurs candidats d'un coup : un dossier avec un sous-dossier par candidat (ou un .zip).
    Chaque sous-dossier devient un dossier KeyScan.
    """
    if "zip" in request.files:
        with zipfile.ZipFile(io.BytesIO(request.files["zip"].read())) as z:
            fichiers = [(i.filename, z.read(i)) for i in z.infolist() if not i.is_dir()]
    else:
        chemins = request.form.getlist("chemins")
        fichiers = [(chemins[i], f.read()) for i, f in enumerate(request.files.getlist("fichiers"))]
    # on range par candidat : « Candidats/Dupont/cv.pdf » -> Dupont
    elements = []
    for chemin, contenu in fichiers:
        parties = [p for p in chemin.replace("\\", "/").split("/") if p]
        if parties and not any(p.startswith(".") or p == "__MACOSX" for p in parties):
            elements.append((parties, contenu))
    racines = {p[0] for p, _ in elements}
    nom_par_defaut = "Import"
    if len(racines) == 1 and all(len(p) > 1 for p, _ in elements):
        nom_par_defaut = racines.pop()
        elements = [(p[1:], c) for p, c in elements]     # tout est dans un seul dossier : on regarde dedans
    candidats = {}
    for parties, contenu in elements:
        candidats.setdefault(parties[0] if len(parties) > 1 else nom_par_defaut, []).append((parties[-1], contenu))

    ids, ignores = [], 0
    for nom, docs in candidats.items():
        if not any(os.path.splitext(n)[1].lower() in moteur.EXTENSIONS for n, _ in docs):
            ignores += len(docs)
            continue
        with db() as con:
            dossier_id = nouveau_dossier(con, nom)
        ids.append(dossier_id)
        for n, contenu in docs:
            if deposer(dossier_id, n, contenu) != "ok":
                ignores += 1
    return jsonify({"ids": ids, "ignores": ignores})


@app.post("/api/lot")
def action_groupee():
    """Une action sur plusieurs dossiers cochés : ajouter / retirer des mots-clés, relire, supprimer."""
    data = request.get_json()
    ids = [int(i) for i in data.get("ids", [])]
    for i in ids:
        mon_dossier(i)
    action, mots = data.get("action"), decouper(data.get("mots"))
    if action not in ("ajouter", "retirer", "relire", "supprimer"):
        abort(400, "Action inconnue")
    a_relire = []
    with db() as con:
        for i in ids:
            if action == "ajouter":
                ajouter_mots(con, i, mots)
            elif action == "retirer":
                for m in mots:
                    con.execute("DELETE FROM mots_cles WHERE dossier_id=? AND norm=?", (i, " ".join(moteur.normaliser(m).split())))
            elif action == "relire":
                a_relire += [d["id"] for d in con.execute("SELECT id FROM documents WHERE dossier_id=?", (i,))]
                con.execute("UPDATE documents SET statut='attente', fait=0 WHERE dossier_id=?", (i,))
            else:
                supprimer_dossier(con, i)
    for doc_id in a_relire:
        file_attente.put(doc_id)
    return jsonify({"ok": True})


@app.delete("/api/documents/<int:doc_id>")
def supprimer_document(doc_id):
    doc = mon_document(doc_id)
    if doc["chemin"] and os.path.exists(doc["chemin"]):
        os.remove(doc["chemin"])
    with db() as con:
        con.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    oublier(doc_id)
    return jsonify({"ok": True})


@app.post("/api/documents/<int:doc_id>/relire")
def relire(doc_id):
    mon_document(doc_id)
    with db() as con:
        con.execute("UPDATE documents SET statut='attente', fait=0 WHERE id=?", (doc_id,))
    file_attente.put(doc_id)
    return jsonify({"ok": True})


@app.get("/api/documents/<int:doc_id>/fichier")
def fichier_original(doc_id):
    doc = mon_document(doc_id)
    return send_file(doc["chemin"], download_name=doc["nom"])


@app.get("/api/documents/<int:doc_id>/page/<int:page>.png")
def image_page(doc_id, page):
    """La page avec les mots trouvés encadrés (vert = sûr, jaune = à vérifier). ?mot=<id> ou ?tous=1, &zone=x0,y0,x1,y1"""
    doc = mon_document(doc_id)
    with db() as con:
        if request.args.get("tous"):
            mots = [m["mot"] for m in con.execute("SELECT mot FROM mots_cles WHERE dossier_id=?", (doc["dossier_id"],))]
        else:
            m = con.execute("SELECT mot FROM mots_cles WHERE id=? AND prof=?", (request.args.get("mot", 0), prof())).fetchone()
            mots = [m["mot"]] if m else []
    zone = [float(v) for v in request.args["zone"].split(",")] if request.args.get("zone") else None
    pages = json.loads(doc["pages"]) if doc["pages"] else []
    infos = pages[page - 1] if 0 < page <= len(pages) else {}

    if os.path.splitext(doc["chemin"])[1].lower() in moteur.EXT_IMAGES:
        with Image.open(doc["chemin"]) as im:
            im.seek(page - 1)
            img = ImageOps.exif_transpose(im.copy()).convert("RGB")
    else:
        with moteur.fitz.open(doc["chemin"]) as pdf:
            pix = pdf[page - 1].get_pixmap(dpi=200 if zone else 110)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    # même rotation que pendant la lecture, pour que les cadres tombent au bon endroit
    if infos.get("rot"):
        img = img.rotate(-infos["rot"], expand=True)
    if infos.get("inclinaison"):
        img = img.rotate(infos["inclinaison"], expand=True, fillcolor="white", resample=Image.BICUBIC)
    if not zone:
        img.thumbnail((1600, 1600))

    dessin = ImageDraw.Draw(img, "RGBA")
    W, H = img.size
    for mot in mots:
        for o in occurrences(doc_id, mot):
            if o["page"] != page:
                continue
            x0, y0, x1, y1 = o["box"]
            sur = o["certain"] and o["score"] * 100 >= moteur.SEUIL_PRESENT
            couleur = (60, 190, 120) if sur else (240, 190, 0)
            dessin.rectangle([x0 * W - 4, y0 * H - 3, x1 * W + 4, y1 * H + 3], fill=couleur + (80,), outline=couleur, width=3)
            if len(mots) > 1:
                dessin.text((x0 * W, y0 * H - 16), mot, fill=(30, 30, 30))
    if zone:   # zoom sur le mot, avec un peu de contexte autour
        x0, y0, x1, y1 = zone
        h = max(y1 - y0, 0.01)
        img = img.crop((int(max(0, x0 - 0.25) * W), int(max(0, y0 - 2.2 * h) * H),
                        int(min(1, x1 + 0.25) * W), int(min(1, y1 + 2.2 * h) * H)))
    tampon = io.BytesIO()
    img.save(tampon, "PNG")
    tampon.seek(0)
    return send_file(tampon, mimetype="image/png")


# ---------------------------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------------------------

def resultats(ids=None):
    """Tous les dossiers du prof, avec pour chaque mot-clé : score, décision et occurrences."""
    with db() as con:
        dossiers = [dict(d) for d in con.execute("SELECT * FROM dossiers WHERE prof=? ORDER BY id DESC", (prof(),))]
        liste_defaut = [dict(m) for m in con.execute("SELECT id, mot FROM mots_cles WHERE prof=? AND dossier_id=0 ORDER BY mot", (prof(),))]
        if ids is not None:
            dossiers = [d for d in dossiers if d["id"] in ids]
        for d in dossiers:
            d["documents"] = [dict(x) for x in con.execute(
                "SELECT id, nom, statut, erreur, pages, qualite, fait, total FROM documents WHERE dossier_id=?", (d["id"],))]
            d["mots_cles"] = [dict(m) for m in con.execute("SELECT id, mot FROM mots_cles WHERE dossier_id=? ORDER BY mot", (d["id"],))]

    for d in dossiers:
        lus = [x for x in d["documents"] if x["statut"] == "ok"]
        d["non_lus"] = [x["nom"] for x in d["documents"] if x["statut"] == "erreur"]
        d["en_cours"] = sum(1 for x in d["documents"] if x["statut"] in ("attente", "lecture"))
        qualite = min((x["qualite"] for x in lus), default=0)
        pages = [p for x in lus for p in json.loads(x["pages"])]
        for x in d["documents"]:
            x["pages"] = json.loads(x["pages"]) if x["pages"] else []
            x["trouves"] = []
        d["cases"] = {}
        for m in d["mots_cles"]:
            occ = [dict(o, doc=x["id"], fichier=x["nom"]) for x in lus for o in occurrences(x["id"], m["mot"])]
            score, decision = moteur.decider(m["mot"], occ, qualite, pages, len(d["non_lus"]))
            d["cases"][m["id"]] = {"mot": m["mot"], "score": score, "decision": decision, "occurrences": occ}
            # pour chaque document : les mots trouvés dedans, leurs pages, et s'il faut vérifier
            for x in d["documents"]:
                ici = [o for o in occ if o["doc"] == x["id"]]
                if ici:
                    x["trouves"].append({"mot_id": m["id"], "mot": m["mot"], "pages": sorted({o["page"] for o in ici}),
                                         "a_verifier": any(not (o["certain"] and o["score"] * 100 >= moteur.SEUIL_PRESENT) for o in ici)})
    return {"dossiers": dossiers, "liste_defaut": liste_defaut, "prof": prof()}


@app.get("/api/resultats")
def api_resultats():
    data = resultats()
    for d in data["dossiers"]:
        for case in d["cases"].values():
            occ = case.pop("occurrences")
            case["nb"] = len(occ)
            case["ou"] = sorted({(o["fichier"], o["page"]) for o in occ})
    return jsonify(data)


@app.get("/api/dossiers/<int:dossier_id>/mot/<int:mot_id>")
def detail_mot(dossier_id, mot_id):
    mon_dossier(dossier_id)
    case = resultats([dossier_id])["dossiers"][0]["cases"].get(mot_id)
    if not case:
        abort(404)
    return jsonify(case)


@app.get("/export.csv")
def export_csv():
    ids = [int(i) for i in request.args.get("ids", "").split(",") if i.isdigit()] or None
    tampon = io.StringIO()
    w = csv.writer(tampon, delimiter=";")
    w.writerow(["Dossier", "Mot-clé", "Décision", "Score (%)", "Trouvé dans", "Documents non lus"])
    for d in resultats(ids)["dossiers"]:
        for case in d["cases"].values():
            ou = sorted({f"{o['fichier']} p.{o['page']}" for o in case["occurrences"]})
            w.writerow([d["nom"], case["mot"], moteur.NOMS[case["decision"]], str(case["score"]).replace(".", ","),
                        " | ".join(ou), " | ".join(d["non_lus"])])
    contenu = ("﻿" + tampon.getvalue()).encode("utf-8")   # ﻿ : pour qu'Excel lise bien les accents
    return send_file(io.BytesIO(contenu), mimetype="text/csv", as_attachment=True,
                     download_name=f"keyscan_{datetime.now():%Y%m%d_%H%M}.csv")


# ---------------------------------------------------------------------------------------------

def demarrer():
    creer_tables()
    if not moteur.trouver_tesseract():
        print("Attention : Tesseract est introuvable, les scans et les images ne pourront pas être lus.")
    with db() as con:   # reprendre les lectures interrompues
        for doc in con.execute("SELECT id FROM documents WHERE statut IN ('attente', 'lecture')"):
            file_attente.put(doc["id"])
    for _ in range(max(1, min(4, (os.cpu_count() or 2) - 1))):
        threading.Thread(target=ouvrier, daemon=True).start()


if __name__ == "__main__":
    import argparse
    import webbrowser
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--oubli-code", metavar="PROF", help="efface le code PIN d'un prof")
    a = ap.parse_args()
    creer_tables()
    if a.oubli_code:
        with db() as con:
            con.execute("DELETE FROM codes WHERE prof=?", (a.oubli_code,))
        print("Code effacé : un nouveau code sera demandé à la prochaine connexion.")
    else:
        demarrer()
        print(f"KeyScan : http://127.0.0.1:{a.port}")
        threading.Timer(1, lambda: webbrowser.open(f"http://127.0.0.1:{a.port}")).start()
        app.run(port=a.port, threaded=True)
