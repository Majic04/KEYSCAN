"""Évalue un moteur (dossier contenant le paquet engine/) sur le banc d'essai.
usage : python evaluate.py <racine_moteur> <dossier_banc> <sortie.json>"""
import json, os, sys, time

root, bench, out = sys.argv[1:4]
sys.path.insert(0, root)
from engine.extract import extract_document, configure_tesseract  # noqa: E402
from engine.matcher import find_keyword, combine, decide, is_fragile  # noqa: E402

configure_tesseract()
T = json.load(open(os.path.join(bench, "truth.json")))
KW = T["keywords"]
rows, t0 = [], time.time()
for doc, present in T["truth"].items():
    t = time.time()
    r = extract_document(os.path.join(bench, doc))
    dt = time.time() - t
    for k in KW:
        occ = find_keyword(r["tokens"], k)
        s = round(combine([o["score"] for o in occ]) * 100, 1)
        dec = decide(s, r["quality"], 85, 50, 70, fragile=is_fragile(k, [p["mode"] for p in r["pages"]]))
        rows.append({"doc": doc, "kw": k, "truth": k in present, "score": s, "decision": dec, "quality": r["quality"], "sec": round(dt, 2)})

tp = sum(r["truth"] and r["decision"] == "present" for r in rows)
fp = sum(not r["truth"] and r["decision"] == "present" for r in rows)
fn = sum(r["truth"] and r["decision"] in ("absent", "absent_douteux") for r in rows)
tn = sum(not r["truth"] and r["decision"] in ("absent", "absent_douteux") for r in rows)
rev_t = sum(r["truth"] and r["decision"] == "a_verifier" for r in rows)
rev_f = sum(not r["truth"] and r["decision"] == "a_verifier" for r in rows)
# erreur grave = décision ferme et fausse (« présent » à tort, ou « absent » sûr à tort)
silent_fn = sum(r["truth"] and r["decision"] == "absent" for r in rows)
P = sum(r["truth"] for r in rows)
summary = {
    "paires": len(rows), "presents_reels": P,
    "vrais_positifs": tp, "faux_positifs": fp, "faux_negatifs": fn, "vrais_negatifs": tn,
    "a_verifier_vrais": rev_t, "a_verifier_faux": rev_f, "absents_surs_a_tort": silent_fn,
    "precision": round(tp / (tp + fp) * 100, 1) if tp + fp else 0,
    "rappel": round(tp / P * 100, 1),
    "exactitude_decisions_fermes": round((tp + tn) / max(1, tp + tn + fp + fn) * 100, 1),
    "score_moyen_vrais_presents": round(sum(r["score"] for r in rows if r["truth"]) / P, 1),
    "score_max_faux": max([r["score"] for r in rows if not r["truth"]] + [0]),
    "temps_total_s": round(time.time() - t0, 1),
}
json.dump({"summary": summary, "rows": rows}, open(out, "w"), ensure_ascii=False, indent=1)
print(json.dumps(summary, ensure_ascii=False, indent=1))
for r in rows:
    if (r["truth"] and r["decision"] != "present") or (not r["truth"] and r["decision"] != "absent" and r["decision"] != "absent_douteux"):
        print(f'  ✗ {r["doc"]:22s} {r["kw"]:26s} vérité={"oui" if r["truth"] else "non"}  {r["decision"]:14s} {r["score"]:5.1f}  q={r["quality"]}')
