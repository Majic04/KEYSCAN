"""
Recherche d'un mot-clé dans les mots lus d'un document.

On fait glisser une « fenêtre » sur les mots lus (1, 2 ou 3 mots consécutifs selon la longueur du
mot-clé) et on mesure à chaque position la ressemblance avec le mot-clé.

    score d'une occurrence = ressemblance (0 à 1) × confiance de lecture (0 à 1)

Ressemblance :
  - écriture identique, sans tenir compte des majuscules ni des accents .................. 1
  - singulier / pluriel (« réseau » / « réseaux ») ....................................... 0,97
  - texte du PDF (aucune erreur de lecture possible) : une seule faute de frappe tolérée,
    et seulement sur un mot de 8 lettres ou plus
  - texte lu par OCR : quelques erreurs de lecture tolérées selon la longueur du mot ;
    une confusion typique de l'OCR (rn↔m, cl↔d, 0↔o, 1/i↔l, 5↔s, vv↔w) coûte une demi-erreur
  - écriture manuscrite : un peu plus de tolérance, mais au mieux « à vérifier »
  - accent différent sur un mot court (« these » pour « thèse »), sigle écrit en minuscules : pénalité

Confiance de lecture : 1 pour le texte du PDF ; celle de Tesseract pour l'OCR, relevée quand le mot
est retrouvé exactement (retrouver par hasard, lettre pour lettre, un mot long est très improbable) ;
celle du modèle pour l'écriture manuscrite.

Un mot-clé n'est jamais trouvé à l'intérieur d'un mot plus long (« pour » dans « pourquoi »).
"""
from __future__ import annotations

from itertools import groupby

from rapidfuzz.distance import Levenshtein

from .text import normalize, word_parts

CONTEXT_WORDS = 7              # mots montrés avant et après une occurrence
CERTAIN_SIMILARITY = 0.94      # au-dessus : le mot lu EST le mot-clé (au pluriel ou à une confusion d'OCR près)
OCR_CONFUSIONS = [("rn", "m"), ("vv", "w"), ("cl", "d"), ("0", "o"), ("1", "l"), ("i", "l"), ("5", "s")]


# =========================================================================== le mot-clé
def _with_ocr_confusions(text: str, keep_digits: bool) -> str:
    """Remplace les groupes de lettres que l'OCR confond par une forme commune : « rnaster » → « master »."""
    for confused, replacement in OCR_CONFUSIONS:
        if keep_digits and confused.isdigit():
            continue
        text = text.replace(confused, replacement)
    return text


def allowed_errors(length: int, handwritten: bool = False) -> float:
    """Nombre d'erreurs de lecture tolérées selon la longueur du mot-clé (aucune pour un mot très court)."""
    if handwritten:
        steps = [(3, 0.0), (6, 1.0), (10, 2.0)]
        above = 3.5
    else:
        steps = [(4, 0.0), (6, 0.5), (10, 1.5)]
        above = 2.5
    for max_length, errors in steps:
        if length <= max_length:
            return errors
    return above


class Keyword:
    """Un mot-clé prêt pour la recherche : « Réseaux de neurones » → parties ["reseaux", "de", "neurones"]."""

    def __init__(self, term: str):
        parts = word_parts(term)
        self.term = term
        self.raw_parts = [raw for raw, _ in parts]
        self.parts = [normalized for _, normalized in parts]
        self.joined = "".join(self.parts)                    # "reseauxdeneurones"
        self.length = len(self.joined)
        self.has_digits = any(ch.isdigit() for ch in self.joined)
        self.joined_confused = _with_ocr_confusions(self.joined, self.has_digits)


# =========================================================================== ressemblance
def _same_word_or_plural(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 3 and long_ in (short + "s", short + "x", short + "es")


def _has_accent(text: str) -> bool:
    return normalize(text) != text.lower()


def similarity(keyword: Keyword, window: list[dict]) -> float:
    """Ressemblance (0 à 1) entre quelques mots lus consécutifs et le mot-clé ; 0 si trop différents."""
    source = window[0]["s"]
    from_pdf, handwritten = source == "texte", source == "manuscrit"
    read = "".join(t["n"] for t in window)
    same_split = len(window) == len(keyword.parts)

    # 1. combien d'erreurs séparent le texte lu du mot-clé ?
    if read == keyword.joined:
        errors = 0.0
    elif same_split and all(_same_word_or_plural(t["n"], k) for t, k in zip(window, keyword.parts)):
        errors = 0.25 if from_pdf else 0.5                  # singulier / pluriel
    elif from_pdf:
        if keyword.length >= 8 and Levenshtein.distance(read, keyword.joined, score_cutoff=1) <= 1:
            errors = 1.0                                     # une faute de frappe dans un mot long
        else:
            return 0.0
    else:
        tolerated = allowed_errors(keyword.length, handwritten)
        if tolerated == 0 or abs(len(read) - keyword.length) > tolerated + 1:
            return 0.0
        plain = Levenshtein.distance(read, keyword.joined)
        with_confusions = Levenshtein.distance(_with_ocr_confusions(read, keyword.has_digits), keyword.joined_confused)
        errors = min(plain, with_confusions + 0.5) if with_confusions < plain else plain
        if errors > tolerated:
            return 0.0

    # 2. ressemblance correspondante
    if errors == 0:
        value = 1.0
    elif errors <= 0.25:
        value = 0.97
    else:
        value = 1 - 0.12 * errors * (8 / max(keyword.length, 8))
        if from_pdf:
            value = min(value, 0.9)
        elif handwritten:
            value = min(value, 0.8)                          # écriture manuscrite approchée : au mieux « à vérifier »

    # 3. accents et sigles, mot par mot
    if same_split:
        for token, keyword_raw in zip(window, keyword.raw_parts):
            read_raw = token.get("r", token["t"])
            accent_differs = (_has_accent(keyword_raw) and normalize(keyword_raw) == normalize(read_raw)
                              and keyword_raw.lower() != read_raw.lower())
            if accent_differs:
                short = len(normalize(keyword_raw)) <= 6
                if from_pdf:
                    value *= (0.85 if read_raw.isupper() else 0.72) if short else 0.97
                elif short:
                    value *= 0.9
            if len(keyword_raw) >= 2 and keyword_raw.isupper() and read_raw.islower():
                value *= 0.6 if from_pdf else 0.75          # « IA » lu « ia »
    return max(0.0, min(1.0, value))


def reading_confidence(keyword: Keyword, window: list[dict], exact: bool) -> float:
    confidence = sum(t["c"] for t in window) / len(window) / 100.0
    # Bonus réservé à Tesseract, qui recopie ce qu'il voit : retrouver exactement un mot long par hasard est
    # très improbable, donc la confiance manquante est divisée par deux tous les 3 caractères au-delà de 3.
    # (TrOCR peut « deviner » un mot plausible : pas de bonus pour l'écriture manuscrite.)
    if window[0]["s"] == "ocr" and exact:
        confidence = 1 - (1 - confidence) * 0.5 ** (max(0, keyword.length - 3) / 3)
    return confidence


# =========================================================================== le mot-clé est-il un mot entier ?
# « pour » ne doit pas être trouvé dans « pourquoi », même quand ce mot arrive découpé en morceaux :
#   - coupure en fin de ligne            « pour- » puis « quoi » à la ligne suivante
#   - trait d'union invisible du PDF     « pour­quoi »
#   - OCR qui insère une espace          « pour quoi » alors que les lettres se touchent sur l'image
# Restent trouvés : l'élision (« l'apprentissage », « d'ingénieur »). La partie d'un mot composé
# (« Master » dans « Master-Recherche ») est proposée « à vérifier ».
ELISIONS = {"l", "d", "j", "m", "n", "s", "t", "c", "qu", "jusqu", "lorsqu", "puisqu", "quoiqu", "presqu"}
HYPHENS = "-‐‑"
APOSTROPHES = "'’ʼ"


def _separators(stream: list[dict]) -> list:
    """separators[k] : les caractères entre le token k-1 et le token k s'ils viennent du même mot lu, sinon None."""
    separators, cursor = [None] * len(stream), 0
    for k, token in enumerate(stream):
        word = token["t"]
        same_word = k > 0 and token["w"] == stream[k - 1]["w"]
        position = word.find(token["r"], cursor if same_word else 0)
        if same_word:
            position = position if position >= 0 else cursor
            separators[k] = word[cursor:position]
        else:
            position = max(position, 0)
        cursor = position + len(token["r"])
    return separators


def _ends_with_line_break_hyphen(token: dict) -> bool:
    """« pour- » en fin de ligne : le mot continue à la ligne suivante."""
    word = token["t"].rstrip()
    return word.endswith(tuple(HYPHENS)) and word.strip(HYPHENS + " ") == token["r"]


def _glued(left: dict, right: dict) -> bool:
    """Deux mots lus séparément mais collés sur la page : même ligne, presque pas d'espace entre eux."""
    l_left, l_top, l_right, l_bottom = left["b"]
    r_left, r_top, r_right, r_bottom = right["b"]
    if left["b"] == right["b"]:
        return False
    vertical_overlap = min(l_bottom, r_bottom) - max(l_top, r_top)
    if vertical_overlap < 0.5 * min(l_bottom - l_top, r_bottom - r_top):
        return False                                          # pas sur la même ligne
    letter_width = (l_right - l_left) / max(1, len(left["t"].strip()))
    return 0 <= r_left - l_right < 0.25 * letter_width


def _surroundings(stream: list[dict], separators: list, start: int, end: int) -> str:
    """
    Ce qui entoure les mots stream[start:end] :
      "seul"     un ou des mots entiers ;
      "composé"  une partie de mot composé avec un vrai trait d'union ;
      "dedans"   un morceau d'un mot plus long : ce n'est pas une occurrence.
    """
    verdict = "seul"
    can_check_gaps = stream[start]["s"] != "manuscrit"      # pour l'écriture manuscrite, les positions sont estimées
    if start > 0:
        before, separator = stream[start - 1], separators[start]
        if separator is not None:                            # même mot lu, juste avant
            if any(c in APOSTROPHES for c in separator) and before["n"] in ELISIONS:
                pass                                         # élision : « l'apprentissage »
            elif separator and all(c in HYPHENS for c in separator):
                verdict = "composé"
            else:
                return "dedans"
        elif _ends_with_line_break_hyphen(before):
            return "dedans"
        elif can_check_gaps and _glued(before, stream[start]):
            return "dedans"
    if end < len(stream):
        after, separator, last = stream[end], separators[end], stream[end - 1]
        if separator is not None:                            # même mot lu, juste après
            if separator and all(c in HYPHENS for c in separator):
                verdict = "composé"
            else:
                return "dedans"
        elif _ends_with_line_break_hyphen(last):
            return "dedans"
        elif can_check_gaps and _glued(last, after):
            return "dedans"
    return verdict


# =========================================================================== recherche dans un document
def _streams(tokens: list[dict]):
    """Regroupe les tokens qui se suivent : même page, même source, même lecture."""
    for (page, source, _reading), group in groupby(tokens, key=lambda t: (t["p"], t["s"], t.get("k", 0))):
        yield page, source, list(group)


def _union(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _same_place(a: list[float], b: list[float]) -> bool:
    """Deux boîtes désignent-elles le même endroit de la page (un même mot lu deux fois) ?"""
    overlap_w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    overlap_h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    shared = overlap_w * overlap_h
    if shared == 0:
        return False
    area_a = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
    return shared / (area_a + area_b - shared) > 0.25 or shared / min(area_a, area_b) > 0.6


def _context(stream: list[dict], start: int, end: int) -> str:
    """L'extrait montré à l'utilisateur, le mot trouvé entre [[ ]]."""
    def words(tokens):
        result, last_word = [], None
        for t in tokens:
            if t["w"] != last_word:
                result.append(t["t"])
                last_word = t["w"]
        return " ".join(result)
    before = words(stream[max(0, start - CONTEXT_WORDS):start])
    after = words(stream[end:end + CONTEXT_WORDS])
    return f"{before} [[{words(stream[start:end])}]] {after}".strip()


def find_keyword(tokens: list[dict], term: str) -> list[dict]:
    """
    Toutes les occurrences d'un mot-clé dans un document. Chaque occurrence :
      {"page", "source", "similarity" (0-100), "certain", "read_conf" (0-100), "score" (0-1),
       "text" (mot lu), "context" (extrait), "box" (position)}
    """
    keyword = Keyword(term)
    if not keyword.parts:
        return []
    # fenêtres de 1, 2 ou 3 mots : un mot-clé de 2 mots peut avoir été lu en 1 (mots collés) ou 3 (césure)
    n = len(keyword.parts)
    window_sizes = sorted({max(1, n - 1), n, n + 1})

    found = []
    for page, source, stream in _streams(tokens):
        separators = _separators(stream)
        candidates = []
        for start in range(len(stream)):
            for size in window_sizes:
                end = start + size
                if end > len(stream):
                    continue
                window = stream[start:end]
                sim = similarity(keyword, window)
                if sim <= 0:
                    continue
                around = _surroundings(stream, separators, start, end)
                if around == "dedans":
                    continue                      # morceau d'un mot plus long
                if around == "composé":
                    sim = min(sim, 0.8)           # à vérifier, jamais présent d'office
                exact = "".join(t["n"] for t in window) == keyword.joined
                candidates.append((sim * reading_confidence(keyword, window, exact), sim, start, end))

        # les meilleures fenêtres d'abord ; un mot lu ne sert qu'à une seule occurrence
        candidates.sort(key=lambda c: (-c[0], c[3] - c[2]))
        used = set()
        for score, sim, start, end in candidates:
            if used.intersection(range(start, end)):
                continue
            used.update(range(start, end))
            window = stream[start:end]
            found.append({
                "page": page, "source": source,
                "similarity": round(sim * 100, 1),
                "certain": sim >= CERTAIN_SIMILARITY,
                "read_conf": round(sum(t["c"] for t in window) / len(window), 1),
                "score": round(score, 4),
                "text": " ".join(dict.fromkeys(t["t"] for t in window)),
                "context": _context(stream, start, end),
                "box": _union([t["b"] for t in window]),
            })

    # un même endroit lu plusieurs fois (texte du PDF + OCR, ou plusieurs lectures) = une seule occurrence
    found.sort(key=lambda o: -o["score"])
    kept = []
    for occurrence in found:
        if not any(k["page"] == occurrence["page"] and _same_place(k["box"], occurrence["box"]) for k in kept):
            kept.append(occurrence)
    kept.sort(key=lambda o: (o["page"], o["box"][1], o["box"][0]))
    return kept
