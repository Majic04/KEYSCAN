"""
Test de l'application CONSTRUITE (exécuté par GitHub après la construction, sur Mac et sur Windows).

Lance l'application en mode serveur (sans fenêtre), puis, comme le ferait un utilisateur :
crée un code PIN, ajoute des mots-clés, crée un dossier, dépose un PDF texte, un scan et une lettre
manuscrite, attend l'analyse et vérifie les décisions.

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


# 1. auto-test intégré : Tesseract (fra/eng) et module manuscrit embarqués
st = subprocess.run([EXE, "--selftest"], env=env, capture_output=True, text=True, timeout=900)
out = st.stdout + st.stderr
log = os.path.join(home, "selftest.txt")
if os.path.exists(log):
    out += open(log, encoding="utf-8").read()
print(out)
check("auto-test intégré (Tesseract + écriture manuscrite)", st.returncode == 0 and "AUTO-TEST OK" in out)

# 2. application en mode serveur
proc = subprocess.Popen([EXE, "--server-only", "--port", str(PORT)], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
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
s.post(BASE + "api/keywords", json={"terms": "Master\nrobotique\napprentissage automatique\nvision par ordinateur\nTOEIC\nchimie"})
did = s.post(BASE + "api/dossiers", json={"name": "Test installé"}).json()["id"]
files = [("files", (n, open(p, "rb"))) for n, p in [
    ("natif.pdf", os.path.join(ROOT, "exemples", "natif.pdf")),
    ("scan.pdf", os.path.join(ROOT, "exemples", "scan.pdf")),
    ("lettre.jpg", os.path.join(ROOT, "banc_essai", "manuscrit", "o_lettre.jpg")),
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
hw_lines = sum(p.get("manuscrit", 0) for x in d["documents"] for p in x["pages"])
check("lettre : lignes manuscrites lues par TrOCR", hw_lines > 0, f"{hw_lines} ligne(s)")
# mots-clés lus dans la lettre manuscrite elle-même (et pas dans les autres documents du dossier)
kids = {c["term"]: kid for kid, c in d["cells"].items()}
hand = {}
for k in ("robotique", "apprentissage automatique", "vision par ordinateur", "stage"):
    cell = s.get(BASE + f"api/dossiers/{did}/keyword/{kids[k]}").json()
    occ = [o for o in cell["occurrences"] if o["filename"] == "lettre.jpg" and o["source"] == "manuscrit"]
    hand[k] = round(max([o["score"] for o in occ], default=0) * 100, 1)
print("Lecture manuscrite de la lettre (meilleur score par mot-clé, %) :", hand)
print(f"Mots-clés manuscrits retrouvés dans la lettre : {sum(1 for v in hand.values() if v >= 50)}/4")
check("export CSV", s.get(BASE + "export.csv").ok)

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
