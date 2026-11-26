"""
Lecture d'une image par OCR, avec le modèle OCRia-nano-1 (LlamaIndex), lancé par la bibliothèque LiteParse.

OCRia-nano-1 : 8 millions de paramètres, tourne sur le processeur (ONNX Runtime), sans carte graphique.
Il trouve les lignes de texte de l'image, puis lit chaque ligne (KeyScan la découpe en mots, pour les surligner).

Étapes pour une image de page :
  1. préparation : niveaux de gris, orientation de l'appareil photo, agrandissement des petites images ;
  2. inclinaison fine : une photo légèrement penchée est redressée (jusqu'à ±12°) ;
  3. lecture par OCRia-nano ;
  4. orientation : seulement si la lecture est mauvaise, on essaie la page tournée (90, 180, 270°)
     et on garde le sens où le modèle lit le mieux ;
  5. secours : si la lecture reste médiocre, une seconde lecture sur l'image nettoyée (noir et blanc)
     complète la première.

Les modèles (environ 70 Mo, avec ONNX Runtime) s'installent une fois : python -m engine.ocr --install
L'application de bureau les embarque (variable LITEPARSE_MODEL_DIR).
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import threading

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .text import make_tokens

MODEL = "ocria-nano"
MIN_WIDTH = 1800              # une image plus étroite est agrandie (au plus ×3) : le modèle lit mieux
GOOD_ENOUGH = 0.85            # confiance moyenne (0 à 1) à partir de laquelle une seule lecture suffit
SECONDARY_MIN_CONFIDENCE = 0.4  # mots de la lecture de secours gardés à partir de cette confiance

_parsers = threading.local()       # un lecteur LiteParse par ouvrier : plusieurs documents sont lus en même temps


# =========================================================================== le modèle
def models_ready() -> bool:
    """Les modèles OCRia-nano sont-ils installés (complets) ?"""
    try:
        from liteparse import models
        return any(m.name == MODEL and m.complete for m in models.list())
    except Exception:  # noqa: BLE001 — LiteParse absent ou dossier des modèles illisible
        return False


def install_models() -> str:
    """Télécharge les modèles (une seule fois) et retourne leur dossier."""
    from liteparse import models
    return models.pull(MODEL)


def _ocr():
    """Le lecteur LiteParse de cet ouvrier, créé une seule fois (une seule image à la fois par lecteur)."""
    if not hasattr(_parsers, "parser"):
        from liteparse import LiteParse
        backend = os.environ.get("KEYSCAN_OCR_BACKEND", MODEL)   # « tesseract » : seulement pour développer sans les modèles
        _parsers.parser = LiteParse(ocr_backend=backend, emit_word_boxes=True, num_workers=1, quiet=True)
    return _parsers.parser


# =========================================================================== 1. préparation de l'image
def prepare(image: Image.Image) -> Image.Image:
    """Niveaux de gris, orientation de l'appareil photo appliquée, petites images agrandies."""
    gray = ImageOps.exif_transpose(image).convert("L")
    if gray.width < MIN_WIDTH:
        factor = min(3.0, MIN_WIDTH / gray.width)
        gray = gray.resize((int(gray.width * factor), int(gray.height * factor)), Image.LANCZOS)
    return gray


def otsu_threshold(pixels: np.ndarray) -> int:
    """
    Seuil d'Otsu : la valeur de gris qui sépare le mieux les pixels en deux groupes (encre / papier).
    On essaie tous les seuils et on garde celui qui rend les deux groupes les plus différents.
    """
    histogram = np.bincount(pixels.ravel(), minlength=256).astype(float)
    count_below = np.cumsum(histogram)
    sum_below = np.cumsum(histogram * np.arange(256))
    total_count, total_sum = count_below[-1], sum_below[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        separation = (total_sum * count_below / total_count - sum_below) ** 2 / (count_below * (total_count - count_below))
    separation[~np.isfinite(separation)] = 0
    return int(np.argmax(separation))


def cleaned(gray: Image.Image) -> Image.Image:
    """Image nettoyée : contraste étiré, bruit atténué (filtre médian), puis noir et blanc (seuil d'Otsu)."""
    image = ImageOps.autocontrast(gray, cutoff=0.5).filter(ImageFilter.MedianFilter(3))
    threshold = otsu_threshold(np.asarray(image))
    return image.point(lambda v: 255 if v > threshold else 0)


# =========================================================================== 2. inclinaison
def estimate_skew(gray: Image.Image, max_angle: float = 12.0) -> float:
    """
    Inclinaison du texte en degrés. On fait tourner l'image et, pour chaque angle, on regarde le profil
    d'encre ligne par ligne : quand les lignes de texte sont bien horizontales, ce profil alterne
    franchement entre lignes et interlignes. L'angle le plus « net » gagne (au 1/10 de degré près).
    """
    small = gray.copy()
    small.thumbnail((1000, 1000))
    pixels = np.asarray(small)
    black_and_white = (pixels < otsu_threshold(pixels)).astype(np.uint8) * 255
    if black_and_white.mean() < 0.5 or black_and_white.mean() > 128:   # page vide ou image pleine
        return 0.0
    image = Image.fromarray(black_and_white)

    def sharpness(angle):
        profile = np.asarray(image.rotate(angle, resample=Image.NEAREST), dtype=np.float32).sum(axis=1)
        return float(np.sum(np.diff(profile) ** 2))

    coarse = max(np.arange(-max_angle, max_angle + 0.01, 0.5), key=sharpness)
    fine = max(np.arange(coarse - 0.5, coarse + 0.51, 0.1), key=sharpness)
    return round(float(fine), 1) if abs(fine) >= 0.3 else 0.0


def _straightened(gray: Image.Image) -> tuple[Image.Image, float]:
    """L'image redressée si elle est penchée, et l'angle de redressement."""
    skew = estimate_skew(gray)
    if skew:
        gray = gray.rotate(skew, expand=True, fillcolor=255, resample=Image.BICUBIC)
    return gray, skew


# =========================================================================== 3. lecture par OCRia-nano
def ocr_reading(image: Image.Image) -> dict:
    """
    Une lecture de l'image par le modèle. Retourne les mots lus (texte, confiance de 0 à 1, boîte en
    fractions de l'image), leur confiance moyenne, et un « poids » (confiance × longueur) pour comparer deux lectures.
    """
    handle, path = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    try:
        image.save(path)
        page = _ocr().parse(path).pages[0]
    finally:
        os.remove(path)
    words = []
    for item in page.text_items:
        confidence = item.confidence if item.confidence is not None else 1.0      # le modèle note chaque ligne
        for box in item.words or [item]:
            words += _split_line(box, confidence, page.width, page.height)
    weight = sum(w["confidence"] * len(w["text"]) for w in words)
    mean = sum(w["confidence"] for w in words) / len(words) if words else 0.0
    return {"words": words, "weight": weight, "mean": mean}


def _split_line(box, confidence: float, page_width: float, page_height: float) -> list[dict]:
    """
    Le modèle donne un morceau de ligne d'un seul bloc (« Certificat TOEIC : 925 points. ») : on le coupe en mots.
    La place de chaque mot dans le bloc est estimée d'après ses lettres (« TOEIC » commence au 12e caractère sur 30).
    """
    text, length = box.text, max(1, len(box.text))
    words = []
    for match in re.finditer(r"\S+", text):
        left = box.x + box.width * match.start() / length
        right = box.x + box.width * match.end() / length
        words.append({"text": match.group(), "confidence": confidence,
                      "box": [left / page_width, box.y / page_height, right / page_width, (box.y + box.height) / page_height]})
    return words


def is_poor(reading: dict) -> bool:
    return reading["mean"] < GOOD_ENOUGH or len(reading["words"]) < 5


def best_orientation(gray: Image.Image, first: dict) -> tuple[int, dict]:
    """
    Page mal lue : elle est peut-être couchée ou à l'envers. On la lit dans les trois autres sens et on
    garde le sens où le modèle lit nettement plus de texte. Retourne (angle, lecture).
    """
    best_angle, best = 0, first
    for angle in (90, 180, 270):
        reading = ocr_reading(gray.rotate(-angle, expand=True))   # Pillow tourne dans le sens inverse des aiguilles
        if reading["weight"] > 1.5 * best["weight"] + 10:
            best_angle, best = angle, reading
    return best_angle, best


# =========================================================================== lecture complète d'une image de page
def read_image(image: Image.Image, page: int, first_word_id: int, find_orientation: bool = True) -> dict:
    """
    Lit une image de page. Retourne :
      {"tokens": [...], "rotation": 0/90/180/270, "skew": degrés}
    """
    prepared = prepare(image)
    gray, skew = _straightened(prepared)
    rotation, first = 0, ocr_reading(gray)
    if find_orientation and is_poor(first):
        rotation, first = best_orientation(prepared, first)
        if rotation:
            gray, skew = _straightened(prepared.rotate(-rotation, expand=True))
            first = ocr_reading(gray)

    readings = [first]
    if is_poor(first):                       # lecture médiocre : une seconde lecture sur l'image nettoyée
        readings.append(ocr_reading(cleaned(gray)))
    best = max(readings, key=lambda r: r["weight"])

    tokens, word_id = [], first_word_id
    for number, reading in enumerate(readings):
        secondary = reading is not best
        for word in reading["words"]:
            if secondary and word["confidence"] < SECONDARY_MIN_CONFIDENCE:
                continue
            tokens += make_tokens(word["text"], confidence=word["confidence"] * 100, page=page, source="ocr",
                                  word_id=word_id, box=word["box"], reading=number, secondary=secondary)
            word_id += 1
    return {"tokens": tokens, "rotation": rotation, "skew": skew}


if __name__ == "__main__":
    if "--install" in sys.argv:
        print("Modèles OCRia-nano installés dans", install_models())
    else:
        print("Modèles OCRia-nano :", "installés" if models_ready() else "absents (python -m engine.ocr --install)")
