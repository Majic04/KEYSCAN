"""
L'image d'une page, avec les occurrences surlignées : vert = sûr, jaune = à vérifier
(les mêmes couleurs que les surligneurs de l'interface).

La page est tournée et redressée exactement comme pendant la lecture, pour que les cadres tombent juste.
On peut aussi zoomer sur une zone (« crop ») pour montrer précisément où est le mot, avec sa ligne et ses voisines.
Les 120 dernières images sont gardées en mémoire.
"""
from __future__ import annotations

import io
import os
import threading

try:
    import pymupdf as fitz            # PyMuPDF ≥ 1.24.3
except ImportError:                   # anciennes versions
    import fitz
from PIL import Image, ImageDraw, ImageFont, ImageOps

from engine.extract import IMAGE_EXTENSIONS

from .analysis import occurrences
from .results import is_sure

SURE_COLORS = ((90, 210, 150, 95), (20, 110, 70, 255))       # (remplissage, bord) : vert
CHECK_COLORS = ((255, 214, 40, 110), (150, 110, 0, 255))     # jaune
LABEL_TEXT_COLOR = (28, 43, 63)
MEMORY_SIZE = 120

_memory: dict[tuple, bytes] = {}
_memory_lock = threading.Lock()


def page_png(document: dict, page: int, terms: list[str], present_threshold: float, crop: list[float] | None) -> bytes:
    """
    document : {"id", "path", "status", "pages" (liste), "analysed_at"}
    terms    : mots-clés à surligner (avec plusieurs mots-clés, leur nom est écrit au-dessus du cadre)
    crop     : zone à agrandir [x0, y0, x1, y1] en fractions de la page (0 à 1), ou None
    """
    key = (document["id"], page, tuple(terms), document["analysed_at"], present_threshold, tuple(crop or ()))
    with _memory_lock:
        if key in _memory:
            return _memory[key]

    pages = document["pages"]
    info = pages[page - 1] if 0 < page <= len(pages) else {}
    image = _straightened_page(document["path"], page, info.get("rot", 0), info.get("skew", 0), sharp=bool(crop))
    if not crop and max(image.size) > 1600:
        image.thumbnail((1600, 1600))
    if terms and document["status"] == "ok":
        _highlight(image, document["id"], page, terms, present_threshold)
    if crop:
        image = _zoom(image, crop)

    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=False, compress_level=3)
    data = buffer.getvalue()
    with _memory_lock:
        _memory[key] = data
        while len(_memory) > MEMORY_SIZE:
            del _memory[next(iter(_memory))]          # on oublie la plus ancienne
    return data


def _straightened_page(path: str, page: int, rotation: int, skew: float, sharp: bool) -> Image.Image:
    if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS:
        with Image.open(path) as picture:
            if getattr(picture, "n_frames", 1) > 1:
                picture.seek(page - 1)                # TIFF de plusieurs pages
            image = ImageOps.exif_transpose(picture.copy()).convert("RGB")
    else:
        with fitz.open(path) as pdf:
            pixels = pdf[page - 1].get_pixmap(dpi=200 if sharp else 110)
            image = Image.frombytes("RGB", (pixels.width, pixels.height), pixels.samples)
    if rotation:
        image = image.rotate(-rotation, expand=True)
    if skew:
        image = image.rotate(skew, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)
    return image


def _highlight(image: Image.Image, document_id: int, page: int, terms: list[str], present_threshold: float):
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    line_width = max(2, max(3, width // 500) - 1)
    try:
        font = ImageFont.load_default(size=max(14, width // 70))
    except TypeError:                                 # Pillow < 10.1
        font = ImageFont.load_default()
    for term in terms:
        for occurrence in occurrences(document_id, term):
            if occurrence["page"] != page:
                continue
            x0, y0, x1, y1 = occurrence["box"]
            box = [x0 * width - 4, y0 * height - 3, x1 * width + 4, y1 * height + 3]
            fill, edge = SURE_COLORS if is_sure(occurrence, present_threshold) else CHECK_COLORS
            draw.rectangle(box, fill=fill, outline=edge, width=line_width)
            if len(terms) > 1:                        # vue d'ensemble : le nom du mot-clé au-dessus du cadre
                label_height = (font.size + 6) if hasattr(font, "size") else 16
                top = box[1] - label_height - 2 if box[1] - label_height - 2 > 0 else box[3] + 2
                draw.rectangle([box[0], top, box[0] + draw.textlength(term, font=font) + 12, top + label_height],
                               fill=fill[:3] + (240,))
                draw.text((box[0] + 6, top + 2), term, fill=LABEL_TEXT_COLOR, font=font)


def _zoom(image: Image.Image, crop: list[float]) -> Image.Image:
    """La zone demandée, plus un peu de contexte : un quart de page de chaque côté, deux lignes au-dessus et en dessous."""
    width, height = image.size
    x0, y0, x1, y1 = crop
    word_height = max(y1 - y0, 0.01)
    left, right = max(0.0, x0 - 0.25), min(1.0, x1 + 0.25)
    top, bottom = max(0.0, y0 - 2.2 * word_height), min(1.0, y1 + 2.2 * word_height)
    image = image.crop((int(left * width), int(top * height), int(right * width), int(bottom * height)))
    if image.width > 1400:
        image.thumbnail((1400, 1400))
    return image
