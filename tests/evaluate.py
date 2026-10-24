"""
Banc d'essai de l'OCR : mesure la justesse des décisions sur des documents piégés dont on connaît la vérité.

    python tests/make_bench.py /tmp/banc                         (fabrique les documents une fois)
    python tests/evaluate.py . /tmp/banc resultats.json

Chiffres affichés :
  précision   : parmi les « Présent », combien sont justes
  rappel      : parmi les mots vraiment présents, combien sont déclarés « Présent »
  absents sûrs à tort : mots présents déclarés « Absent » sans réserve (l'erreur la plus grave)
"""
import json
import os
import sys
import time

engine_root, bench_dir, output_file = sys.argv[1:4]
sys.path.insert(0, engine_root)
from engine.decision import ABSENT, PRESENT, TO_CHECK, UNCERTAIN, evaluate  # noqa: E402
from engine.extract import read_document  # noqa: E402
from engine.ocr import find_tesseract  # noqa: E402
from engine.search import find_keyword  # noqa: E402

find_tesseract()
with open(os.path.join(bench_dir, "truth.json"), encoding="utf-8") as f:
    truth = json.load(f)

rows, started = [], time.time()
for document, present_keywords in truth["truth"].items():
    reading = read_document(os.path.join(bench_dir, document))
    for keyword in truth["keywords"]:
        score, decision = evaluate(keyword, find_keyword(reading["tokens"], keyword), reading["quality"], reading["pages"])
        rows.append({"doc": document, "kw": keyword, "truth": keyword in present_keywords,
                     "score": score, "decision": decision, "quality": reading["quality"]})


def count(truly_present: bool, decisions: tuple) -> int:
    return sum(1 for r in rows if r["truth"] == truly_present and r["decision"] in decisions)


right_present, wrong_present = count(True, (PRESENT,)), count(False, (PRESENT,))
missed, right_absent = count(True, (ABSENT, UNCERTAIN)), count(False, (ABSENT, UNCERTAIN))
really_present = sum(r["truth"] for r in rows)
summary = {
    "paires": len(rows), "presents_reels": really_present,
    "vrais_positifs": right_present, "faux_positifs": wrong_present, "faux_negatifs": missed, "vrais_negatifs": right_absent,
    "a_verifier_vrais": count(True, (TO_CHECK,)), "a_verifier_faux": count(False, (TO_CHECK,)),
    "absents_surs_a_tort": count(True, (ABSENT,)),
    "precision": round(right_present / (right_present + wrong_present) * 100, 1) if right_present + wrong_present else 0,
    "rappel": round(right_present / really_present * 100, 1),
    "exactitude_decisions_fermes": round((right_present + right_absent) / max(1, right_present + right_absent + wrong_present + missed) * 100, 1),
    "score_moyen_vrais_presents": round(sum(r["score"] for r in rows if r["truth"]) / really_present, 1),
    "score_max_faux": max([r["score"] for r in rows if not r["truth"]] + [0]),
    "temps_total_s": round(time.time() - started, 1),
}
with open(output_file, "w", encoding="utf-8") as f:
    json.dump({"summary": summary, "rows": rows}, f, ensure_ascii=False, indent=1)
print(json.dumps(summary, ensure_ascii=False, indent=1))
for r in rows:
    wrong = (r["truth"] and r["decision"] != PRESENT) or (not r["truth"] and r["decision"] not in (ABSENT, UNCERTAIN))
    if wrong:
        print(f'  ✗ {r["doc"]:22s} {r["kw"]:26s} vérité={"oui" if r["truth"] else "non"}  {r["decision"]:14s} {r["score"]:5.1f}  q={r["quality"]}')
