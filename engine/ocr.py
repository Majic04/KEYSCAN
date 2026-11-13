"""
Lecture d'une image par OCR (Tesseract), avec redressement de la page.

Étapes pour une image de page :
  1. préparation : niveaux de gris, agrandissement des petites images ;
  2. orientation : la page est-elle couchée ou à l'envers ? (0, 90, 180 ou 270°) ;
  3. inclinaison fine : une photo légèrement penchée est redressée (jusqu'à ±12°) ;
  4. lecture : Tesseract lit l'image. Si la lecture est médiocre, on recommence avec une image
     nettoyée, puis avec d'autres réglages. La meilleure lecture fait foi, les autres la complètent ;
  5. écriture manuscrite : les lignes que Tesseract n'a pas su lire sont confiées à TrOCR
     (seulement si le module est installé).
"""
from __future__ import annotations

import os
import shutil
import time

import numpy as np
import pytesseract
from PIL import Image, ImageFilter, ImageOps

from .text import make_tokens

LANGUAGES = os.environ.get("KWF_OCR_LANG", "fra+eng")   # français + anglais
MIN_WIDTH = 1800              # une image plus étroite est agrandie (au plus ×3) : Tesseract lit mieux
GOOD_ENOUGH = 88              # confiance moyenne à partir de laquelle une seule lecture suffit
SECONDARY_MIN_CONFIDENCE = 40 # mots des lectures de secours gardés à partir de cette confiance


def find_tesseract() -> str | None:
    """Trouve le programme Tesseract : variable TESSERACT_CMD, sinon PATH, sinon emplacements habituels."""
    candidates = [
        os.environ.get("TESSERACT_CMD"),
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return path
    return None


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


def cleaned(gray: Image.Image, median: int = 3) -> Image.Image:
    """Image nettoyée : contraste étiré, bruit atténué (filtre médian), puis noir et blanc (seuil d'Otsu)."""
    image = ImageOps.autocontrast(gray, cutoff=0.5).filter(ImageFilter.MedianFilter(median))
    threshold = otsu_threshold(np.asarray(image))
    return image.point(lambda v: 255 if v > threshold else 0)


def local_threshold(gray: Image.Image, radius: int = 20, margin: int = 14) -> Image.Image:
    """
    Noir et blanc par seuil local : chaque pixel est comparé à la moyenne de son voisinage.
    Indispensable quand le fond n'est pas uniforme (ombre d'une photo, texte gris collé sur une page blanche).
    """
    smooth = gray.filter(ImageFilter.MedianFilter(3))
    pixels = np.asarray(smooth, dtype=np.int16)
    neighbourhood = np.asarray(smooth.filter(ImageFilter.BoxBlur(radius)), dtype=np.int16)
    return Image.fromarray(np.where(pixels < neighbourhood - margin, 0, 255).astype(np.uint8))


# =========================================================================== 2-3. orientation et inclinaison
def _confident_text_amount(gray: Image.Image) -> float:
    """Nombre de lettres lues avec assurance : sert à comparer deux sens de lecture."""
    small = gray.copy()
    small.thumbnail((1400, 1400))
    data = pytesseract.image_to_data(small, lang=LANGUAGES, config="--oem 1 --psm 3", output_type=pytesseract.Output.DICT)
    return float(sum(len(word.strip()) for word, confidence in zip(data["text"], data["conf"])
                     if float(confidence) >= 70 and len(word.strip()) >= 3 and any(ch.isalpha() for ch in word)))


def detect_rotation(gray: Image.Image) -> int:
    """
    Angle (0, 90, 180 ou 270) à appliquer pour remettre le texte droit.
    Tesseract propose un angle ; comme il se trompe souvent sur l'écriture manuscrite, on n'accepte de
    tourner la page que si l'OCR y lit nettement plus de texte une fois tournée.
    """
    for candidate in (gray, cleaned(gray)):
        try:
            guess = pytesseract.image_to_osd(candidate, output_type=pytesseract.Output.DICT)
        except pytesseract.TesseractError:
            continue                               # pas assez de texte pour se prononcer
        angle = int(guess.get("rotate", 0)) % 360
        if float(guess.get("orientation_conf", 0)) < 1.5:
            continue
        if angle == 0:
            return 0
        try:
            before = _confident_text_amount(gray)
            after = _confident_text_amount(gray.rotate(-angle, expand=True))
        except pytesseract.TesseractError:
            return 0
        return angle if after > 1.5 * before + 10 else 0
    return 0


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


# =========================================================================== 4. lecture par Tesseract
def _tesseract_reading(image: Image.Image, page_mode: int = 3) -> dict:
    """
    Une lecture de l'image. page_mode 3 = mise en page automatique, 6 = un seul bloc de texte.
    Retourne les mots lus, leur confiance moyenne et un « poids » (confiance × longueur) pour comparer les lectures.
    """
    data = pytesseract.image_to_data(image, lang=LANGUAGES, config=f"--oem 1 --psm {page_mode}",
                                     output_type=pytesseract.Output.DICT)
    words = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        confidence = float(data["conf"][i])
        if text and confidence >= 0:
            left, top, width, height = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            words.append({"text": text, "confidence": confidence, "box": [left, top, left + width, top + height]})
    weight = sum(w["confidence"] * len(w["text"]) for w in words)
    mean = sum(w["confidence"] for w in words) / len(words) if words else 0.0
    return {"words": words, "weight": weight, "mean": mean}


def _all_readings(gray: Image.Image) -> list[dict]:
    """Lectures successives, de la plus rapide à la plus robuste, tant que la lecture reste médiocre."""
    readings = [_tesseract_reading(gray)]                                   # image telle quelle

    def still_poor(threshold):
        best = max(readings, key=lambda r: r["weight"])
        return best["mean"] < threshold or len(best["words"]) < 3

    if still_poor(GOOD_ENOUGH):
        clean = cleaned(gray)
        readings.append(_tesseract_reading(clean))                          # contraste, bruit, noir et blanc
        if still_poor(80):
            readings.append(_tesseract_reading(local_threshold(gray)))      # fond non uniforme
        if still_poor(80):
            readings.append(_tesseract_reading(clean, page_mode=6))         # un seul bloc de texte
            readings.append(_tesseract_reading(cleaned(gray, median=5), page_mode=6))   # bruit fort
    return readings


# =========================================================================== lecture complète d'une image de page
_handwriting_check = {"time": 0.0, "available": False}


def handwriting_available() -> bool:
    """Le module d'écriture manuscrite est-il installé ? (vérifié au plus une fois par minute)"""
    if time.time() - _handwriting_check["time"] > 60:
        try:
            from . import trocr
            _handwriting_check["available"] = trocr.available()
        except Exception:  # noqa: BLE001
            _handwriting_check["available"] = False
        _handwriting_check["time"] = time.time()
    return _handwriting_check["available"]


def read_image(image: Image.Image, page: int, first_word_id: int, find_orientation: bool = True) -> dict:
    """
    Lit une image de page. Retourne :
      {"tokens": [...], "rotation": 0/90/180/270, "skew": degrés, "handwritten_lines": nombre}
    """
    gray = prepare(image)
    rotation = detect_rotation(gray) if find_orientation else 0
    if rotation:
        gray = gray.rotate(-rotation, expand=True)        # Pillow tourne dans le sens inverse des aiguilles d'une montre
    skew = estimate_skew(gray)
    if skew:
        gray = gray.rotate(skew, expand=True, fillcolor=255, resample=Image.BICUBIC)
    width, height = gray.size

    readings = _all_readings(gray)
    best = max(readings, key=lambda r: r["weight"])
    tokens, word_id = [], first_word_id
    for number, reading in enumerate(readings):
        secondary = reading is not best
        for word in reading["words"]:
            if secondary and word["confidence"] < SECONDARY_MIN_CONFIDENCE:
                continue
            left, top, right, bottom = word["box"]
            box = [left / width, top / height, right / width, bottom / height]
            tokens += make_tokens(word["text"], confidence=word["confidence"], page=page, source="ocr",
                                  word_id=word_id, box=box, reading=number, secondary=secondary)
            word_id += 1

    handwritten = 0
    if handwriting_available():
        handwritten = _add_handwriting(gray, best, page, word_id, tokens)
    return {"tokens": tokens, "rotation": rotation, "skew": skew, "handwritten_lines": handwritten}


def _add_handwriting(gray: Image.Image, best: dict, page: int, first_word_id: int, tokens: list[dict]) -> int:
    """Ajoute aux tokens les mots manuscrits lus par TrOCR. Retourne le nombre de lignes manuscrites bien lues."""
    from .handwriting import read_handwriting
    printed_words = [(w["box"], w["confidence"], w["text"]) for w in best["words"]]
    try:
        handwritten_tokens, lines = read_handwriting(gray, printed_words, page, first_word_id)
    except Exception as error:  # noqa: BLE001 — le module manuscrit ne doit jamais bloquer l'analyse
        print(f"[manuscrit] lecture impossible : {error}")
        return 0
    # dans les lignes manuscrites, la lecture ratée de Tesseract ne compte plus dans la qualité de lecture
    width, height = gray.size
    for token in tokens:
        center_x = (token["b"][0] + token["b"][2]) / 2 * width
        center_y = (token["b"][1] + token["b"][3]) / 2 * height
        if any(left <= center_x <= right and top <= center_y <= bottom for left, top, right, bottom in lines):
            token["x"] = 1
    tokens += handwritten_tokens
    return len(lines)
