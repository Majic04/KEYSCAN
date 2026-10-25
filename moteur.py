"""
Moteur de KeyScan : lire un document (PDF, scan, photo, lettre manuscrite) puis chercher des mots-clés dedans.

    lire_document(chemin)          -> les mots lus, page par page, et la qualité de lecture
    chercher(mots_lus, mot_cle)    -> les endroits où le mot-clé apparaît, avec un score
    decider(mot_cle, occurrences, qualite, pages, non_lus)  -> (score, décision)

Utilisation seule :  python moteur.py cv.pdf lettre.jpg --mots "thèse, robotique"
"""
import os
import re
import shutil
import sys
import unicodedata
from itertools import groupby

import numpy as np
import pytesseract
from PIL import Image, ImageFilter, ImageOps
from rapidfuzz.distance import Levenshtein

try:
    import pymupdf as fitz
except ImportError:
    import fitz

LANGUES = "fra+eng"
EXT_IMAGES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
EXTENSIONS = EXT_IMAGES | {".pdf"}

# seuils de décision (en %)
SEUIL_PRESENT = 85
SEUIL_A_VERIFIER = 50
QUALITE_MIN = 70

PRESENT, A_VERIFIER, ABSENT, INCERTAIN = "present", "a_verifier", "absent", "absent_douteux"
NOMS = {PRESENT: "Présent", A_VERIFIER: "À vérifier", ABSENT: "Absent", INCERTAIN: "Absence incertaine"}


# ---------------------------------------------------------------------------------------------
# Texte : un mot lu = un ou plusieurs « tokens » (dictionnaires)
#   texte : le mot tel qu'il a été lu        partie : le morceau de mot de ce token
#   norm  : ce morceau sans accents ni majuscules
#   conf  : confiance de lecture 0-100       page, source ("texte", "ocr", "manuscrit")
#   num   : numéro du mot (« Sous-Traitance » donne 2 tokens avec le même numéro)
#   box   : position [gauche, haut, droite, bas] entre 0 et 1
#   lecture : numéro de la lecture OCR       secondaire : ne compte pas dans la qualité
# ---------------------------------------------------------------------------------------------

def normaliser(texte):
    texte = texte.lower().replace("œ", "oe").replace("æ", "ae")
    texte = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in texte if not unicodedata.combining(c))


def morceaux(texte):
    """« Sous-Traitance, » -> [("Sous", "sous"), ("Traitance", "traitance")]. Garde C++ et C#."""
    res = []
    for m in re.finditer(r"[^\W_]+(?:\+\+|#)?", texte):
        brut = m.group(0)
        for n in re.findall(r"[a-z0-9]+(?:\+\+|#)?", normaliser(brut)):
            res.append((brut, n))
    return res


def tokens_du_mot(mot, conf, page, source, num, box, lecture=0, secondaire=False):
    toks = []
    for brut, n in morceaux(mot):
        t = {"texte": mot, "partie": brut, "norm": n, "conf": float(conf), "page": page,
             "source": source, "num": num, "box": box, "lecture": lecture}
        if secondaire:
            t["secondaire"] = 1
        toks.append(t)
    return toks


# ---------------------------------------------------------------------------------------------
# Lecture d'un document
# ---------------------------------------------------------------------------------------------

def trouver_tesseract():
    for chemin in [os.environ.get("TESSERACT_CMD"), shutil.which("tesseract"),
                   r"C:\Program Files\Tesseract-OCR\tesseract.exe", "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"]:
        if chemin and os.path.exists(chemin):
            pytesseract.pytesseract.tesseract_cmd = chemin
            return chemin
    return None


MOTS_COURANTS = set("le la les de des du un une et en au aux a pour par sur avec dans est sont il elle ce qui que ne pas "
                    "plus ou nous je mon ma mes the and of to in for on with is are was by an at as from this that be it my we".split())


def texte_lisible(mots):
    """Certains PDF ont un texte copiable faux (« DSSUHQWLVVDJH ») : on le détecte ici."""
    texte = " ".join(mots)
    if not texte.strip():
        return True
    bizarres = sum(1 for c in texte if unicodedata.category(c) in ("Cc", "Co", "Cn") or c == "\ufffd")
    if bizarres > 0.01 * len(texte):
        return False
    vrais_mots = [normaliser(m) for m in re.findall(r"[^\W\d_]{2,}", texte)]
    if not vrais_mots:
        return True
    avec_voyelle = sum(1 for m in vrais_mots if re.search("[aeiouy]", m)) / len(vrais_mots)
    courants = sum(1 for m in vrais_mots if m in MOTS_COURANTS)
    if len(vrais_mots) >= 12 and courants == 0 and avec_voyelle < 0.9:
        return False
    return avec_voyelle >= 0.7


def nb_pages(chemin):
    try:
        if os.path.splitext(chemin)[1].lower() in EXT_IMAGES:
            with Image.open(chemin) as im:
                return getattr(im, "n_frames", 1)
        with fitz.open(chemin) as doc:
            return doc.page_count
    except Exception:
        return 0


def lire_document(chemin, avancement=None):
    """Retourne {"tokens": [...], "pages": [...], "qualite": 0-100}. avancement(fait, total) après chaque page."""
    ext = os.path.splitext(chemin)[1].lower()
    tokens, pages = [], []
    if ext in EXT_IMAGES:
        with Image.open(chemin) as im:
            total = getattr(im, "n_frames", 1)
            for i in range(total):
                im.seek(i)
                r = lire_image(im.copy(), i + 1, len(tokens))
                tokens += r["tokens"]
                pages.append({"mode": "ocr", "rot": r["rot"], "inclinaison": r["inclinaison"], "manuscrit": r["manuscrit"]})
                if avancement:
                    avancement(i + 1, total)
    elif ext == ".pdf":
        with fitz.open(chemin) as doc:
            for i, page in enumerate(doc):
                num_page = i + 1
                mots = page.get_text("words", sort=True)
                ok = texte_lisible([m[4] for m in mots])
                w, h = page.rect.width, page.rect.height
                for x0, y0, x1, y1, mot, *_ in mots:
                    tokens += tokens_du_mot(mot, 100 if ok else 20, num_page, "texte", len(tokens),
                                            [x0 / w, y0 / h, x1 / w, y1 / h], secondaire=not ok)
                nb_car = len(page.get_text().strip()) if ok else 0
                info = {"mode": "texte", "rot": 0, "inclinaison": 0, "manuscrit": 0}
                # page scannée ou avec des images : on la lit aussi par OCR
                if page.get_images(full=True) or nb_car < 30:
                    pix = page.get_pixmap(dpi=300)
                    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    r = lire_image(image, num_page, len(tokens), chercher_sens=nb_car < 30)
                    tokens += r["tokens"]
                    info = {"mode": "ocr" if nb_car < 30 else "mixte", "rot": r["rot"],
                            "inclinaison": r["inclinaison"], "manuscrit": r["manuscrit"]}
                pages.append(info)
                if avancement:
                    avancement(num_page, doc.page_count)
    else:
        raise ValueError("format non pris en charge : " + ext)
    return {"tokens": tokens, "pages": pages, "qualite": qualite(tokens)}


def qualite(tokens):
    """Confiance moyenne des mots lus (les mots longs comptent plus). Sert à savoir si on peut dire « absent »."""
    toks = [t for t in tokens if not t.get("secondaire")]
    lettres = sum(len(t["norm"]) for t in toks)
    if not lettres:
        return 0.0
    return round(sum(t["conf"] * len(t["norm"]) for t in toks) / lettres, 1)


# ---------------------------------------------------------------------------------------------
# OCR d'une image (Tesseract)
# ---------------------------------------------------------------------------------------------

def seuil_otsu(pixels):
    hist = np.bincount(pixels.ravel(), minlength=256).astype(float)
    n = np.cumsum(hist)
    s = np.cumsum(hist * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        sep = (s[-1] * n / n[-1] - s) ** 2 / (n * (n[-1] - n))
    sep[~np.isfinite(sep)] = 0
    return int(np.argmax(sep))


def noir_et_blanc(gris, median=3):
    im = ImageOps.autocontrast(gris, cutoff=0.5).filter(ImageFilter.MedianFilter(median))
    seuil = seuil_otsu(np.asarray(im))
    return im.point(lambda v: 255 if v > seuil else 0)


def seuil_local(gris, rayon=20, marge=14):
    """Pour les fonds pas uniformes (ombre d'une photo) : chaque pixel est comparé à ses voisins."""
    lisse = gris.filter(ImageFilter.MedianFilter(3))
    px = np.asarray(lisse, dtype=np.int16)
    voisins = np.asarray(lisse.filter(ImageFilter.BoxBlur(rayon)), dtype=np.int16)
    return Image.fromarray(np.where(px < voisins - marge, 0, 255).astype(np.uint8))


def tesseract(image, psm=3):
    d = pytesseract.image_to_data(image, lang=LANGUES, config=f"--oem 1 --psm {psm}", output_type=pytesseract.Output.DICT)
    mots = []
    for i, txt in enumerate(d["text"]):
        txt = (txt or "").strip()
        conf = float(d["conf"][i])
        if txt and conf >= 0:
            x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
            mots.append({"texte": txt, "conf": conf, "box": [x, y, x + w, y + h]})
    poids = sum(m["conf"] * len(m["texte"]) for m in mots)
    moyenne = sum(m["conf"] for m in mots) / len(mots) if mots else 0
    return {"mots": mots, "poids": poids, "moyenne": moyenne}


def texte_sur(gris):
    """Nombre de lettres lues avec assurance (pour comparer deux sens de lecture)."""
    petit = gris.copy()
    petit.thumbnail((1400, 1400))
    return sum(len(m["texte"]) for m in tesseract(petit)["mots"] if m["conf"] >= 70 and len(m["texte"]) >= 3)


def trouver_sens(gris):
    """0, 90, 180 ou 270. Tesseract se trompe souvent sur l'écriture manuscrite, donc on vérifie qu'on lit mieux après."""
    for im in (gris, noir_et_blanc(gris)):
        try:
            osd = pytesseract.image_to_osd(im, output_type=pytesseract.Output.DICT)
        except pytesseract.TesseractError:
            continue
        angle = int(osd.get("rotate", 0)) % 360
        if float(osd.get("orientation_conf", 0)) < 1.5:
            continue
        if angle == 0:
            return 0
        avant, apres = texte_sur(gris), texte_sur(gris.rotate(-angle, expand=True))
        return angle if apres > 1.5 * avant + 10 else 0
    return 0


def trouver_inclinaison(gris, max_angle=12):
    """On tourne l'image petit à petit : quand les lignes sont droites, le profil d'encre est le plus contrasté."""
    petit = gris.copy()
    petit.thumbnail((1000, 1000))
    px = np.asarray(petit)
    nb = (px < seuil_otsu(px)).astype(np.uint8) * 255
    if nb.mean() < 0.5 or nb.mean() > 128:
        return 0.0
    im = Image.fromarray(nb)

    def nettete(a):
        profil = np.asarray(im.rotate(a, resample=Image.NEAREST), dtype=np.float32).sum(axis=1)
        return float(np.sum(np.diff(profil) ** 2))

    a = max(np.arange(-max_angle, max_angle + 0.01, 0.5), key=nettete)
    a = max(np.arange(a - 0.5, a + 0.51, 0.1), key=nettete)
    return round(float(a), 1) if abs(a) >= 0.3 else 0.0


def lire_image(image, page, premier_num, chercher_sens=True):
    gris = ImageOps.exif_transpose(image).convert("L")
    if gris.width < 1800:   # Tesseract lit mieux les grandes images
        f = min(3.0, 1800 / gris.width)
        gris = gris.resize((int(gris.width * f), int(gris.height * f)), Image.LANCZOS)
    rot = trouver_sens(gris) if chercher_sens else 0
    if rot:
        gris = gris.rotate(-rot, expand=True)
    incl = trouver_inclinaison(gris)
    if incl:
        gris = gris.rotate(incl, expand=True, fillcolor=255, resample=Image.BICUBIC)
    W, H = gris.size

    # plusieurs lectures si la première est mauvaise
    lectures = [tesseract(gris)]

    def mauvais(seuil):
        m = max(lectures, key=lambda l: l["poids"])
        return m["moyenne"] < seuil or len(m["mots"]) < 3

    if mauvais(88):
        propre = noir_et_blanc(gris)
        lectures.append(tesseract(propre))
        if mauvais(80):
            lectures.append(tesseract(seuil_local(gris)))
        if mauvais(80):
            lectures.append(tesseract(propre, psm=6))
            lectures.append(tesseract(noir_et_blanc(gris, 5), psm=6))
    meilleure = max(lectures, key=lambda l: l["poids"])

    tokens, num = [], premier_num
    for k, lec in enumerate(lectures):
        for m in lec["mots"]:
            if lec is not meilleure and m["conf"] < 40:
                continue
            x0, y0, x1, y1 = m["box"]
            tokens += tokens_du_mot(m["texte"], m["conf"], page, "ocr", num, [x0 / W, y0 / H, x1 / W, y1 / H],
                                    lecture=k, secondaire=lec is not meilleure)
            num += 1

    nb_manuscrit = 0
    if manuscrit_dispo():
        try:
            nb_manuscrit = ajouter_manuscrit(gris, meilleure["mots"], page, num, tokens)
        except Exception as e:
            print("lecture manuscrite impossible :", e)
    return {"tokens": tokens, "rot": rot, "inclinaison": incl, "manuscrit": nb_manuscrit}


# ---------------------------------------------------------------------------------------------
# Écriture manuscrite : on repère les lignes que Tesseract n'a pas su lire et on les donne à TrOCR
# ---------------------------------------------------------------------------------------------

MODELE = os.environ.get("KEYSCAN_MODELE", "agomberto/trocr-large-handwritten-fr")
PROCESSEUR = os.environ.get("KEYSCAN_PROCESSEUR", "microsoft/trocr-large-handwritten")
_trocr = None


def manuscrit_dispo():
    if os.environ.get("KEYSCAN_SANS_MANUSCRIT"):
        return False
    try:
        import torch, transformers  # noqa: F401
        return True
    except ImportError:
        return False


def masque_encre(gris):
    lisse = gris.filter(ImageFilter.MedianFilter(3))
    px = np.asarray(lisse, dtype=np.int16)
    encre = px < np.asarray(lisse.filter(ImageFilter.BoxBlur(25)), dtype=np.int16) - 12
    # enlever le grain du papier : un vrai trait remplit une partie de son voisinage
    r = max(3, gris.width // 600)
    c = np.pad(encre.astype(np.int32), ((r + 1, r), (r + 1, r))).cumsum(0).cumsum(1)
    k = 2 * r + 1
    autour = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    encre &= autour >= 0.2 * k * k
    # enlever les longs traits horizontaux (bord de carte, soulignement)
    L = max(40, gris.width // 6)
    if encre.shape[1] > L:
        c = np.pad(encre.astype(np.int32), ((0, 0), (1, 0))).cumsum(1)
        plein = np.pad(((c[:, L:] - c[:, :-L]) >= int(0.92 * L)).astype(np.int32), ((0, 0), (1, 0))).cumsum(1)
        x = np.arange(encre.shape[1])
        encre &= ~((plein[:, np.minimum(x, encre.shape[1] - L) + 1] - plein[:, np.maximum(0, x - L + 1)]) > 0)
    return encre


def intervalles(masque):
    bords = np.diff(np.concatenate([[False], masque, [False]]).astype(np.int8))
    return list(zip(np.where(bords == 1)[0], np.where(bords == -1)[0]))


def interligne(profil):
    """Mesuré par autocorrélation : le profil ressemble à lui-même décalé d'une ligne."""
    p = profil - profil.mean()
    n = len(p)
    ac = np.correlate(p, p, mode="full")[n - 1:]
    if ac[0] <= 0:
        return 0
    a, b = max(8, n // 150), max(9, n // 4)
    fen = ac[a:b]
    pics = [i for i in range(1, len(fen) - 1) if fen[i] >= fen[i - 1] and fen[i] >= fen[i + 1] and fen[i] > 0.1 * ac[0]]
    return a + max(pics, key=lambda i: fen[i]) if pics else 0


def bandes_de_lignes(profil):
    H = len(profil)
    esp = interligne(profil)
    if esp < 8:
        seuil = max(2.0, 0.06 * float(np.percentile(profil[profil > 0], 90)))
        return [(h, b) for h, b in intervalles(profil > seuil) if b - h >= 6]
    lisse = np.convolve(profil, np.ones(max(3, esp // 3)) / max(3, esp // 3), mode="same")
    cand = [y for y in range(1, H - 1) if lisse[y] >= lisse[y - 1] and lisse[y] > lisse[y + 1] and lisse[y] > 0.12 * lisse.max()]
    pics = []
    for y in sorted(cand, key=lambda y: -lisse[y]):
        if all(abs(y - p) >= 0.6 * esp for p in pics):
            pics.append(y)
    pics.sort()
    bandes = []
    for i, p in enumerate(pics):
        haut = pics[i - 1] + int(np.argmin(lisse[pics[i - 1]:p])) if i else max(0, int(p - 0.6 * esp))
        bas = p + int(np.argmin(lisse[p:pics[i + 1]])) if i + 1 < len(pics) else min(H, int(p + 0.6 * esp))
        encre = np.where(profil[haut:bas] > 0.05 * lisse[p])[0]
        if len(encre):
            haut, bas = haut + int(encre[0]), haut + int(encre[-1]) + 1
        if bas - haut >= 6:
            bandes.append((haut, bas))
    return bandes


def lignes_de_texte(gris):
    """Les morceaux de lignes de la page, en pixels (gauche, haut, droite, bas)."""
    encre = masque_encre(gris)
    H, W = encre.shape
    profil = encre.sum(axis=1).astype(np.float32)
    if not profil.any():
        return []
    boites = []
    for haut, bas in bandes_de_lignes(profil):
        h = bas - haut
        if h < 8 or h > H / 2:
            continue
        traits = [t for t in intervalles(encre[haut:bas].sum(axis=0) >= 2) if t[1] - t[0] >= 2]
        if not traits:
            continue
        # un grand vide sépare deux colonnes ; un morceau trop long est coupé entre deux mots
        morceaux_ligne, debut, fin = [], traits[0][0], traits[0][1]
        for a, b in traits[1:]:
            if a - fin > 1.8 * h or (a - fin > 0.35 * h and fin - debut > 14 * h):
                morceaux_ligne.append((debut, fin))
                debut = a
            fin = b
        morceaux_ligne.append((debut, fin))
        for g, d in morceaux_ligne:
            if d - g < h or encre[haut:bas, g:d].sum() < 0.02 * h * (d - g):
                continue
            boites.append((max(0, g - h // 4), max(0, haut - h // 12), min(W, d + h // 4), min(H, bas + h // 12)))
    return boites


def lire_lignes(images):
    """TrOCR lit chaque image de ligne. Retourne [(texte, confiance 0-100)]."""
    global _trocr
    import torch
    from transformers import AutoTokenizer, TrOCRProcessor, VisionEncoderDecoderModel
    from transformers.utils import logging
    logging.set_verbosity_error()
    if _trocr is None:
        print("chargement du modèle manuscrit (téléchargé la première fois, environ 2 Go)…")
        proc = TrOCRProcessor.from_pretrained(PROCESSEUR)
        tok = AutoTokenizer.from_pretrained(MODELE)
        modele = VisionEncoderDecoderModel.from_pretrained(MODELE).eval()
        if modele.config.decoder_start_token_id is None:
            modele.config.decoder_start_token_id = tok.cls_token_id or tok.bos_token_id
        if modele.config.pad_token_id is None:
            modele.config.pad_token_id = tok.pad_token_id
        _trocr = (proc, tok, modele)
    proc, tok, modele = _trocr
    res = []
    for i in range(0, len(images), 6):
        lot = [im.convert("RGB") for im in images[i:i + 6]]
        with torch.no_grad():
            out = modele.generate(proc(images=lot, return_tensors="pt").pixel_values, max_new_tokens=64, num_beams=1,
                                  output_scores=True, return_dict_in_generate=True)
            logp = modele.compute_transition_scores(out.sequences, out.scores, normalize_logits=True)
        textes = tok.batch_decode(out.sequences, skip_special_tokens=True)
        for j, txt in enumerate(textes):
            ids = out.sequences[j, 1:]
            v = logp[j][[k for k in range(logp.shape[1]) if k < len(ids) and int(ids[k]) != modele.config.pad_token_id]]
            v = v[torch.isfinite(v)]
            conf = float(torch.exp(v.mean())) * 100 if len(v) else 0.0
            res.append((txt.strip(), round(conf, 1)))
    return res


def ajouter_manuscrit(gris, mots_imprimes, page, num, tokens):
    """Ajoute les mots manuscrits aux tokens. Retourne le nombre de lignes manuscrites bien lues."""
    W, H = gris.size
    bien_lus = [m["box"] for m in mots_imprimes if m["conf"] >= 75 and (len(m["texte"]) >= 2 or m["conf"] >= 90)]
    lignes = []
    for g, h, d, b in lignes_de_texte(gris):
        couvert = np.zeros(d - g, dtype=bool)
        for x0, y0, x1, y1 in bien_lus:
            if min(b, y1) - max(h, y0) > 0.4 * min(b - h, y1 - y0):
                couvert[max(0, int(x0) - g):max(0, int(x1) - g)] = True
        if couvert.mean() < 0.6:   # pas du texte imprimé bien lu -> manuscrit
            lignes.append((g, h, d, b))
    lignes = lignes[:60]
    if not lignes:
        return 0
    lues = []
    for (g, h, d, b), (txt, conf) in zip(lignes, lire_lignes([gris.crop(l) for l in lignes])):
        mots = txt.split()
        nb = sum(len(m) for m in mots) + len(mots) - 1
        if not mots:
            continue
        if conf >= 40:
            lues.append((g, h, d, b))
        pos = 0
        for m in mots:   # TrOCR ne donne pas la position des mots : on l'estime avec le nombre de lettres
            box = [(g + (d - g) * pos / nb) / W, h / H, (g + (d - g) * (pos + len(m)) / nb) / W, b / H]
            tokens += tokens_du_mot(m, conf, page, "manuscrit", num, box, lecture=90, secondaire=conf < 40)
            num += 1
            pos += len(m) + 1
    # dans ces lignes, ce que Tesseract a mal lu ne compte plus dans la qualité
    for t in tokens:
        if t["source"] == "ocr":
            cx, cy = (t["box"][0] + t["box"][2]) / 2 * W, (t["box"][1] + t["box"][3]) / 2 * H
            if any(g <= cx <= d and h <= cy <= b for g, h, d, b in lues):
                t["secondaire"] = 1
    return len(lues)


# ---------------------------------------------------------------------------------------------
# Recherche d'un mot-clé
#   score d'une occurrence = ressemblance (0 à 1) x confiance de lecture (0 à 1)
# ---------------------------------------------------------------------------------------------

CONFUSIONS_OCR = [("rn", "m"), ("vv", "w"), ("cl", "d"), ("0", "o"), ("1", "l"), ("i", "l"), ("5", "s")]
ELISIONS = {"l", "d", "j", "m", "n", "s", "t", "c", "qu", "jusqu", "lorsqu", "puisqu", "quoiqu", "presqu"}
TIRETS = "-‐‑"
APOSTROPHES = "'’ʼ"


def sans_confusions(txt, garder_chiffres):
    for a, b in CONFUSIONS_OCR:
        if not (garder_chiffres and a.isdigit()):
            txt = txt.replace(a, b)
    return txt


def erreurs_tolerees(longueur, manuscrit):
    paliers = [(3, 0), (6, 1), (10, 2), (99, 3.5)] if manuscrit else [(4, 0), (6, 0.5), (10, 1.5), (99, 2.5)]
    return next(e for lmax, e in paliers if longueur <= lmax)


def meme_mot_ou_pluriel(a, b):
    court, long_ = sorted((a, b), key=len)
    return a == b or (len(court) >= 3 and long_ in (court + "s", court + "x", court + "es"))


def ressemblance(mc, fenetre):
    """mc = le mot-clé découpé (voir chercher). Retourne 0 si trop différent."""
    source = fenetre[0]["source"]
    lu = "".join(t["norm"] for t in fenetre)
    meme_decoupe = len(fenetre) == len(mc["parties"])
    longueur = len(mc["colle"])

    if lu == mc["colle"]:
        err = 0
    elif meme_decoupe and all(meme_mot_ou_pluriel(t["norm"], p) for t, p in zip(fenetre, mc["parties"])):
        err = 0.25 if source == "texte" else 0.5
    elif source == "texte":
        # texte du PDF : seulement une faute de frappe dans un mot long
        if longueur >= 8 and Levenshtein.distance(lu, mc["colle"]) <= 1:
            err = 1
        else:
            return 0
    else:
        tol = erreurs_tolerees(longueur, source == "manuscrit")
        if tol == 0 or abs(len(lu) - longueur) > tol + 1:
            return 0
        err = Levenshtein.distance(lu, mc["colle"])
        avec_conf = Levenshtein.distance(sans_confusions(lu, mc["chiffres"]), sans_confusions(mc["colle"], mc["chiffres"]))
        if avec_conf < err:
            err = min(err, avec_conf + 0.5)
        if err > tol:
            return 0

    if err == 0:
        r = 1.0
    elif err <= 0.25:
        r = 0.97
    else:
        r = 1 - 0.12 * err * 8 / max(longueur, 8)
        if source == "texte":
            r = min(r, 0.9)
        if source == "manuscrit":
            r = min(r, 0.8)   # écriture manuscrite approchée : jamais plus que « à vérifier »

    # accent oublié sur un mot court (« these » pour « thèse »), sigle écrit en minuscules
    if meme_decoupe:
        for t, brut in zip(fenetre, mc["bruts"]):
            lu_brut = t["partie"]
            if normaliser(brut) != brut.lower() and normaliser(brut) == normaliser(lu_brut) and brut.lower() != lu_brut.lower():
                if len(normaliser(brut)) <= 6:
                    r *= (0.85 if lu_brut.isupper() else 0.72) if source == "texte" else 0.9
                elif source == "texte":
                    r *= 0.97
            if len(brut) >= 2 and brut.isupper() and lu_brut.islower():
                r *= 0.6 if source == "texte" else 0.75
    return max(0.0, min(1.0, r))


def separateurs(flux):
    """sep[k] = ce qu'il y a entre le token k-1 et k s'ils viennent du même mot lu, sinon None."""
    sep, curseur = [None] * len(flux), 0
    for k, t in enumerate(flux):
        meme = k > 0 and t["num"] == flux[k - 1]["num"]
        pos = t["texte"].find(t["partie"], curseur if meme else 0)
        if meme:
            pos = pos if pos >= 0 else curseur
            sep[k] = t["texte"][curseur:pos]
        else:
            pos = max(pos, 0)
        curseur = pos + len(t["partie"])
    return sep


def coupe_en_fin_de_ligne(t):
    mot = t["texte"].rstrip()
    return mot.endswith(tuple(TIRETS)) and mot.strip(TIRETS + " ") == t["partie"]


def colles(a, b):
    """Deux mots lus séparément mais qui se touchent sur l'image."""
    if a["box"] == b["box"]:
        return False
    if min(a["box"][3], b["box"][3]) - max(a["box"][1], b["box"][1]) < 0.5 * min(a["box"][3] - a["box"][1], b["box"][3] - b["box"][1]):
        return False
    largeur_lettre = (a["box"][2] - a["box"][0]) / max(1, len(a["texte"].strip()))
    return 0 <= b["box"][0] - a["box"][2] < 0.25 * largeur_lettre


def autour(flux, sep, debut, fin):
    """« seul », « compose » (Master-Recherche) ou « dedans » (pour dans pourquoi : pas une occurrence)."""
    res = "seul"
    positions_fiables = flux[debut]["source"] != "manuscrit"
    if debut > 0:
        avant, s = flux[debut - 1], sep[debut]
        if s is not None:
            if any(c in APOSTROPHES for c in s) and avant["norm"] in ELISIONS:
                pass   # l'apprentissage, d'ingénieur
            elif s and all(c in TIRETS for c in s):
                res = "compose"
            else:
                return "dedans"
        elif coupe_en_fin_de_ligne(avant) or (positions_fiables and colles(avant, flux[debut])):
            return "dedans"
    if fin < len(flux):
        s = sep[fin]
        if s is not None:
            if s and all(c in TIRETS for c in s):
                res = "compose"
            else:
                return "dedans"
        elif coupe_en_fin_de_ligne(flux[fin - 1]) or (positions_fiables and colles(flux[fin - 1], flux[fin])):
            return "dedans"
    return res


def meme_endroit(a, b):
    lw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    lh = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    commun = lw * lh
    if commun == 0:
        return False
    aa = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    ab = max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
    return commun / (aa + ab - commun) > 0.25 or commun / min(aa, ab) > 0.6


def extrait(flux, debut, fin):
    def mots(toks):
        res = []
        for t in toks:
            if not res or res[-1][0] != t["num"]:
                res.append((t["num"], t["texte"]))
        return " ".join(m for _, m in res)
    return f"{mots(flux[max(0, debut - 7):debut])} [[{mots(flux[debut:fin])}]] {mots(flux[fin:fin + 7])}".strip()


def chercher(tokens, mot_cle):
    """Toutes les occurrences du mot-clé : [{"page", "source", "certain", "score" (0-1), "texte", "contexte", "box"}]."""
    parts = morceaux(mot_cle)
    if not parts:
        return []
    colle = "".join(n for _, n in parts)
    mc = {"bruts": [b for b, _ in parts], "parties": [n for _, n in parts], "colle": colle,
          "chiffres": any(c.isdigit() for c in colle)}
    n = len(parts)
    tailles = sorted({max(1, n - 1), n, n + 1})   # un mot-clé de 2 mots peut avoir été lu collé ou coupé

    trouves = []
    for (page, source, _), groupe in groupby(tokens, key=lambda t: (t["page"], t["source"], t.get("lecture", 0))):
        flux = list(groupe)
        sep = separateurs(flux)
        candidats = []
        for debut in range(len(flux)):
            for taille in tailles:
                fin = debut + taille
                if fin > len(flux):
                    continue
                fen = flux[debut:fin]
                r = ressemblance(mc, fen)
                if r <= 0:
                    continue
                place = autour(flux, sep, debut, fin)
                if place == "dedans":
                    continue
                if place == "compose":
                    r = min(r, 0.8)
                conf = sum(t["conf"] for t in fen) / len(fen) / 100
                # retrouver exactement un mot long par hasard avec Tesseract est très improbable : on fait plus confiance
                if source == "ocr" and "".join(t["norm"] for t in fen) == colle:
                    conf = 1 - (1 - conf) * 0.5 ** (max(0, len(colle) - 3) / 3)
                candidats.append((r * conf, r, debut, fin))
        candidats.sort(key=lambda c: (-c[0], c[3] - c[2]))
        pris = set()
        for score, r, debut, fin in candidats:
            if pris.intersection(range(debut, fin)):
                continue
            pris.update(range(debut, fin))
            fen = flux[debut:fin]
            trouves.append({
                "page": page, "source": source, "certain": r >= 0.94, "score": round(score, 4),
                "texte": " ".join(dict.fromkeys(t["texte"] for t in fen)),
                "contexte": extrait(flux, debut, fin),
                "box": [min(t["box"][0] for t in fen), min(t["box"][1] for t in fen),
                        max(t["box"][2] for t in fen), max(t["box"][3] for t in fen)],
            })
    # un même endroit lu plusieurs fois (PDF + OCR, ou plusieurs lectures) ne compte qu'une fois
    trouves.sort(key=lambda o: -o["score"])
    res = []
    for o in trouves:
        if not any(r["page"] == o["page"] and meme_endroit(r["box"], o["box"]) for r in res):
            res.append(o)
    res.sort(key=lambda o: (o["page"], o["box"][1], o["box"][0]))
    return res


# ---------------------------------------------------------------------------------------------
# Décision pour un mot-clé dans un dossier
# ---------------------------------------------------------------------------------------------

def decider(mot_cle, occurrences, qualite_min_dossier, pages, non_lus=0):
    """
    Les occurrences sûres se renforcent : 0,9 et 0,8 donnent 0,96. Une occurrence seulement approchante
    (« these » pour « thèse ») ne se cumule pas et reste sous le seuil « Présent », même répétée.
    """
    sures = sorted((o["score"] for o in occurrences if o["certain"]), reverse=True)
    approchees = [o["score"] for o in occurrences if not o["certain"]]
    manque = 1.0
    for i, s in enumerate(sures):
        manque *= 1 - (s if i == 0 else s / 2)
    score = round(max(1 - manque if sures else 0, max(approchees, default=0)) * 100, 1)
    if not sures:
        score = min(score, SEUIL_PRESENT - 1)

    if score >= SEUIL_PRESENT:
        return score, PRESENT
    if score >= SEUIL_A_VERIFIER:
        return score, A_VERIFIER
    # on n'affirme pas « absent » si on n'a pas pu tout bien lire
    manuscrit = any(p.get("manuscrit") for p in pages)
    scan = any(p.get("mode") in ("ocr", "mixte") for p in pages)
    mot_court = len("".join(n for _, n in morceaux(mot_cle))) <= 2
    if non_lus or qualite_min_dossier < QUALITE_MIN or manuscrit or (scan and mot_court):
        return score, INCERTAIN
    return score, ABSENT


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="KeyScan sans interface : un dossier = les fichiers donnés")
    ap.add_argument("fichiers", nargs="+")
    ap.add_argument("--mots", required=True, help='mots-clés séparés par des virgules : "thèse, robotique"')
    a = ap.parse_args()
    trouver_tesseract()
    lus, non_lus = [], 0
    for f in a.fichiers:
        try:
            lus.append(lire_document(f))
            print(f"{f} : lu ({lus[-1]['qualite']} %)")
        except Exception as e:
            non_lus += 1
            print(f"{f} : illisible ({e})")
    q = min((d["qualite"] for d in lus), default=0)
    pages = [p for d in lus for p in d["pages"]]
    for mot in [m.strip() for m in a.mots.split(",") if m.strip()]:
        occ = [o for d in lus for o in chercher(d["tokens"], mot)]
        score, dec = decider(mot, occ, q, pages, non_lus)
        print(f"  {mot:25s} {NOMS[dec]:20s} {score:5.1f} %")
    sys.exit(0)
