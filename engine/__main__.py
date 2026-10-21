"""
KeyScan en ligne de commande : le moteur d'analyse seul, 100 % Python, sans interface ni serveur.

    python -m engine CV.pdf lettre.jpg releve.pdf --mots "thèse, robotique, TOEIC"
    python -m engine dossier/*.pdf --mots-fichier mots.txt --json

Les fichiers donnés forment UN dossier de candidature : mêmes règles que l'application
(doublons comptés une fois, document illisible → aucune absence affirmée, seuils réglables).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

from .extract import configure_tesseract, extract_document
from .matcher import evaluate, find_keyword

LABELS = {"present": "Présent", "a_verifier": "À vérifier", "absent": "Absent", "absent_douteux": "Absence incertaine"}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def analyse(files: list[str], keywords: list[str], present_thr=85.0, review_thr=50.0, min_quality=70.0,
            log=lambda *_: None) -> dict:
    """Analyse un dossier (liste de fichiers) et rend, pour chaque mot-clé, score, décision et occurrences."""
    seen, docs = {}, []
    for path in files:
        name = os.path.basename(path)
        digest = sha256(path)
        if digest in seen:
            docs.append({"file": name, "status": "doublon", "same_as": seen[digest]})
            log(f"  {name} : identique à {seen[digest]}, ignoré")
            continue
        seen[digest] = name
        t = time.time()
        try:
            res = extract_document(path)
            docs.append({"file": name, "status": "ok", "quality": res["quality"], "pages": res["pages"], "tokens": res["tokens"]})
            log(f"  {name} : {len(res['pages'])} page(s), lecture {res['quality']:.0f} %, {time.time() - t:.1f} s")
        except Exception as e:  # noqa: BLE001 — document illisible : signalé, jamais ignoré en silence
            docs.append({"file": name, "status": "erreur", "error": str(e)[:200]})
            log(f"  {name} : ILLISIBLE ({e})")
    ready = [d for d in docs if d["status"] == "ok"]
    unread = [d["file"] for d in docs if d["status"] == "erreur"]
    quality = min((d["quality"] for d in ready), default=0.0)
    pages = [p for d in ready for p in d["pages"]]
    results = []
    for kw in keywords:
        occ = [{**o, "file": d["file"]} for d in ready for o in find_keyword(d["tokens"], kw)]
        score, decision = evaluate(kw, occ, quality, pages, present_thr, review_thr, min_quality, unread=len(unread))
        results.append({"keyword": kw, "decision": decision, "label": LABELS[decision], "score": score,
                        "occurrences": [{k: o[k] for k in ("file", "page", "source", "text", "score", "certain", "context")}
                                        for o in occ]})
    for d in docs:
        d.pop("tokens", None)
    return {"documents": docs, "unread": unread, "quality": round(quality, 1), "results": results}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine", description="Recherche de mots-clés dans un dossier de documents.")
    ap.add_argument("files", nargs="+", help="PDF ou images d'un même dossier")
    ap.add_argument("--mots", default="", help="mots-clés séparés par des virgules")
    ap.add_argument("--mots-fichier", help="fichier texte : un mot-clé par ligne")
    ap.add_argument("--present", type=float, default=85, help="seuil « présent » (défaut 85)")
    ap.add_argument("--verifier", type=float, default=50, help="seuil « à vérifier » (défaut 50)")
    ap.add_argument("--lecture-min", type=float, default=70, help="qualité de lecture minimale pour affirmer une absence")
    ap.add_argument("--json", action="store_true", help="résultat complet en JSON")
    a = ap.parse_args(argv)

    kws = [k.strip() for k in a.mots.replace(";", ",").split(",") if k.strip()]
    if a.mots_fichier:
        with open(a.mots_fichier, encoding="utf-8") as f:
            kws += [line.strip() for line in f if line.strip()]
    if not kws:
        ap.error("aucun mot-clé : utilisez --mots ou --mots-fichier")
    if not configure_tesseract():
        print("Attention : Tesseract introuvable, les scans et images ne pourront pas être lus.", file=sys.stderr)

    log = (lambda *_: None) if a.json else (lambda m: print(m, flush=True))
    log(f"Lecture de {len(a.files)} document(s)…")
    res = analyse(a.files, kws, a.present, a.verifier, a.lecture_min, log=log)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    if res["unread"]:
        print(f"\n⚠ Non lu(s) : {', '.join(res['unread'])} — aucune absence n'est affirmée.")
    w = max(len(r["keyword"]) for r in res["results"])
    print(f"\n{'Mot-clé':<{w}}  {'Décision':<18}  Score  Occurrences")
    for r in sorted(res["results"], key=lambda r: -r["score"]):
        where = ", ".join(sorted({f"{o['file']} p.{o['page']}" for o in r["occurrences"]}))
        print(f"{r['keyword']:<{w}}  {r['label']:<18}  {r['score']:5.1f}  {len(r['occurrences'])}" + (f"  ({where})" if where else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
