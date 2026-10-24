"""
Lecture complète d'un document (PDF ou image) : tous ses mots, page par page.

Pour chaque page d'un PDF :
  1. on lit le texte contenu dans le PDF lui-même (rapide et sans erreur) ;
  2. on vérifie que ce texte est vraisemblable : certains PDF contiennent un texte copiable illisible
     (« DSSUHQWLVVDJH » au lieu de « apprentissage ») ; il est alors ignoré ;
  3. si la page contient des images, ou presque pas de texte utilisable, elle est transformée en image
     et lue par l'OCR (ocr.py). C'est le cas des scans et des photos collées dans un PDF.
Une image (JPEG, PNG, TIFF…) est toujours lue par l'OCR.

Résultat : {"tokens": [...], "pages": [...], "quality": 0-100} (voir read_document).
"""
from __future__ import annotations

import os
import re
import unicodedata

try:
    import pymupdf as fitz            # PyMuPDF ≥ 1.24.3
except ImportError:                   # anciennes versions
    import fitz
from PIL import Image

from .ocr import read_image
from .text import make_tokens, next_word_id, normalize

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS
OCR_RESOLUTION = 300          # points par pouce pour transformer une page PDF en image
MIN_TEXT_CHARACTERS = 30      # en dessous, la page est considérée comme scannée


# =========================================================================== le texte du PDF est-il lisible ?
_COMMON_WORDS = set("""le la les de des du un une et en au aux a pour par sur avec dans est sont il elle ce cette ses son sa
qui que ne pas plus ou nous je mon ma mes the and of to in for on with is are was were by an at as from this that these
be it my we our have has all or not will can i""".split())


def text_looks_valid(words: list[str]) -> bool:
    """
    Un texte normal contient surtout des mots prononçables (avec des voyelles) et quelques mots courants
    (« le », « de », « the »…). Un texte corrompu contient des caractères de contrôle, ou des suites
    de lettres sans voyelles ni mots courants.
    """
    text = " ".join(words)
    if not text.strip():
        return True
    control_characters = sum(1 for ch in text if unicodedata.category(ch) in ("Cc", "Co", "Cn") or ch == "�")
    if control_characters / len(text) > 0.01:
        return False
    letters_only = [normalize(w) for w in re.findall(r"[^\W\d_]{2,}", text)]
    if not letters_only:
        return True
    with_vowel = sum(1 for w in letters_only if re.search(r"[aeiouy]", w)) / len(letters_only)
    common = sum(1 for w in letters_only if w in _COMMON_WORDS)
    if len(letters_only) >= 12 and common == 0 and with_vowel < 0.9:
        return False
    return with_vowel >= 0.7


def _pdf_text_tokens(page, page_number: int, first_word_id: int) -> tuple[list[dict], bool]:
    """Tokens du texte contenu dans une page de PDF, et si ce texte est lisible."""
    width, height = page.rect.width, page.rect.height
    words = page.get_text("words", sort=True)            # [(gauche, haut, droite, bas, mot, …)]
    valid = text_looks_valid([w[4] for w in words])
    tokens, word_id = [], first_word_id
    for left, top, right, bottom, word, *_ in words:
        box = [left / width, top / height, right / width, bottom / height]
        # texte illisible : gardé pour mémoire, mais avec une confiance très basse et hors qualité de lecture
        tokens += make_tokens(word, confidence=100.0 if valid else 20.0, page=page_number, source="texte",
                              word_id=word_id, box=box, secondary=not valid)
        word_id += 1
    return tokens, valid


# =========================================================================== un document entier
def page_count(path: str) -> int:
    """Nombre de pages d'un fichier (1 pour une image simple, 0 si le fichier est illisible)."""
    try:
        if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS:
            with Image.open(path) as image:
                return getattr(image, "n_frames", 1)
        with fitz.open(path) as document:
            return document.page_count
    except Exception:  # noqa: BLE001 — l'erreur sera signalée au moment de la lecture
        return 0


def read_document(path: str, progress=None) -> dict:
    """
    Lit tous les mots d'un fichier.
    progress(pages_lues, pages_totales) est appelé après chaque page (suivi des gros documents).
    Retourne :
      {"tokens": [...],                       (voir text.py)
       "pages":  [{"mode": "texte" | "ocr" | "mixte", "rot": 0, "skew": 0.0, "manuscrit": 0}, …],
       "quality": 0-100}                      (voir reading_quality)
    """
    extension = os.path.splitext(path)[1].lower()
    if extension in IMAGE_EXTENSIONS:
        tokens, pages = _read_image_file(path, progress)
    elif extension in PDF_EXTENSIONS:
        tokens, pages = _read_pdf(path, progress)
    else:
        raise ValueError(f"Format non pris en charge : {extension}")
    return {"tokens": tokens, "pages": pages, "quality": reading_quality(tokens)}


def _read_image_file(path: str, progress) -> tuple[list[dict], list[dict]]:
    tokens, pages = [], []
    with Image.open(path) as image:
        frames = getattr(image, "n_frames", 1)           # un TIFF peut contenir plusieurs pages
        if progress:
            progress(0, frames)
        for frame in range(frames):
            image.seek(frame)
            result = read_image(image.copy(), frame + 1, next_word_id(tokens))
            tokens += result["tokens"]
            pages.append({"mode": "ocr", "rot": result["rotation"], "skew": result["skew"],
                          "manuscrit": result["handwritten_lines"]})
            if progress:
                progress(frame + 1, frames)
    return tokens, pages


def _read_pdf(path: str, progress) -> tuple[list[dict], list[dict]]:
    tokens, pages = [], []
    with fitz.open(path) as document:
        if progress:
            progress(0, document.page_count)
        for index, page in enumerate(document):
            number = index + 1
            text_tokens, text_valid = _pdf_text_tokens(page, number, next_word_id(tokens))
            tokens += text_tokens
            text_characters = len(page.get_text().strip()) if text_valid else 0
            has_images = bool(page.get_images(full=True))
            info = {"mode": "texte", "rot": 0, "skew": 0.0, "text_layer": "ok" if text_valid else "corrompue", "manuscrit": 0}
            if has_images or text_characters < MIN_TEXT_CHARACTERS:
                scanned = text_characters < MIN_TEXT_CHARACTERS
                pixmap = page.get_pixmap(dpi=OCR_RESOLUTION)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                # l'orientation n'est cherchée que pour une page sans texte utilisable (un vrai scan)
                result = read_image(image, number, next_word_id(tokens), find_orientation=scanned)
                tokens += result["tokens"]
                info.update(mode="ocr" if scanned else "mixte", rot=result["rotation"], skew=result["skew"],
                            manuscrit=result["handwritten_lines"])
            pages.append(info)
            if progress:
                progress(number, document.page_count)
    return tokens, pages


def reading_quality(tokens: list[dict]) -> float:
    """
    Qualité de lecture d'un document, de 0 à 100 : confiance moyenne des mots de la lecture principale,
    les mots longs comptant davantage. Elle dit si l'on peut affirmer qu'un mot est absent :
    sur un document mal lu, ne pas trouver un mot ne prouve rien.
    """
    main = [t for t in tokens if not t.get("x")]
    total_letters = sum(len(t["n"]) for t in main)
    if not total_letters:
        return 0.0
    return round(sum(t["c"] * len(t["n"]) for t in main) / total_letters, 1)
