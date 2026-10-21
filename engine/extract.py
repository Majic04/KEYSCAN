"""
Extraction du texte d'un document (PDF ou image), mot par mot.

Chaque mot extrait devient un « token » :
    {
      "t": mot brut tel que lu (avec ponctuation),
      "r": partie du mot correspondant au token, casse et accents d'origine ("Réseaux"),
      "n": forme normalisée (minuscules, sans accents : "reseaux"),
      "c": confiance de lecture 0-100 (100 pour une couche texte PDF saine),
      "p": numéro de page (à partir de 1),
      "s": source -> "texte" (couche texte du PDF), "ocr" (Tesseract) ou "manuscrit" (TrOCR),
      "w": identifiant du mot brut (un mot brut peut donner plusieurs tokens),
      "b": boîte englobante [x0, y0, x1, y1] en fractions de la page (0..1),
      "k": numéro de la lecture OCR (plusieurs lectures possibles d'une même page),
      "x": 1 si le token vient d'une lecture secondaire (exclu du calcul de qualité)
    }

Stratégie par page :
  1. lecture de la couche texte native du PDF, puis contrôle de sa vraisemblance
     (une police sans table Unicode donne un texte copiable illisible : « DSSUHQWLVVDJH ») ;
  2. si la page contient des images, presque pas de texte, ou une couche texte suspecte,
     elle est rendue en image et lue par OCR (Tesseract) :
       - orientation automatique (0/90/180/270°) puis redressement fin (±12°) ;
       - plusieurs lectures (image brute, image nettoyée et binarisée, seuillage local, autre mode de segmentation)
         tant que la lecture reste médiocre ; la meilleure fait foi, les autres complètent.
Les doublons entre lectures sont éliminés au moment de la recherche.
"""
from __future__ import annotations

import os
import re
import shutil
import unicodedata

import numpy as np
try:
    import pymupdf as fitz  # PyMuPDF ≥ 1.24.3
except ImportError:  # anciennes versions de PyMuPDF
    import fitz
import pytesseract
from PIL import Image, ImageFilter, ImageOps

OCR_LANG = os.environ.get("KWF_OCR_LANG", "fra+eng")
OCR_DPI = 300
MIN_NATIVE_CHARS = 30      # en dessous, la page est considérée comme scannée
TARGET_WIDTH = 1800        # largeur minimale de l'image envoyée à l'OCR (agrandissement des petites images)
GOOD_READ = 88             # confiance moyenne au-delà de laquelle une seule lecture suffit
SECONDARY_MIN_CONF = 40    # mots des lectures secondaires conservés à partir de cette confiance

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
PDF_EXT = {".pdf"}
ALLOWED_EXT = IMAGE_EXT | PDF_EXT


def configure_tesseract() -> str | None:
    """Trouve l'exécutable Tesseract (variable TESSERACT_CMD, PATH, ou chemins Windows/Mac usuels)."""
    candidates = [
        os.environ.get("TESSERACT_CMD"),
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            pytesseract.pytesseract.tesseract_cmd = c
            return c
    return None


# =========================================================================== normalisation
# un token = suite de lettres/chiffres, suivie éventuellement de « ++ » ou « # » (C++, C#, F#)
_RAW_WORD_RE = re.compile(r"[^\W_]+(?:\+\+|#)?")
_NORM_RE = re.compile(r"[a-z0-9]+(?:\+\+|#)?")


def normalize(s: str) -> str:
    """minuscules + suppression des accents + ligatures (é->e, œ->oe, ﬁ->fi)."""
    s = s.lower().replace("œ", "oe").replace("æ", "ae")
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def split_raw(text: str) -> list[tuple[str, str]]:
    """Découpe en (partie brute, forme normalisée) : 'Sous-Traitance,' -> [('Sous','sous'), ('Traitance','traitance')]."""
    out = []
    for m in _RAW_WORD_RE.finditer(text):
        raw = m.group(0)
        for n in _NORM_RE.findall(normalize(raw)):
            out.append((raw, n))
    return out


def split_tokens(text: str) -> list[str]:
    return [n for _, n in split_raw(text)]


# =========================================================================== contrôle de la couche texte
_STOPWORDS = set("""le la les de des du un une et en au aux a pour par sur avec dans est sont il elle ce cette ses son sa
qui que ne pas plus ou nous je mon ma mes the and of to in for on with is are was were by an at as from this that these
be it my we our have has all or not will can i""".split())


def text_layer_is_plausible(raw_words: list[str]) -> bool:
    """
    Une couche texte saine contient surtout des mots « prononçables » et quelques mots-outils.
    Une couche corrompue (police sans table Unicode) contient des caractères de contrôle et
    des suites de lettres sans voyelles ni mots-outils.
    """
    text = " ".join(raw_words)
    if not text.strip():
        return True
    ctrl = sum(1 for ch in text if unicodedata.category(ch) in ("Cc", "Co", "Cn") or ch == "\ufffd")
    if ctrl / len(text) > 0.01:
        return False
    words = [normalize(w) for w in re.findall(r"[^\W\d_]{2,}", text)]
    if not words:
        return True
    vowel_ok = sum(1 for w in words if re.search(r"[aeiouy]", w)) / len(words)
    stop_hits = sum(1 for w in words if w in _STOPWORDS)
    if len(words) >= 12 and stop_hits == 0 and vowel_ok < 0.9:
        return False
    return vowel_ok >= 0.7


# =========================================================================== OCR : préparation de l'image
def _otsu(a: np.ndarray) -> int:
    hist = np.bincount(a.ravel(), minlength=256).astype(float)
    w = np.cumsum(hist); m = np.cumsum(hist * np.arange(256))
    total, mt = w[-1], m[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        var = (mt * w / total - m) ** 2 / (w * (total - w))
    var[~np.isfinite(var)] = 0
    return int(np.argmax(var))


def _prepare(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("L")
    if img.width < TARGET_WIDTH:  # petites images : on agrandit (au plus ×3) pour aider Tesseract
        f = min(3.0, TARGET_WIDTH / img.width)
        img = img.resize((int(img.width * f), int(img.height * f)), Image.LANCZOS)
    return img


def _clean(img: Image.Image, median: int = 3) -> Image.Image:
    """Image nettoyée : étirement du contraste, filtre médian anti-bruit, seuillage d'Otsu (noir/blanc)."""
    img = ImageOps.autocontrast(img, cutoff=0.5).filter(ImageFilter.MedianFilter(median))
    t = _otsu(np.asarray(img))
    return img.point(lambda v: 255 if v > t else 0)


def _adaptive(img: Image.Image, radius: int = 20, k: int = 14) -> Image.Image:
    """
    Seuillage local : chaque pixel est comparé à la moyenne de son voisinage.
    Indispensable quand le fond n'est pas uniforme (texte gris sur fond gris collé sur une page blanche,
    ombre d'une photo) : un seuil global confond alors le texte et le fond.
    """
    m = img.filter(ImageFilter.MedianFilter(3))
    a = np.asarray(m, dtype=np.int16)
    local = np.asarray(m.filter(ImageFilter.BoxBlur(radius)), dtype=np.int16)
    return Image.fromarray(np.where(a < local - k, 0, 255).astype(np.uint8))


def _detect_rotation(img: Image.Image) -> int:
    """Angle (0/90/180/270) à appliquer pour remettre le texte droit, via l'OSD de Tesseract."""
    for candidate in (img, _clean(img)):
        try:
            osd = pytesseract.image_to_osd(candidate, output_type=pytesseract.Output.DICT)
            if float(osd.get("orientation_conf", 0)) >= 1.5:
                return int(osd.get("rotate", 0)) % 360
        except pytesseract.TesseractError:
            continue  # pas assez de texte pour décider
    return 0


def _estimate_skew(img: Image.Image, max_angle: float = 12.0) -> float:
    """
    Inclinaison fine du texte (en degrés) par la méthode des profils de projection :
    quand les lignes sont horizontales, la somme des pixels noirs par ligne alterne
    franchement entre lignes de texte et interlignes (profil très « contrasté »).
    """
    small = img.copy()
    small.thumbnail((1000, 1000))
    a = np.asarray(small)
    bw = (a < _otsu(a)).astype(np.uint8) * 255
    if bw.mean() < 0.5 or bw.mean() > 128:  # page vide ou image pleine
        return 0.0
    src = Image.fromarray(bw)

    def sharpness(angle):
        prof = np.asarray(src.rotate(angle, resample=Image.NEAREST), dtype=np.float32).sum(axis=1)
        return float(np.sum(np.diff(prof) ** 2))

    coarse = max(np.arange(-max_angle, max_angle + 0.01, 0.5), key=sharpness)
    fine = max(np.arange(coarse - 0.5, coarse + 0.51, 0.1), key=sharpness)
    return round(float(fine), 1) if abs(fine) >= 0.3 else 0.0


# =========================================================================== écriture manuscrite (module optionnel)
_HW_STATE = {"checked": 0.0, "ok": False}


def handwriting_enabled() -> bool:
    """Le module manuscrit est-il installé (bibliothèques + modèle) ? Vérifié au plus une fois par minute."""
    import time
    if time.time() - _HW_STATE["checked"] > 60:
        try:
            from . import handwriting
            _HW_STATE["ok"] = handwriting.available()
        except Exception:  # noqa: BLE001
            _HW_STATE["ok"] = False
        _HW_STATE["checked"] = time.time()
    return _HW_STATE["ok"]


def _handwriting_tokens(img: Image.Image, best: dict, page_no: int, wid: int):
    """
    Détecte les lignes manuscrites (non lues comme imprimé fiable par Tesseract) et les lit avec TrOCR.
    Retourne (tokens, boîtes des lignes lues en pixels).
    """
    from . import handwriting
    d = best["d"]
    words = [([d["left"][i], d["top"][i], d["left"][i] + d["width"][i], d["top"][i] + d["height"][i]],
              float(d["conf"][i]), d["text"][i]) for i in best["idx"]]
    try:
        lines = handwriting.read_handwriting(img, words)
    except Exception as e:  # noqa: BLE001 — le module manuscrit ne doit jamais bloquer l'analyse
        print(f"[manuscrit] lecture impossible : {e}")
        return [], []
    W, H = img.size
    tokens, boxes = [], []
    for ln in lines:
        x0, y0, x1, y1 = ln["box"]
        raw_words = ln["text"].split()
        total = sum(len(w) for w in raw_words) + max(0, len(raw_words) - 1)
        if not total:
            continue
        if ln["conf"] >= 40:
            boxes.append(ln["box"])
        pos = 0
        for rw in raw_words:   # position de chaque mot estimée au prorata des caractères
            a = x0 + (x1 - x0) * pos / total
            b = x0 + (x1 - x0) * (pos + len(rw)) / total
            box = [float(a / W), float(y0 / H), float(b / W), float(y1 / H)]
            for part, n in split_raw(rw):
                t = {"t": rw, "r": part, "n": n, "c": float(ln["conf"]), "p": page_no, "s": "manuscrit", "k": 90, "w": wid, "b": box}
                if ln["conf"] < 40:
                    t["x"] = 1        # lecture trop incertaine : ne compte pas dans la qualité de lecture
                tokens.append(t)
            wid += 1
            pos += len(rw) + 1
    return tokens, boxes


def _run_ocr(img: Image.Image, psm: int = 3):
    d = pytesseract.image_to_data(img, lang=OCR_LANG, config=f"--oem 1 --psm {psm}", output_type=pytesseract.Output.DICT)
    idx = [i for i, w in enumerate(d["text"]) if (w or "").strip() and float(d["conf"][i]) >= 0]
    strength = sum(float(d["conf"][i]) * len(d["text"][i].strip()) for i in idx)
    mean = sum(float(d["conf"][i]) for i in idx) / len(idx) if idx else 0.0
    return {"d": d, "idx": idx, "strength": strength, "mean": mean}


def ocr_image(img: Image.Image, page_no: int, word_id_start: int, detect_rotation: bool = True, info: dict | None = None):
    """OCR d'une image. Retourne (tokens, rotation_90, inclinaison_fine) ; info reçoit le nombre de lignes manuscrites lues."""
    img = _prepare(img)
    rot = _detect_rotation(img) if detect_rotation else 0
    if rot:
        img = img.rotate(-rot, expand=True)  # PIL tourne dans le sens anti-horaire
    skew = _estimate_skew(img)
    if skew:
        img = img.rotate(skew, expand=True, fillcolor=255, resample=Image.BICUBIC)
    W, H = img.size

    # lectures successives, de la moins coûteuse à la plus robuste, tant que la lecture reste médiocre
    def weak(threshold):
        best = max(passes, key=lambda p: p["strength"])
        return best["mean"] < threshold or len(best["idx"]) < 3

    passes = [_run_ocr(img, 3)]                                   # image brute
    if weak(GOOD_READ):
        clean = _clean(img)
        passes.append(_run_ocr(clean, 3))                         # contraste étiré, débruitée, binarisée
        if weak(80):
            passes.append(_run_ocr(_adaptive(img), 3))            # seuillage local (fond non uniforme)
        if weak(80):
            passes.append(_run_ocr(clean, 6))                     # bloc de texte uniforme
            passes.append(_run_ocr(_clean(img, median=5), 6))     # bruit fort
    best = max(passes, key=lambda p: p["strength"])

    tokens, wid = [], word_id_start
    for k, p in enumerate(passes):
        secondary = p is not best
        d = p["d"]
        for i in p["idx"]:
            raw = d["text"][i].strip()
            conf = float(d["conf"][i])
            if secondary and conf < SECONDARY_MIN_CONF:
                continue
            x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
            box = [x / W, y / H, (x + w) / W, (y + h) / H]
            for part, n in split_raw(raw):
                t = {"t": raw, "r": part, "n": n, "c": conf, "p": page_no, "s": "ocr", "k": k, "w": wid, "b": box}
                if secondary:
                    t["x"] = 1
                tokens.append(t)
            wid += 1
    # écriture manuscrite : les lignes que Tesseract n'a pas su lire sont relues par TrOCR
    if handwriting_enabled():
        hw_tokens, hw_boxes = _handwriting_tokens(img, best, page_no, wid)
        if hw_boxes:
            # dans ces zones, la lecture Tesseract (ratée) ne compte plus dans la qualité de lecture
            for t in tokens:
                cx, cy = (t["b"][0] + t["b"][2]) / 2 * W, (t["b"][1] + t["b"][3]) / 2 * H
                if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in hw_boxes):
                    t["x"] = 1
        tokens += hw_tokens
        if info is not None:
            info["manuscrit"] = len(hw_boxes)
    # les lectures sont rangées l'une après l'autre : la recherche se fait dans chaque flux (page, source, lecture)
    return tokens, rot, skew


# =========================================================================== PDF & images
def _native_tokens(page: fitz.Page, page_no: int, word_id_start: int):
    W, H = page.rect.width, page.rect.height
    words = page.get_text("words", sort=True)
    plausible = text_layer_is_plausible([w[4] for w in words])
    tokens, wid = [], word_id_start
    for x0, y0, x1, y1, raw, *_ in words:
        box = [x0 / W, y0 / H, x1 / W, y1 / H]
        for part, n in split_raw(raw):
            t = {"t": raw, "r": part, "n": n, "c": 100.0 if plausible else 20.0, "p": page_no, "s": "texte", "w": wid, "b": box}
            if not plausible:
                t["x"] = 1
            tokens.append(t)
        wid += 1
    return tokens, plausible


def _next_wid(tokens: list[dict]) -> int:
    return tokens[-1]["w"] + 1 if tokens else 0


def page_count(path: str) -> int:
    """Nombre de pages d'un fichier (1 pour une image simple)."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in IMAGE_EXT:
            with Image.open(path) as im:
                return getattr(im, "n_frames", 1)
        with fitz.open(path) as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001 — fichier illisible : l'erreur sera remontée par l'extraction
        return 0


def extract_document(path: str, progress=None) -> dict:
    """
    Extrait tous les tokens d'un fichier.
    progress(pages_faites, pages_totales) est appelé après chaque page (suivi des gros PDF).
    Retourne {"tokens": [...], "pages": [{"mode": "texte|ocr|mixte", "rot": 0, "skew": 0.0}], "quality": 0-100}
    """
    ext = os.path.splitext(path)[1].lower()
    tokens: list[dict] = []
    pages: list[dict] = []

    if ext in IMAGE_EXT:
        with Image.open(path) as im:
            frames = getattr(im, "n_frames", 1)  # TIFF multipage
            if progress:
                progress(0, frames)
            for f in range(frames):
                im.seek(f)
                info = {}
                toks, rot, skew = ocr_image(im.copy(), f + 1, _next_wid(tokens), info=info)
                tokens += toks
                pages.append({"mode": "ocr", "rot": rot, "skew": skew, "manuscrit": info.get("manuscrit", 0)})
                if progress:
                    progress(f + 1, frames)

    elif ext in PDF_EXT:
        doc = fitz.open(path)
        try:
            if progress:
                progress(0, doc.page_count)
            for i, page in enumerate(doc):
                pno = i + 1
                native, plausible = _native_tokens(page, pno, _next_wid(tokens))
                tokens += native
                native_chars = len(page.get_text().strip()) if plausible else 0
                has_images = bool(page.get_images(full=True))
                mode, rot, skew = "texte", 0, 0.0
                if has_images or native_chars < MIN_NATIVE_CHARS:
                    pix = page.get_pixmap(dpi=OCR_DPI)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    scanned = native_chars < MIN_NATIVE_CHARS
                    # rotation auto seulement pour les pages sans texte natif exploitable
                    info = {}
                    toks, rot, skew = ocr_image(img, pno, _next_wid(tokens), detect_rotation=scanned, info=info)
                    tokens += toks
                    mode = "ocr" if scanned else "mixte"
                pages.append({"mode": mode, "rot": rot, "skew": skew, "text_layer": "ok" if plausible else "corrompue",
                              "manuscrit": info.get("manuscrit", 0) if mode != "texte" else 0})
                if progress:
                    progress(pno, doc.page_count)
        finally:
            doc.close()
    else:
        raise ValueError(f"Format non pris en charge : {ext}")

    return {"tokens": tokens, "pages": pages, "quality": reading_quality(tokens)}


def reading_quality(tokens: list[dict]) -> float:
    """
    Qualité de lecture du document (0-100) : confiance moyenne des mots de la lecture principale,
    pondérée par leur longueur. Elle mesure la fiabilité d'une décision « absent » :
    si le document est illisible, l'absence d'un mot-clé ne prouve rien.
    """
    main = [t for t in tokens if not t.get("x")]
    den = sum(len(t["n"]) for t in main)
    if not den:
        return 0.0
    return round(sum(t["c"] * len(t["n"]) for t in main) / den, 1)
