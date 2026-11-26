"""Diagnostic temporaire : ce que lit le modèle OCR sur le document collé (déformé ou non) et sur les exemples."""
import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
import pymupdf
from PIL import Image
from engine import ocr
from engine.extract import read_document
scan = pymupdf.open(os.path.join(ROOT, "exemples", "scan.pdf"))[0].get_pixmap(dpi=150)
img = Image.frombytes("RGB", (scan.width, scan.height), scan.samples)
for name, im in [("scan 150 dpi", img), ("scan écrasé (comme le test)", img.resize((img.width, int(img.width * 500 / 495)))),
                 ("scan écrasé ×2", img.resize((img.width * 2, int(img.width * 2 * 500 / 495))))]:
    t = time.time(); r = ocr.read_image(im, 1, 0)
    print(f"--- {name} {im.size} {time.time()-t:.2f}s rot={r['rotation']}:", " ".join(x["t"] for x in r["tokens"])[:300])
for f in ["scan.pdf", "cv_tourne.jpg", "manuscrit.png"]:
    t = time.time(); r = read_document(os.path.join(ROOT, "exemples", f))
    print(f"--- {f} {time.time()-t:.2f}s {r['pages']} q={r['quality']}:", " ".join(x["t"] for x in r["tokens"])[:300])
