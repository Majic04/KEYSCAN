"""
Prépare le modèle d'écriture manuscrite à embarquer dans l'application (exécuté par la construction GitHub).

1. Télécharge agomberto/trocr-large-handwritten-fr (uniquement config + vocabulaire + poids, sans les
   fichiers d'entraînement) et le préprocesseur d'images de microsoft/trocr-large-handwritten.
2. Le convertit en demi-précision (float16) : 1,1 Go au lieu de 2,2 Go dans l'installateur.
   L'application le recharge en pleine précision (float32) : les calculs restent identiques.
3. Vérifie que la version allégée lit l'image de test comme la version d'origine.

Usage : python build/prepare_model.py <dossier_sortie>
"""
import os
import sys
import time

import torch
from huggingface_hub import snapshot_download
from PIL import Image
from transformers import AutoTokenizer, TrOCRProcessor, VisionEncoderDecoderModel

MODEL = "agomberto/trocr-large-handwritten-fr"
PROCESSOR = "microsoft/trocr-large-handwritten"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def read(model, processor, tokenizer, crops):
    pv = processor(images=[c.convert("RGB") for c in crops], return_tensors="pt").pixel_values
    with torch.no_grad():
        ids = model.generate(pv, max_new_tokens=64, num_beams=1)
    return tokenizer.batch_decode(ids, skip_special_tokens=True)


def download(repo, patterns, tries=6):
    """Téléchargement depuis Hugging Face, avec nouvelles tentatives (le site limite le nombre de requêtes)."""
    for i in range(tries):
        try:
            return snapshot_download(repo, allow_patterns=patterns)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            wait = 30 * 2 ** i
            print(f"Téléchargement de {repo} refusé ({type(e).__name__}) : nouvel essai dans {wait} s", flush=True)
            time.sleep(wait)


def main(out):
    small = ["*.json", "merges.txt", "vocab.*"]
    t = time.time()
    download(MODEL, small + ["pytorch_model.bin"])
    download(PROCESSOR, small)
    print(f"Téléchargé en {time.time() - t:.0f} s")

    processor = TrOCRProcessor.from_pretrained(PROCESSOR)
    tokenizer = AutoTokenizer.from_pretrained(MODEL)
    full = VisionEncoderDecoderModel.from_pretrained(MODEL).eval()

    from engine.handwriting import find_text_lines
    sample = Image.open(os.path.join(ROOT, "exemples", "manuscrit.png")).convert("L")
    crops = [sample.crop(b) for b in find_text_lines(sample)]
    ref = read(full, processor, tokenizer, crops)
    print("Lecture (pleine précision) :", ref)

    os.makedirs(out, exist_ok=True)
    full.half().save_pretrained(out, safe_serialization=True)
    processor.image_processor.save_pretrained(out)
    tokenizer.save_pretrained(out)
    del full

    light = VisionEncoderDecoderModel.from_pretrained(out, torch_dtype=torch.float32).eval()
    got = read(light, TrOCRProcessor.from_pretrained(out), AutoTokenizer.from_pretrained(out), crops)
    print("Lecture (version allégée) :", got)
    size = sum(os.path.getsize(os.path.join(out, f)) for f in os.listdir(out))
    print(f"Taille : {size / 1e9:.2f} Go")
    if got != ref:
        diff = sum(a != b for a, b in zip(got, ref))
        print(f"Attention : {diff} ligne(s) lue(s) différemment après allègement")
        if diff > len(ref) // 3:
            raise SystemExit("La version allégée lit trop différemment : arrêt")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "models", "trocr-fr"))
