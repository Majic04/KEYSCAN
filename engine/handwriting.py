"""
Écriture manuscrite : repérer les lignes écrites à la main sur une page, puis les faire lire par TrOCR.

Pourquoi : Tesseract (l'OCR) est fait pour le texte imprimé. Sur une lettre écrite à la main,
il ne lit presque rien, et un mot-clé manuscrit passerait inaperçu.

Pour chaque page lue par l'OCR :
  1. on trouve les lignes de texte sur l'image (find_text_lines) ;
  2. une ligne est considérée comme manuscrite si Tesseract n'y a pas lu de texte imprimé fiable
     (moins de 60 % de sa largeur couverte par des mots lus à 75 % ou plus) ;
  3. ces lignes seules sont lues par le modèle TrOCR (trocr.py) : les lignes imprimées ne sont pas relues.

Comment on trouve les lignes, sans réseau de neurones (numpy seul) :
  a. masque de l'encre : un pixel est de l'encre s'il est nettement plus sombre que son voisinage
     (marche sur papier jauni, ombres, taches) ; on enlève ensuite le grain du papier, les pointillés
     et les longs traits horizontaux (bords de carte, filets) ;
  b. on compte l'encre ligne de pixels par ligne de pixels : ce « profil » monte sur chaque ligne de texte
     et redescend entre deux lignes ; l'interligne se mesure par autocorrélation ;
  c. chaque ligne de texte est un pic du profil, et deux lignes se séparent au creux entre leurs pics
     (cela marche même quand les jambages d'une ligne touchent la suivante) ;
  d. chaque ligne est enfin coupée en morceaux de 10 à 12 mots au plus (TrOCR lit mieux des morceaux courts).
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from . import trocr
from .text import make_tokens

PRINTED_MIN_CONFIDENCE = 75     # un mot Tesseract lu au moins à ce niveau est du texte imprimé bien lu
PRINTED_MIN_COVERAGE = 0.6      # une ligne couverte à 60 % par de tels mots n'est pas relue
MAX_PIECES_PER_PAGE = 60        # garde-fou
MAX_PIECE_RATIO = 14            # longueur maximale d'un morceau = 14 fois sa hauteur (≈ 10-12 mots)
MIN_TRUSTED_CONFIDENCE = 40     # en dessous, la lecture TrOCR ne compte pas dans la qualité de lecture
HANDWRITING_READING = 90        # numéro de « lecture » des tokens manuscrits (voir text.py, clé "k")


# =========================================================================== a. masque de l'encre
def _window_sum(mask: np.ndarray, radius: int) -> np.ndarray:
    """Pour chaque pixel, le nombre de pixels vrais dans le carré de côté 2×radius+1 qui l'entoure."""
    c = np.pad(mask.astype(np.int32), ((radius + 1, radius), (radius + 1, radius))).cumsum(0).cumsum(1)
    k = 2 * radius + 1
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def _long_horizontal_strokes(ink: np.ndarray, length: int) -> np.ndarray:
    """Pixels qui font partie d'un trait horizontal continu d'au moins `length` pixels."""
    height, width = ink.shape
    if width <= length:
        return np.zeros_like(ink)
    c = np.pad(ink.astype(np.int32), ((0, 0), (1, 0))).cumsum(1)
    full_window = (c[:, length:] - c[:, :-length]) >= int(0.92 * length)   # fenêtre [x, x+length) presque pleine
    f = np.pad(full_window.astype(np.int32), ((0, 0), (1, 0))).cumsum(1)
    x = np.arange(width)
    last_start = np.minimum(x, width - length) + 1
    first_start = np.maximum(0, x - length + 1)
    return (f[:, last_start] - f[:, first_start]) > 0


def ink_mask(gray: Image.Image) -> np.ndarray:
    """Tableau de booléens : True là où il y a de l'encre."""
    smooth = gray.filter(ImageFilter.MedianFilter(3))
    pixels = np.asarray(smooth, dtype=np.int16)
    neighbourhood = np.asarray(smooth.filter(ImageFilter.BoxBlur(25)), dtype=np.int16)
    ink = pixels < neighbourhood - 12
    radius = max(3, gray.size[0] // 600)                       # ≈ 4 pixels à 300 dpi
    ink &= _window_sum(ink, radius) >= 0.2 * (2 * radius + 1) ** 2   # un trait remplit sa fenêtre, pas un grain
    ink &= ~_long_horizontal_strokes(ink, max(40, gray.size[0] // 6))
    return ink


# =========================================================================== b-c. lignes de texte
def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Intervalles [début, fin) où le masque est vrai : [F,T,T,F,T] → [(1, 3), (4, 5)]."""
    edges = np.diff(np.concatenate([[False], mask, [False]]).astype(np.int8))
    return list(zip(np.where(edges == 1)[0], np.where(edges == -1)[0]))


def _line_spacing(profile: np.ndarray) -> float:
    """
    Interligne en pixels, mesuré par autocorrélation : le profil d'encre ressemble à lui-même décalé
    d'un interligne. On prend le pic le plus fort (pas le premier : hampes et jambages créent un faux pic
    à mi-interligne). 0 si le texte n'a pas de régularité.
    """
    centered = profile - profile.mean()
    n = len(centered)
    autocorrelation = np.correlate(centered, centered, mode="full")[n - 1:]
    if autocorrelation[0] <= 0:
        return 0.0
    first, last = max(8, n // 150), max(9, n // 4)
    window = autocorrelation[first:last]
    peaks = [i for i in range(1, len(window) - 1)
             if window[i] >= window[i - 1] and window[i] >= window[i + 1] and window[i] > 0.1 * autocorrelation[0]]
    if not peaks:
        return 0.0
    return float(first + max(peaks, key=lambda i: window[i]))


def _line_bands(profile: np.ndarray) -> list[tuple[int, int]]:
    """Bandes horizontales [haut, bas) des lignes de texte, à partir du profil d'encre."""
    height = len(profile)
    spacing = _line_spacing(profile)
    if spacing < 8:            # pas de régularité : on coupe simplement aux interlignes blancs
        threshold = max(2.0, 0.06 * float(np.percentile(profile[profile > 0], 90)))
        return [(top, bottom) for top, bottom in _runs(profile > threshold) if bottom - top >= 6]

    width = max(3, int(spacing / 3))
    smooth = np.convolve(profile, np.ones(width) / width, mode="same")
    floor = 0.12 * float(smooth.max())
    candidates = [y for y in range(1, height - 1) if smooth[y] >= smooth[y - 1] and smooth[y] > smooth[y + 1] and smooth[y] > floor]
    peaks = []
    for y in sorted(candidates, key=lambda y: -smooth[y]):     # les pics les plus forts d'abord…
        if all(abs(y - other) >= 0.6 * spacing for other in peaks):   # …et pas deux pics dans la même ligne
            peaks.append(y)
    peaks.sort()

    bands = []
    for n, peak in enumerate(peaks):
        if n == 0:
            top = max(0, int(peak - 0.6 * spacing))
        else:
            top = peaks[n - 1] + int(np.argmin(smooth[peaks[n - 1]:peak]))      # creux avec la ligne du dessus
        if n + 1 < len(peaks):
            bottom = peak + int(np.argmin(smooth[peak:peaks[n + 1]]))           # creux avec la ligne du dessous
        else:
            bottom = min(height, int(peak + 0.6 * spacing))
        inked = np.where(profile[top:bottom] > 0.05 * smooth[peak])[0]          # on resserre sur l'encre réelle
        if len(inked):
            top, bottom = top + int(inked[0]), top + int(inked[-1]) + 1
        if bottom - top >= 6:
            bands.append((top, bottom))
    return bands


# =========================================================================== d. morceaux de lignes
def _pieces_of_band(ink: np.ndarray, top: int, bottom: int) -> list[tuple[int, int]]:
    """Coupe une bande en morceaux horizontaux [gauche, droite) : colonnes séparées, morceaux pas trop longs."""
    h = bottom - top
    columns = ink[top:bottom].sum(axis=0) >= 2
    strokes = [(a, b) for a, b in _runs(columns) if b - a >= 2]
    if not strokes:
        return []
    # regroupement des traits : un grand vide (> 1,8 × hauteur) sépare deux colonnes de texte
    groups = [{"left": strokes[0][0], "right": strokes[0][1], "word_gaps": []}]
    for a, b in strokes[1:]:
        gap = a - groups[-1]["right"]
        if gap > 1.8 * h:
            groups.append({"left": a, "right": b, "word_gaps": []})
        else:
            if gap > 0.35 * h:
                groups[-1]["word_gaps"].append((groups[-1]["right"], a))    # espace entre deux mots
            groups[-1]["right"] = b
    pieces = []
    for group in groups:
        start = group["left"]
        for gap_start, gap_end in group["word_gaps"]:       # morceau trop long : coupé à un espace entre mots
            if gap_start - start > MAX_PIECE_RATIO * h:
                pieces.append((start, gap_start))
                start = gap_end
        pieces.append((start, group["right"]))
    return pieces


def find_text_lines(gray: Image.Image) -> list[tuple[int, int, int, int]]:
    """Morceaux de lignes de texte d'une page, en pixels : [(gauche, haut, droite, bas)]."""
    ink = ink_mask(gray)
    height, width = ink.shape
    profile = ink.sum(axis=1).astype(np.float32)
    if not (profile > 0).any():
        return []
    boxes = []
    for top, bottom in _line_bands(profile):
        h = bottom - top
        if h < 8 or h > 0.5 * height:
            continue
        for left, right in _pieces_of_band(ink, top, bottom):
            too_short = right - left < h
            almost_empty = ink[top:bottom, left:right].sum() < 0.02 * h * (right - left)
            if too_short or almost_empty:
                continue
            margin_y, margin_x = int(0.08 * h), int(0.25 * h)
            boxes.append((max(0, left - margin_x), max(0, top - margin_y), min(width, right + margin_x), min(height, bottom + margin_y)))
    return boxes


# =========================================================================== lignes manuscrites
def handwritten_lines(gray: Image.Image, printed_words: list[tuple[list[float], float, str]]) -> list[tuple[int, int, int, int]]:
    """
    Morceaux de lignes que Tesseract n'a pas lus comme du texte imprimé fiable : ce sont les lignes manuscrites.
    printed_words : les mots lus par Tesseract, [(boîte en pixels, confiance, texte)].
    """
    well_read = [box for box, confidence, text in printed_words
                 if confidence >= PRINTED_MIN_CONFIDENCE and (len(text.strip()) >= 2 or confidence >= 90)]
    result = []
    for line in find_text_lines(gray):
        left, top, right, bottom = line
        covered = np.zeros(right - left, dtype=bool)
        for word_left, word_top, word_right, word_bottom in well_read:
            vertical_overlap = min(bottom, word_bottom) - max(top, word_top)
            if vertical_overlap <= 0.4 * min(bottom - top, word_bottom - word_top):
                continue                                       # mot d'une autre ligne
            a, b = int(max(left, word_left)) - left, int(min(right, word_right)) - left
            if b > a:
                covered[a:b] = True
        if covered.mean() < PRINTED_MIN_COVERAGE:
            result.append(line)
        if len(result) >= MAX_PIECES_PER_PAGE:
            break
    return result


def read_handwriting(gray: Image.Image, printed_words, page: int, first_word_id: int) -> tuple[list[dict], list]:
    """
    Repère et lit l'écriture manuscrite d'une page.
    Retourne (tokens des mots lus, boîtes des lignes bien lues). Chaque mot reçoit une position estimée
    au prorata de ses lettres dans la ligne (TrOCR lit la ligne entière, sans position par mot).
    """
    lines = handwritten_lines(gray, printed_words)
    if not lines:
        return [], []
    readings = trocr.read_lines([gray.crop(box) for box in lines])
    width, height = gray.size
    tokens, trusted_lines, word_id = [], [], first_word_id
    for (left, top, right, bottom), (text, confidence) in zip(lines, readings):
        words = text.split()
        letters = sum(len(w) for w in words) + max(0, len(words) - 1)
        if not letters:
            continue
        trusted = confidence >= MIN_TRUSTED_CONFIDENCE
        if trusted:
            trusted_lines.append((left, top, right, bottom))
        position = 0
        for word in words:
            word_left = left + (right - left) * position / letters
            word_right = left + (right - left) * (position + len(word)) / letters
            box = [word_left / width, top / height, word_right / width, bottom / height]
            tokens += make_tokens(word, confidence=confidence, page=page, source="manuscrit", word_id=word_id,
                                  box=[float(v) for v in box], reading=HANDWRITING_READING, secondary=not trusted)
            word_id += 1
            position += len(word) + 1
    return tokens, trusted_lines
