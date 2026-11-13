"""
Tests des règles de décision (moteur Python seul, sans interface ni serveur).
Reprennent notamment les 3 anomalies du rapport « Remarques et recommandations sur l'algorithme d'analyse » :
  1. un mot seulement approchant, même répété, ne devient jamais « présent » ;
  2. un fichier déposé deux fois n'est compté qu'une fois ;
  3. un document illisible empêche d'affirmer une absence.

usage : python tests/test_regles.py      (code de sortie 1 en cas d'échec)
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pymupdf  # noqa: E402

from engine.__main__ import analyse  # noqa: E402
from engine.decision import evaluate  # noqa: E402
from engine.ocr import find_tesseract  # noqa: E402
from engine.search import find_keyword  # noqa: E402
from engine.text import word_parts  # noqa: E402

find_tesseract()
TMP = tempfile.mkdtemp(prefix="keyscan-tests-")
failures = []


def check(name, cond, detail=""):
    print(("OK     " if cond else "ÉCHEC  ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def pdf(name, text):
    path = os.path.join(TMP, name)
    d = pymupdf.open()
    page = d.new_page()
    for i, line in enumerate(text.split("\n")):
        page.insert_text((72, 90 + 20 * i), line, fontsize=12)
    d.save(path)
    return path


def tokens(text, source="texte", conf=100.0):
    return [{"t": r, "r": r, "n": n, "c": conf, "p": 1, "s": source, "k": 0, "w": i, "b": [i * .05, 0, i * .05 + .04, .02]}
            for i, (r, n) in enumerate(word_parts(text))]


def result(res, kw):
    return next(r for r in res["results"] if r["keyword"] == kw)


# --- 1. répétition d'un mot approchant (exemple du rapport : « these » dans un CV anglais, mot-clé « thèse »)
for n in (1, 2, 3, 6):
    occ = find_keyword(tokens(" ".join(["these results"] * n)), "thèse")
    score, dec = evaluate("thèse", occ, 100, [{"mode": "texte"}])
    check(f"« these » ×{n} → à vérifier, score plafonné", dec == "a_verifier" and score == 72.0, f"{score} % {dec}")
occ = find_keyword(tokens("ma thèse et ces thèses"), "thèse")
check("« thèse » exact (×2) → présent", evaluate("thèse", occ, 100, [{"mode": "texte"}])[1] == "present")
for src in ("ocr", "manuscrit"):
    occ = find_keyword(tokens(" ".join(["robotiqe"] * 5), src, 95), "robotique")
    score, dec = evaluate("robotique", occ, 95, [{"mode": "ocr"}])
    check(f"lecture approchée répétée ({src}) → jamais présent", dec != "present", f"{score} % {dec}")
occ = find_keyword(tokens("Ingénierie en robotique", "ocr", 90), "robotique")
check("lecture OCR exacte → présent", evaluate("robotique", occ, 95, [{"mode": "ocr"}])[1] == "present")

# --- 2. doublons de fichiers
cv = pdf("cv_en.pdf", "Research on these topics.\nThese projects matter.\nSkills: Python, robotics.")
copy = os.path.join(TMP, "cv_en_copie.pdf")
with open(cv, "rb") as a, open(copy, "wb") as b:
    b.write(a.read())
res = analyse([cv, copy], ["thèse", "Python"])
check("fichier identique déposé 2 fois : compté une fois", [d["status"] for d in res["documents"]] == ["ok", "doublon"])
check("doublon : « thèse » reste à vérifier", result(res, "thèse")["decision"] == "a_verifier", str(result(res, "thèse")["score"]))

# --- 3. document illisible
bad = os.path.join(TMP, "protege.pdf")
with open(bad, "wb") as f:
    f.write(b"%PDF-1.4\n\x00 ceci n'est pas un PDF lisible")
ok_doc = pdf("lettre.pdf", "Lettre de motivation pour le Master.\nJe souhaite rejoindre le parcours robotique.")
res = analyse([ok_doc, bad], ["Master", "chimie"])
check("document illisible signalé", res["unread"] == ["protege.pdf"], str(res["unread"]))
check("illisible : absence incertaine (pas « absent »)", result(res, "chimie")["decision"] == "absent_douteux")
check("illisible : un mot trouvé reste présent", result(res, "Master")["decision"] == "present")
res = analyse([ok_doc], ["chimie"])
check("sans document illisible : absent", result(res, "chimie")["decision"] == "absent")

# --- 4. mot-clé à l'intérieur d'un mot plus long (« pour » dans « pourquoi »)
def words(ws, source="texte", gap=0.01):
    out, x = [], 0.05
    for wi, w in enumerate(ws):
        wd = 0.012 * len(w)
        for r, n in word_parts(w):
            out.append({"t": w, "r": r, "n": n, "c": 95.0, "p": 1, "s": source, "k": 0, "w": wi, "b": [x, .1, x + wd, .12]})
        x += wd + gap
    return out


def decision(ws, kw, source="texte", gap=0.01):
    return evaluate(kw, find_keyword(words(ws, source, gap), kw), 95, [{"mode": "texte"}])[1]


for ws, kw, want, label in [
    (["pourquoi"], "pour", "absent", "« pourquoi » ne contient pas le mot « pour »"),
    (["pour-", "quoi"], "pour", "absent", "« pour- / quoi » coupé en fin de ligne"),
    (["pour\u00adquoi"], "pour", "absent", "trait d'union conditionnel invisible"),
    (["merci", "pour", "tout"], "pour", "present", "« pour » seul reste présent"),
    (["l'apprentissage"], "apprentissage", "present", "élision : « l'apprentissage »"),
    (["d\u2019ingénieur"], "ingénieur", "present", "élision : « d'ingénieur »"),
    (["Master-Recherche"], "Master", "a_verifier", "mot composé : à vérifier"),
    (["apprentis-", "sage", "automatique"], "apprentissage automatique", "present", "césure dans le mot-clé lui-même"),
]:
    got = decision(ws, kw)
    check(label, got == want, got)
check("OCR : « pour » et « quoi » collés sur l'image", decision(["pour", "quoi"], "pour", "ocr", gap=0.001) == "absent")
check("OCR : « pour quoi » bien espacés", decision(["pour", "quoi"], "pour", "ocr", gap=0.01) == "present")

# --- règles existantes
check("mot-clé de 2 lettres dans un scan : jamais absent sûr",
      evaluate("IA", [], 95, [{"mode": "ocr"}])[1] == "absent_douteux")
check("dossier avec écriture manuscrite : jamais absent sûr",
      evaluate("stage", [], 95, [{"mode": "ocr", "manuscrit": 3}])[1] == "absent_douteux")
check("lecture insuffisante : absence incertaine", evaluate("stage", [], 60, [{"mode": "ocr"}])[1] == "absent_douteux")

# --------------------------------------------------------------------------- PDF avec images
# Une page de texte avec un logo : le logo n'est pas lu par l'OCR (la page reste en mode « texte »).
# Une page de texte avec un grand document photographié collé dedans : seule cette image est lue,
# et les mots trouvés dedans sont bien placés sur la page.
from engine.extract import read_document  # noqa: E402

folder = tempfile.mkdtemp()
scan = pymupdf.open(os.path.join(ROOT, "exemples", "scan.pdf"))[0].get_pixmap(dpi=150)
scan_path = os.path.join(folder, "scan.png")
scan.save(scan_path)
pdf = pymupdf.open()
page = pdf.new_page()
page.insert_text((50, 60), "Dossier de candidature : copie du relevé de notes ci-dessous.", fontsize=11)
page.insert_image(pymupdf.Rect(520, 20, 570, 70), filename=scan_path)        # petit : un « logo »
zone = pymupdf.Rect(50, 300, 545, 800)
page.insert_image(zone, filename=scan_path)                                   # grand : un document collé
logo_only = pymupdf.open()
logo_page = logo_only.new_page()
logo_page.insert_text((50, 60), "Curriculum vitae : Master de robotique, stage de six mois.", fontsize=11)
logo_page.insert_image(pymupdf.Rect(520, 20, 570, 70), filename=scan_path)
pdf.save(os.path.join(folder, "colle.pdf"))
logo_only.save(os.path.join(folder, "logo.pdf"))

reading = read_document(os.path.join(folder, "logo.pdf"))
check("PDF avec un logo : pas d'OCR inutile", reading["pages"][0]["mode"] == "texte", str(reading["pages"]))
reading = read_document(os.path.join(folder, "colle.pdf"))
found = [o for o in find_keyword(reading["tokens"], "TOEIC") if o["source"] == "ocr"]
check("document collé dans un PDF : lu par l'OCR", reading["pages"][0]["mode"] == "mixte" and found, str(reading["pages"]))
inside = found and all(zone.x0 / page.rect.width - 0.01 <= o["box"][0] and o["box"][2] <= zone.x1 / page.rect.width + 0.01
                       and zone.y0 / page.rect.height - 0.01 <= o["box"][1] and o["box"][3] <= zone.y1 / page.rect.height + 0.01
                       for o in found)
check("document collé : mot placé dans l'image, sur la page", inside, str([o["box"] for o in found]))

print(f"\n{len(failures)} échec(s)" if failures else "\nTous les tests de règles sont passés.")
sys.exit(1 if failures else 0)
