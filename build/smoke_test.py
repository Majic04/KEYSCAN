"""
Test de l'application CONSTRUITE (exécuté par GitHub après la construction, sur Mac et sur Windows).

Lance l'application en mode serveur (sans fenêtre), puis, comme le ferait un utilisateur :
crée un code PIN, ajoute des mots-clés, crée un dossier, dépose un PDF texte, un scan et une photo
couchée (lue par le modèle OCR OCRia-nano), attend l'analyse et vérifie les décisions.

usage : python build/smoke_test.py <chemin de l'exécutable KeyScan>
"""
import json
import os
import subprocess
import sys
import tempfile
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = sys.argv[1]
PORT = 47901
BASE = f"http://127.0.0.1:{PORT}/"
home = tempfile.mkdtemp(prefix="keyscan-test-")
env = dict(os.environ, KEYSCAN_HOME=home)
failures = []


def check(name, cond, detail=""):
    print(("OK     " if cond else "ÉCHEC  ") + name + (f"  ({detail})" if detail else ""), flush=True)
    if not cond:
        failures.append(name)


# 1. auto-test intégré : le modèle OCR embarqué lit un scan
st = subprocess.run([EXE, "--selftest"], env=env, capture_output=True, timeout=900)
out = (st.stdout or b"").decode("utf-8", "replace") + (st.stderr or b"").decode("utf-8", "replace")
log = os.path.join(home, "selftest.txt")
if os.path.exists(log):
    out += open(log, encoding="utf-8").read()
print(out)
check("auto-test intégré (modèle OCR OCRia-nano)", st.returncode == 0 and "AUTO-TEST OK" in out)

# 2. application en mode serveur
proc = subprocess.Popen([EXE, "--server-only", "--port", str(PORT)], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)   # l'application écrit dans keyscan.log
t0 = time.time()
s = requests.Session()
while time.time() - t0 < 180:
    try:
        if s.get(BASE + "api/session", timeout=2).ok:
            break
    except requests.RequestException:
        time.sleep(2)
check("démarrage du serveur", time.time() - t0 < 180, f"{time.time() - t0:.0f} s")
check("page d'accueil", s.get(BASE).status_code == 200 and "KeyScan" in s.get(BASE).text)
check("création du code PIN", s.post(BASE + "api/pin/setup", json={"owner": "Franck Plestan", "pin": "1234"}).ok)
s.post(BASE + "api/keywords", json={"terms": "Master\nrobotique\napprentissage automatique\nvision par ordinateur\nstage\nTOEIC\nchimie"})
did = s.post(BASE + "api/dossiers", json={"name": "Test installé"}).json()["id"]
files = [("files", (n, open(p, "rb"))) for n, p in [
    ("natif.pdf", os.path.join(ROOT, "exemples", "natif.pdf")),
    ("scan.pdf", os.path.join(ROOT, "exemples", "scan.pdf")),
    ("cv_tourne.jpg", os.path.join(ROOT, "exemples", "cv_tourne.jpg")),
]]
check("dépôt de 3 documents", len(s.post(BASE + f"api/dossiers/{did}/files", files=files).json()["added"]) == 3)

t0 = time.time()
while time.time() - t0 < 900:
    r = s.get(BASE + "api/results").json()
    if not r["dossiers"][0]["pending"]:
        break
    time.sleep(3)
d = r["dossiers"][0]
print(json.dumps({c["term"]: [c["decision"], c["score"]] for c in d["cells"].values()}, ensure_ascii=False))
print(json.dumps([{"doc": x["filename"], "statut": x["status"], "pages": x["pages"], "erreur": x["error"]} for x in d["documents"]], ensure_ascii=False))
check("analyse terminée", not d["pending"], f"{time.time() - t0:.0f} s")
check("aucun document en erreur", all(x["status"] == "ok" for x in d["documents"]))
dec = {c["term"]: c["decision"] for c in d["cells"].values()}
check("PDF texte : « Master » présent", dec.get("Master") == "present")
check("scan (OCR) : « TOEIC » présent", dec.get("TOEIC") == "present")
check("« chimie » absent", dec.get("chimie") in ("absent", "absent_douteux"))
photo = next(x for x in d["documents"] if x["filename"] == "cv_tourne.jpg")
check("photo couchée : remise droite (90°)", photo["pages"][0].get("rot") == 90, str(photo["pages"]))
kids = {c["term"]: kid for kid, c in d["cells"].items()}
cell = s.get(BASE + f"api/dossiers/{did}/keyword/{kids['stage']}").json()
check("photo couchée : « stage » lu sur l'image", any(o["filename"] == "cv_tourne.jpg" for o in cell["occurrences"]))
dup = s.post(BASE + f"api/dossiers/{did}/files", files=[("files", ("copie.pdf", open(os.path.join(ROOT, "exemples", "natif.pdf"), "rb")))]).json()
check("fichier en double refusé", not dup["added"] and len(dup.get("duplicates", [])) == 1)
check("mots-clés propres au dossier", len(d["keywords"]) == 7, f"{len(d['keywords'])}")
# export : une ligne par document, une colonne par mot-clé, le nombre d'occurrences dans chaque case
export = s.get(BASE + "export.csv")
rows = [line.split(";") for line in export.content.decode("utf-8-sig").splitlines()]
natif = next((row for row in rows if len(row) > 2 and row[2] == "natif.pdf"), [])
master = rows[0].index("Master") if export.ok and "Master" in rows[0] else None
check("export CSV (fréquences par document)", export.ok and rows[0][:4] == ["Profil", "Dossier", "Document", "État"]
      and len(rows) == 1 + len(d["documents"]) and master is not None and natif[master].isdigit() and int(natif[master]) >= 1,
      str(rows[:2]))

proc.terminate()
try:
    proc.wait(timeout=20)
except subprocess.TimeoutExpired:
    proc.kill()
if failures:
    logf = os.path.join(home, "keyscan.log")
    if os.path.exists(logf):
        print("\n----- journal de l'application -----\n" + open(logf, encoding="utf-8", errors="replace").read()[-15000:])
    print("\nÉCHECS :", failures)
    sys.exit(1)
print("\nTous les tests de l'application construite sont passés.")
