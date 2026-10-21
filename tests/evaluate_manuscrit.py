"""
Banc d'essai de l'écriture manuscrite : lettres écrites avec des polices manuscrites irrégulières.
Compare la détection des mots-clés SANS puis AVEC le module manuscrit, et mesure le taux d'erreur
de lecture par caractère (CER) de TrOCR sur chaque ligne.
usage : python tests/evaluate_manuscrit.py   (module manuscrit installé requis pour la 2e partie)
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from rapidfuzz.distance import Levenshtein
from engine import extract as ex, handwriting as hw
from engine.extract import normalize
from engine.matcher import find_keyword, evaluate

D = os.path.join(ROOT, "tests", "manuscrit")
T = json.load(open(os.path.join(D, "truth.json"), encoding="utf-8"))
ex.configure_tesseract()


READ = {}


def run(htr):
    ex._HW_STATE.update(checked=1e18, ok=htr)
    res, t0 = {}, time.time()
    for doc in T["truth"]:
        r = ex.extract_document(os.path.join(D, doc))
        for k in T["keywords"]:
            occ = find_keyword(r["tokens"], k)
            s, dec = evaluate(k, occ, r["quality"], r["pages"])
            res[(doc, k)] = (dec, s)
        if htr:
            seen, words = set(), []
            for t in r["tokens"]:
                if t["s"] == "manuscrit" and t["w"] not in seen:
                    seen.add(t["w"]); words.append(t["t"])
            READ[doc] = " ".join(words)
            print(f"  {doc} — lu par TrOCR : {READ[doc]}")
    return res, time.time() - t0


def summary(name, res, dt):
    tp = sum(1 for (d, k), v in res.items() if k in T["truth"][d]["present"] and v[0] == "present")
    fp = sum(1 for (d, k), v in res.items() if k not in T["truth"][d]["present"] and v[0] == "present")
    rv = sum(1 for (d, k), v in res.items() if k in T["truth"][d]["present"] and v[0] == "a_verifier")
    sure = sum(1 for (d, k), v in res.items() if k in T["truth"][d]["present"] and v[0] == "absent")
    P = sum(len(v["present"]) for v in T["truth"].values())
    print(f"{name:28s} trouvés {tp}/{P} · à vérifier {rv} · faux présents {fp} · absents sûrs à tort {sure} · {dt:.1f} s")


off, dt0 = run(False)
summary("SANS module manuscrit", off, dt0)
if not hw.available():
    sys.exit("Module manuscrit non installé : seconde partie ignorée.")
on, dt1 = run(True)
summary("AVEC module manuscrit", on, dt1)
for (d, k), v in on.items():
    if k in T["truth"][d]["present"] or v[0] == "present":
        print(f"  {d:13s} {k:24s} {off[(d, k)][0]:14s} → {v[0]:11s} {v[1]:5.1f}")

# taux d'erreur de lecture par caractère (CER) : texte lu par TrOCR vs texte réellement écrit (sans accents ni casse)
errs = tot = 0
for doc, t in T["truth"].items():
    ref, got = normalize(" ".join(t["texte"])), normalize(READ.get(doc, ""))
    e = Levenshtein.distance(got, ref)
    errs += e; tot += len(ref)
    print(f"  CER {doc:13s} {e / len(ref) * 100:5.1f} %")
print(f"CER global : {errs / tot * 100:.1f} %  (les lignes imprimées bien lues par Tesseract ne sont pas relues)")
