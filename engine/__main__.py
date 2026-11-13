"""
KeyScan en ligne de commande : le moteur seul, sans interface ni serveur.

    python -m engine CV.pdf lettre.jpg releve.pdf --mots "thèse, robotique, TOEIC"
    python -m engine dossier/*.pdf --mots-fichier mots.txt --json

Les fichiers donnés forment UN dossier de candidature, avec les mêmes règles que l'application :
un fichier en double est compté une fois, un document illisible empêche d'affirmer une absence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

from .decision import LABELS, evaluate
from .extract import read_document
from .ocr import find_tesseract
from .search import find_keyword


def file_fingerprint(path: str) -> str:
    """Empreinte du contenu : deux fichiers identiques ont la même, quel que soit leur nom."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyse(files: list[str], keywords: list[str], present_thr=85.0, review_thr=50.0, min_quality=70.0,
            log=lambda message: None) -> dict:
    """Analyse un dossier (une liste de fichiers) : pour chaque mot-clé, score, décision et occurrences."""
    documents, seen = [], {}
    for path in files:
        name = os.path.basename(path)
        fingerprint = file_fingerprint(path)
        if fingerprint in seen:
            documents.append({"file": name, "status": "doublon", "same_as": seen[fingerprint]})
            log(f"  {name} : identique à {seen[fingerprint]}, ignoré")
            continue
        seen[fingerprint] = name
        started = time.time()
        try:
            result = read_document(path)
        except Exception as error:  # noqa: BLE001 — un document illisible est signalé, jamais ignoré en silence
            documents.append({"file": name, "status": "erreur", "error": str(error)[:200]})
            log(f"  {name} : ILLISIBLE ({error})")
            continue
        documents.append({"file": name, "status": "ok", **result})
        log(f"  {name} : {len(result['pages'])} page(s), lecture {result['quality']:.0f} %, {time.time() - started:.1f} s")

    read_ok = [d for d in documents if d["status"] == "ok"]
    unread = [d["file"] for d in documents if d["status"] == "erreur"]
    quality = min((d["quality"] for d in read_ok), default=0.0)
    pages = [page for d in read_ok for page in d["pages"]]
    results = []
    for keyword in keywords:
        occurrences = [{**o, "file": d["file"]} for d in read_ok for o in find_keyword(d["tokens"], keyword)]
        score, decision = evaluate(keyword, occurrences, quality, pages, present_thr, review_thr, min_quality, unread=len(unread))
        results.append({
            "keyword": keyword, "decision": decision, "label": LABELS[decision], "score": score,
            "occurrences": [{k: o[k] for k in ("file", "page", "source", "text", "score", "certain", "context")} for o in occurrences],
        })
    for d in documents:
        d.pop("tokens", None)
    return {"documents": documents, "unread": unread, "quality": round(quality, 1), "results": results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine", description="Recherche de mots-clés dans un dossier de documents.")
    parser.add_argument("files", nargs="+", help="PDF ou images d'un même dossier")
    parser.add_argument("--mots", default="", help="mots-clés séparés par des virgules")
    parser.add_argument("--mots-fichier", help="fichier texte : un mot-clé par ligne")
    parser.add_argument("--present", type=float, default=85, help="seuil « présent » (85 par défaut)")
    parser.add_argument("--verifier", type=float, default=50, help="seuil « à vérifier » (50 par défaut)")
    parser.add_argument("--lecture-min", type=float, default=70, help="qualité de lecture minimale pour affirmer une absence")
    parser.add_argument("--json", action="store_true", help="résultat complet en JSON")
    args = parser.parse_args(argv)

    keywords = [k.strip() for k in args.mots.replace(";", ",").split(",") if k.strip()]
    if args.mots_fichier:
        with open(args.mots_fichier, encoding="utf-8") as f:
            keywords += [line.strip() for line in f if line.strip()]
    if not keywords:
        parser.error("aucun mot-clé : utilisez --mots ou --mots-fichier")
    if not find_tesseract():
        print("Attention : Tesseract introuvable, les scans et les images ne pourront pas être lus.", file=sys.stderr)

    log = (lambda message: None) if args.json else (lambda message: print(message, flush=True))
    log(f"Lecture de {len(args.files)} document(s)…")
    result = analyse(args.files, keywords, args.present, args.verifier, args.lecture_min, log=log)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    if result["unread"]:
        print(f"\n⚠ Non lu(s) : {', '.join(result['unread'])}. Aucune absence n'est affirmée.")
    width = max(len(r["keyword"]) for r in result["results"])
    print(f"\n{'Mot-clé':<{width}}  {'Décision':<18}  Score  Occurrences")
    for r in sorted(result["results"], key=lambda r: -r["score"]):
        where = ", ".join(sorted({f"{o['file']} p.{o['page']}" for o in r["occurrences"]}))
        print(f"{r['keyword']:<{width}}  {r['label']:<18}  {r['score']:5.1f}  {len(r['occurrences'])}" + (f"  ({where})" if where else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
