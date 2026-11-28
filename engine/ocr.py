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
     complète la première ;
  6. couverture : part de l'encre de la page qui se trouve dans un mot lu. Le modèle ne lit que les lignes
     horizontales : un mot vertical, en biais ou à l'envers (affiche, schéma, tampon, nuage de mots)
     reste hors des mots lus. Si la couverture est faible, la page est relue tournée dans d'autres sens
     (EXTRA_ANGLES) ; chaque mot trouvé ainsi est replacé sur la page d'origine.
     Quand un même endroit a été lu dans plusieurs sens, on garde la lecture la plus sûre.
     Les « mots » lus à l'envers (« npuə] » pour « tendu ») sont écartés : leurs lettres ne sont pas
     celles du français ou de l'anglais.

Les modèles (environ 70 Mo, avec ONNX Runtime) s'installent une fois : python -m engine.ocr --install
L'application de bureau les embarque (variable LITEPARSE_MODEL_DIR).
"""
from __future__ import annotations

import math
import os
import re
import sys
import tempfile
import threading
import unicodedata

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .text import make_tokens

MODEL = "ocria-nano"
MIN_WIDTH = 1800              # une image plus étroite est agrandie (au plus ×3) : le modèle lit mieux
GOOD_ENOUGH = 0.85            # confiance moyenne (0 à 1) à partir de laquelle une seule lecture suffit
SECONDARY_MIN_CONFIDENCE = 0.4  # mots de la lecture de secours gardés à partir de cette confiance
WELL_COVERED = 0.85           # couverture (0 à 1) à partir de laquelle la page est lue dans un seul sens
# sens supplémentaires (degrés, sens des aiguilles d'une montre), du plus utile au moins utile (banc d'essai) ;
# 55°, 145°, 235° et 325° : un mot en diagonale collé à un autre était lu coupé (« modè ») sous un seul angle,
# un angle voisin le lit en entier (banc du zip : 70,3 % -> 72,6 % des mots) ; ±10° de plus n'apportait presque rien
EXTRA_ANGLES = (90, 270, 180, 315, 45, 135, 225, 55, 145, 235, 325)
EXTRA_SCALE = 0.6             # les autres sens sont lus sur l'image réduite : autant de mots trouvés, plus vite

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


# =========================================================================== 6. mots plausibles
def plausible(text: str) -> bool:
    """
    Un mot lu dans le mauvais sens donne des lettres d'autres alphabets : « npuə] » (tendu à l'envers),
    « дqƏp » (débit), « sƏtбəue » (énergies). Un mot plausible n'a que des lettres latines courantes
    (de A à Z, avec les accents du français et des langues voisines).
    """
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and all(ord(ch) <= 0x17F for ch in letters)     # Latin de base, Latin-1, Latin étendu A


# =========================================================================== 7. couverture de la page
def coverage(gray: Image.Image, boxes: list[list[float]]) -> float:
    """
    Part de l'encre de la page (0 à 1) qui se trouve dans un mot lu. Les grandes zones pleines (photo, logo,
    aplat de couleur) ne comptent pas : ce n'est pas du texte. Une page sans encre est entièrement couverte.
    """
    small = gray.copy()
    small.thumbnail((800, 800))
    pixels = np.asarray(small)
    ink = pixels < min(otsu_threshold(pixels), 200)
    height, width = ink.shape
    tile = 16                                       # zones pleines : plus de 45 % d'encre sur un carré de 16 pixels,
    rows, cols = -(-height // tile), -(-width // tile)          # et leurs voisins (le bord d'une photo)
    dense = np.zeros((rows, cols), dtype=bool)
    for row in range(rows):
        for col in range(cols):
            dense[row, col] = ink[row * tile:(row + 1) * tile, col * tile:(col + 1) * tile].mean() > 0.45
    for row, col in zip(*np.nonzero(dense)):
        ink[max(0, row - 1) * tile:(row + 2) * tile, max(0, col - 1) * tile:(col + 2) * tile] = False
    total = ink.sum()
    if total < 0.002 * ink.size:
        return 1.0
    read = np.zeros_like(ink)
    margin = 0.004                                  # un mot lu couvre aussi le bord de ses lettres
    for left, top, right, bottom in boxes:
        x0, y0 = max(0, int((left - margin) * width)), max(0, int((top - margin) * height))
        x1, y1 = min(width, int(math.ceil((right + margin) * width))), min(height, int(math.ceil((bottom + margin) * height)))
        read[y0:y1, x0:x1] = True
    return round(float((ink & read).sum() / total), 3)


# =========================================================================== 8. lecture dans d'autres sens
def _rotated(gray: Image.Image, angle: float) -> Image.Image:
    """L'image tournée de « angle » degrés dans le sens des aiguilles d'une montre (agrandie pour tout garder)."""
    return gray.rotate(-angle, expand=True, fillcolor=255, resample=Image.BICUBIC)


def back_to_page(box: list[float], angle: float, page_size: tuple[int, int], rotated_size: tuple[int, int]) -> list[float]:
    """
    Une boîte lue sur l'image tournée (fractions de l'image tournée) ramenée sur la page d'origine
    (fractions de la page). On défait la rotation pour ses quatre coins, puis on garde le rectangle qui
    les contient : un mot en biais est encadré par un rectangle droit.
    """
    width, height = page_size
    rotated_width, rotated_height = rotated_size
    radians = math.radians(angle)
    cos, sin = math.cos(radians), math.sin(radians)
    xs, ys = [], []
    for fx, fy in ((box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])):
        dx, dy = fx * rotated_width - rotated_width / 2, fy * rotated_height - rotated_height / 2
        # l'image a tourné dans le sens des aiguilles d'une montre : on tourne le point dans l'autre sens
        xs.append((dx * cos + dy * sin + width / 2) / width)
        ys.append((-dx * sin + dy * cos + height / 2) / height)
    clip = lambda v: min(1.0, max(0.0, v))
    return [clip(min(xs)), clip(min(ys)), clip(max(xs)), clip(max(ys))]


def rotated_reading(gray: Image.Image, angle: float) -> dict:
    """Une lecture de la page tournée de « angle » degrés ; les boîtes des mots sont ramenées sur la page."""
    turned = _rotated(gray, angle)
    reading = ocr_reading(turned)
    for word in reading["words"]:
        word["box"] = back_to_page(word["box"], angle, gray.size, turned.size)
    return reading


def _overlap(a: list[float], b: list[float]) -> float:
    """Recouvrement de deux boîtes (intersection / union), de 0 à 1."""
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    shared = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - shared
    return shared / union if union > 0 else 0.0


def keep_best_reading(readings: list[dict]) -> None:
    """
    Un même endroit lu dans plusieurs sens : on garde le mot le plus sûr (confiance × nombre de lettres),
    et on retire les autres de leur lecture. Les mots de la première lecture passent d'abord à égalité.
    """
    words = [(word["confidence"] * len([c for c in word["text"] if c.isalnum()]), -number, number, word)
             for number, reading in enumerate(readings) for word in reading["words"]]
    words.sort(key=lambda w: (w[0], w[1]), reverse=True)
    kept = []
    for _, _, number, word in words:
        if any(_overlap(word["box"], other["box"]) > 0.3 for other in kept):
            word["dropped"] = True
        else:
            kept.append(word)
    for reading in readings:
        reading["words"] = [w for w in reading["words"] if not w.pop("dropped", False)]


# =========================================================================== lecture complète d'une image de page
def read_image(image: Image.Image, page: int, first_word_id: int, find_orientation: bool = True) -> dict:
    """
    Lit une image de page. Retourne :
      {"tokens": [...], "rotation": 0/90/180/270, "skew": degrés, "coverage": 0-1, "angles": sens lus en plus}
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
    for reading in readings:                 # les mots lus à l'envers ne sont pas des mots
        reading["words"] = [w for w in reading["words"] if plausible(w["text"])]
    best = max(readings, key=lambda r: r["weight"])

    # mots en biais, verticaux ou à l'envers : la page est relue dans d'autres sens si elle est mal couverte
    boxes = [w["box"] for r in readings for w in r["words"]]
    page_coverage = coverage(gray, boxes)
    angles = []
    if find_orientation and page_coverage < WELL_COVERED:
        # (effacer les mots déjà lus avant de relire abîmait leurs voisins : moins de mots trouvés sur le banc)
        smaller = gray.resize((int(gray.width * EXTRA_SCALE), int(gray.height * EXTRA_SCALE)), Image.LANCZOS)
        for angle in EXTRA_ANGLES:
            extra = rotated_reading(smaller, angle)
            extra["words"] = [w for w in extra["words"]
                              if plausible(w["text"]) and w["confidence"] >= SECONDARY_MIN_CONFIDENCE]
            if extra["words"]:
                readings.append(extra)
                angles.append(angle)
        keep_best_reading(readings)
        page_coverage = coverage(gray, [w["box"] for r in readings for w in r["words"]])

    tokens, word_id = [], first_word_id
    for number, reading in enumerate(readings):
        # la lecture de secours (image nettoyée) ne compte pas dans la qualité ; les autres sens, si
        secondary = reading is not best and number < len(readings) - len(angles)
        for word in reading["words"]:
            if secondary and word["confidence"] < SECONDARY_MIN_CONFIDENCE:
                continue
            tokens += make_tokens(word["text"], confidence=word["confidence"] * 100, page=page, source="ocr",
                                  word_id=word_id, box=word["box"], reading=number, secondary=secondary)
            word_id += 1
    return {"tokens": tokens, "rotation": rotation, "skew": skew, "coverage": page_coverage, "angles": angles}


if __name__ == "__main__":
    if "--install" in sys.argv:
        print("Modèles OCRia-nano installés dans", install_models())
    else:
        print("Modèles OCRia-nano :", "installés" if models_ready() else "absents (python -m engine.ocr --install)")
