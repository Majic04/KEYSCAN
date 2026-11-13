"""
Banc d'essai de l'écriture manuscrite : des lettres écrites avec des polices manuscrites irrégulières.
On cherche les mots-clés SANS puis AVEC le module manuscrit, et on mesure le taux d'erreur de lecture
par caractère (CER) du modèle TrOCR.

    python tests/evaluate_manuscrit.py        (la 2e partie demande le module manuscrit installé)
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from rapidfuzz.distance import Levenshtein  # noqa: E402

from engine import ocr, trocr  # noqa: E402
from engine.decision import ABSENT, PRESENT, TO_CHECK, evaluate  # noqa: E402
from engine.extract import read_document  # noqa: E402
from engine.search import find_keyword  # noqa: E402
from engine.text import normalize  # noqa: E402

FOLDER = os.path.join(ROOT, "tests", "manuscrit")
with open(os.path.join(FOLDER, "truth.json"), encoding="utf-8") as f:
    TRUTH = json.load(f)
ocr.find_tesseract()
handwriting_text = {}


def run(with_handwriting: bool):
    # on force l'état du module manuscrit (au lieu de le vérifier sur le disque)
    ocr._handwriting_check.update(time=1e18, available=with_handwriting)
    results, started = {}, time.time()
    for document in TRUTH["truth"]:
        reading = read_document(os.path.join(FOLDER, document))
        for keyword in TRUTH["keywords"]:
            score, decision = evaluate(keyword, find_keyword(reading["tokens"], keyword), reading["quality"], reading["pages"])
            results[(document, keyword)] = (decision, score)
        if with_handwriting:
            words, seen = [], set()
            for token in reading["tokens"]:
                if token["s"] == "manuscrit" and token["w"] not in seen:
                    seen.add(token["w"])
                    words.append(token["t"])
            handwriting_text[document] = " ".join(words)
            print(f"  {document} — lu par TrOCR : {handwriting_text[document]}")
    return results, time.time() - started


def summary(name, results, seconds):
    def count(present, decision):
        return sum(1 for (doc, kw), (dec, _) in results.items() if (kw in TRUTH["truth"][doc]["present"]) == present and dec == decision)
    total = sum(len(v["present"]) for v in TRUTH["truth"].values())
    print(f"{name:28s} trouvés {count(True, PRESENT)}/{total} · à vérifier {count(True, TO_CHECK)} · "
          f"faux présents {count(False, PRESENT)} · absents sûrs à tort {count(True, ABSENT)} · {seconds:.1f} s")


without, seconds = run(False)
summary("SANS module manuscrit", without, seconds)
if not trocr.available():
    sys.exit("Module manuscrit non installé : seconde partie ignorée.")
with_hw, seconds = run(True)
summary("AVEC module manuscrit", with_hw, seconds)
for (document, keyword), (decision, score) in with_hw.items():
    if keyword in TRUTH["truth"][document]["present"] or decision == PRESENT:
        print(f"  {document:13s} {keyword:24s} {without[(document, keyword)][0]:14s} → {decision:11s} {score:5.1f}")

# taux d'erreur par caractère : texte lu par TrOCR comparé au texte réellement écrit (sans accents ni majuscules)
errors = letters = 0
for document, truth in TRUTH["truth"].items():
    expected, read = normalize(" ".join(truth["texte"])), normalize(handwriting_text.get(document, ""))
    distance = Levenshtein.distance(read, expected)
    errors += distance
    letters += len(expected)
    print(f"  CER {document:13s} {distance / len(expected) * 100:5.1f} %")
print(f"CER global : {errors / letters * 100:.1f} %  (les lignes imprimées bien lues par Tesseract ne sont pas relues)")
