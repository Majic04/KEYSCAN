"""
Recherche des mots-clés dans les tokens extraits, et calcul du score de confiance.

Score d'une occurrence = ressemblance × confiance de lecture

1. Ressemblance (0-1) entre le texte lu et le mot-clé
   - écriture identique (aux majuscules et accents près) .................. 1
   - même mot au singulier / pluriel (« réseau » / « réseaux ») ......... 0,97
   - couche texte native (pas d'erreur de lecture possible) :
       une seule faute de frappe tolérée, et seulement sur les mots de 8 lettres ou plus
   - texte lu par OCR : erreurs de lecture tolérées selon la longueur du mot
       ≤ 4 lettres : aucune ; 5-6 : seulement une confusion typique de l'OCR
       (rn↔m, cl↔d, 0↔o, 1/i↔l, 5↔s, vv↔w) ; 7-10 : 1,5 erreur ; > 10 : 2,5 erreurs.
       Une confusion typique coûte une demi-erreur, une autre erreur en coûte une.
   - ajustements :
       accents différents sur un mot court (« thèse » / « these ») .... × 0,72 (texte natif)
       sigle en majuscules lu en minuscules (« IA » / « ia ») .......... × 0,6

2. Confiance de lecture (0-1)
   - couche texte native saine : 1 ; couche texte corrompue : 0,2
   - écriture manuscrite (TrOCR) : probabilité moyenne des caractères lus, sans recalibrage
     (un modèle de langage peut produire un mot plausible : une correspondance exacte n'y prouve pas autant)
   - OCR : confiance de Tesseract, recalibrée pour les correspondances exactes :
     retrouver exactement un mot long par hasard est très improbable, donc la confiance
     manquante est divisée par deux tous les 3 caractères au-delà de 3.
       c' = 1 - (1 - c) × 0,5^((L - 3) / 3)

Score d'un mot-clé pour un dossier (plusieurs occurrences possibles) :
    S = 1 - (1 - s_max) × Π_autres (1 - s_i / 2)
"""
from __future__ import annotations

from itertools import groupby

from rapidfuzz.distance import Levenshtein

from .extract import normalize, split_raw

CONTEXT_WORDS = 7
_CONFUSIONS = [("rn", "m"), ("vv", "w"), ("cl", "d"), ("0", "o"), ("1", "l"), ("i", "l"), ("5", "s")]


# --------------------------------------------------------------------------- outils
def _confuse(s: str, keep_digits: bool) -> str:
    """Forme canonique qui confond les caractères que l'OCR mélange souvent."""
    for a, b in _CONFUSIONS:
        if keep_digits and a.isdigit():
            continue
        s = s.replace(a, b)
    return s


def _morph_eq(a: str, b: str) -> bool:
    """Même mot au singulier/pluriel près (s, x, es)."""
    if a == b:
        return True
    lo, hi = sorted((a, b), key=len)
    return len(lo) >= 3 and hi in (lo + "s", lo + "x", lo + "es")


def edit_budget(length: int) -> float:
    if length <= 4:
        return 0.0
    if length <= 6:
        return 0.5
    if length <= 10:
        return 1.5
    return 2.5


def handwriting_budget(length: int) -> float:
    """TrOCR se trompe plus que Tesseract (et autrement) : tolérance plus large, jamais pour les mots très courts."""
    if length <= 3:
        return 0.0
    if length <= 6:
        return 1.0
    if length <= 10:
        return 2.0
    return 3.5


def _has_accent(s: str) -> bool:
    return normalize(s) != s.lower()


class Keyword:
    def __init__(self, term: str):
        parts = split_raw(term)
        self.term = term
        self.raw = [r for r, _ in parts]
        self.norm = [n for _, n in parts]
        self.joined = "".join(self.norm)
        self.L = len(self.joined)
        self.m = len(self.norm)
        self.digits = any(ch.isdigit() for ch in self.joined)
        self.conf = _confuse(self.joined, self.digits)
        self.budget = edit_budget(self.L)


# --------------------------------------------------------------------------- ressemblance d'une fenêtre de tokens
def similarity(kw: Keyword, win: list[dict]) -> float:
    """Ressemblance (0-1) entre une fenêtre de tokens consécutifs et le mot-clé ; 0 si trop différent."""
    native = win[0]["s"] == "texte"
    hand = win[0]["s"] == "manuscrit"
    budget = handwriting_budget(kw.L) if hand else kw.budget
    joined = "".join(t["n"] for t in win)
    same_count = len(win) == kw.m

    if joined == kw.joined:
        eff = 0.0
    elif same_count and all(_morph_eq(t["n"], k) for t, k in zip(win, kw.norm)):
        eff = 0.25 if native else 0.5          # singulier / pluriel
    elif native:
        if kw.L >= 8 and Levenshtein.distance(joined, kw.joined, score_cutoff=1) <= 1:
            eff = 1.0                           # faute de frappe
        else:
            return 0.0
    else:
        if budget == 0 or abs(len(joined) - kw.L) > budget + 1:
            return 0.0
        d_raw = Levenshtein.distance(joined, kw.joined)
        d_conf = Levenshtein.distance(_confuse(joined, kw.digits), kw.conf)
        eff = min(d_raw, d_conf + 0.5) if d_conf < d_raw else d_raw
        if eff > budget:
            return 0.0

    if eff == 0:
        factor = 1.0
    elif eff <= 0.25:
        factor = 0.97
    else:
        factor = 1 - 0.12 * eff * (8 / max(kw.L, 8))
        if native:
            factor = min(factor, 0.9)
        elif hand:
            factor = min(factor, 0.8)       # écriture manuscrite approchée : au mieux « à vérifier », jamais « présent »

    # ajustements accents / sigles, mot par mot quand le découpage correspond
    if same_count:
        for t, kraw in zip(win, kw.raw):
            wraw = t.get("r", t["t"])
            if _has_accent(kraw) and normalize(kraw) == normalize(wraw) and kraw.lower() != wraw.lower():
                short = len(normalize(kraw)) <= 6
                if native:
                    factor *= (0.85 if wraw.isupper() else 0.72) if short else 0.97
                elif short:
                    factor *= 0.9
            if len(kraw) >= 2 and kraw.isupper() and wraw.islower():
                factor *= 0.6 if native else 0.75
    return max(0.0, min(1.0, factor))


def read_confidence(kw: Keyword, win: list[dict], exact: bool) -> float:
    c = sum(t["c"] for t in win) / len(win) / 100.0
    # bonus réservé à Tesseract, qui recopie ce qu'il voit ; TrOCR peut « deviner » un mot plausible,
    # sa confiance (probabilité du modèle) est donc utilisée telle quelle
    if win[0]["s"] == "ocr" and exact:
        c = 1 - (1 - c) * 0.5 ** (max(0, kw.L - 3) / 3)
    return c


# --------------------------------------------------------------------------- recherche
def _streams(tokens: list[dict]):
    """Regroupe les tokens par (page, source, lecture) en conservant l'ordre de lecture."""
    key = lambda t: (t["p"], t["s"], t.get("k", 0))
    for k, grp in groupby(tokens, key=key):
        yield k, list(grp)


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter == 0:
        return 0.0
    area = lambda r: max(1e-9, (r[2] - r[0]) * (r[3] - r[1]))
    return inter / (area(a) + area(b) - inter)


def _overlap(a, b):
    """Part de la plus petite boîte couverte par l'autre (une même zone lue deux fois)."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = lambda r: max(1e-9, (r[2] - r[0]) * (r[3] - r[1]))
    return ix * iy / min(area(a), area(b))


def _context(stream: list[dict], i: int, j: int) -> str:
    def words(sub):
        out, last = [], None
        for t in sub:
            if t["w"] != last:
                out.append(t["t"])
                last = t["w"]
        return " ".join(out)

    return f"{words(stream[max(0, i - CONTEXT_WORDS):i])} [[{words(stream[i:j])}]] {words(stream[j:j + CONTEXT_WORDS])}".strip()


def find_keyword(tokens: list[dict], term: str) -> list[dict]:
    """Toutes les occurrences (dédoublonnées) d'un mot-clé dans les tokens d'un document."""
    kw = Keyword(term)
    if not kw.m:
        return []
    spans = sorted({max(1, kw.m - 1), kw.m, kw.m + 1})  # mot coupé (césure) ou deux mots collés par l'OCR

    found = []
    for (page, source, _), stream in _streams(tokens):
        cands = []
        for i in range(len(stream)):
            for span in spans:
                j = i + span
                if j > len(stream):
                    continue
                win = stream[i:j]
                sim = similarity(kw, win)
                if sim <= 0:
                    continue
                exact = "".join(t["n"] for t in win) == kw.joined
                score = sim * read_confidence(kw, win, exact)
                cands.append((score, sim, i, j))

        cands.sort(key=lambda c: (-c[0], c[3] - c[2]))
        used: set[int] = set()
        for score, sim, i, j in cands:
            if used.intersection(range(i, j)):
                continue
            used.update(range(i, j))
            win = stream[i:j]
            found.append({
                "page": page,
                "source": source,
                "similarity": round(sim * 100, 1),
                "certain": sim >= CERTAIN_SIM,
                "read_conf": round(sum(t["c"] for t in win) / len(win), 1),
                "score": round(score, 4),
                "text": " ".join(dict.fromkeys(t["t"] for t in win)),
                "context": _context(stream, i, j),
                "box": _union([t["b"] for t in win]),
            })

    # une même zone lue plusieurs fois (couche texte + OCR, ou plusieurs lectures OCR) = une seule occurrence
    found.sort(key=lambda o: -o["score"])
    kept: list[dict] = []
    for o in found:
        if any(k["page"] == o["page"] and (_iou(k["box"], o["box"]) > 0.25 or _overlap(k["box"], o["box"]) > 0.6) for k in kept):
            continue
        kept.append(o)
    kept.sort(key=lambda o: (o["page"], o["box"][1], o["box"][0]))
    return kept


# Une occurrence est « certaine » quand le mot lu est le mot-clé lui-même : identique, au pluriel près,
# ou à une confusion typique de l'OCR près (rn/m, 0/o…). Faute de frappe, accent manquant sur un mot court
# (« these » pour « thèse »), casse d'un sigle ou lecture manuscrite approchée : occurrence « approchante ».
CERTAIN_SIM = 0.94


def aggregate(occ: list[dict]) -> tuple[float, bool]:
    """
    Score (0-100) d'un mot-clé à partir de ses occurrences, et s'il existe au moins une occurrence certaine.
      - les occurrences certaines se renforcent entre elles (plusieurs lectures concordantes) ;
      - les occurrences approchantes ne se cumulent JAMAIS : 3 fois « these » ne valent pas « thèse ».
        Elles comptent seulement pour leur meilleure valeur, et ne peuvent pas donner « présent » (voir decide).
    """
    sure = [o["score"] for o in occ if o.get("certain", True)]
    approx = [o["score"] for o in occ if not o.get("certain", True)]
    score = max(combine(sure), max(approx, default=0.0))
    return round(score * 100, 1), bool(sure)


def combine(scores: list[float]) -> float:
    """Agrège les scores de plusieurs occurrences en un score unique (0-1)."""
    if not scores:
        return 0.0
    s = sorted(scores, reverse=True)
    rest = 1.0
    for x in s[1:]:
        rest *= 1 - x / 2
    return 1 - (1 - s[0]) * rest


def is_fragile(term: str, pages) -> bool:
    """
    Cas où l'absence d'un mot-clé ne peut jamais être affirmée avec certitude (« absent douteux ») :
      - le dossier contient de l'écriture manuscrite lue par TrOCR (environ 1 caractère sur 8 mal lu) ;
      - mot-clé très court (≤ 2 caractères : « IA », « C# », « R ») dans un document lu par OCR :
        une seule lettre mal lue suffit à le manquer.
    pages : descriptions des pages (« mode », « manuscrit ») de tous les documents du dossier.
    """
    if any(p.get("manuscrit") for p in pages):
        return True
    return Keyword(term).L <= 2 and any(p.get("mode") in ("ocr", "mixte") for p in pages)


def decide(score_pct: float, quality_pct: float, present_thr: float, review_thr: float, min_quality: float,
           fragile: bool = False, certain: bool = True) -> str:
    """
    Décision rendue pour un mot-clé dans un dossier.
      present        : score ≥ seuil « présent » ET au moins une occurrence certaine (certain)
      a_verifier     : score entre les deux seuils — contrôle humain conseillé
      absent         : score < seuil « à vérifier » et documents bien lus
      absent_douteux : rien trouvé, mais lecture des documents trop mauvaise pour conclure
                       (ou mot-clé très court dans un document lu par OCR, voir is_fragile,
                       ou document du dossier impossible à lire)
    """
    if score_pct >= present_thr and certain:
        return "present"
    if score_pct >= review_thr:
        return "a_verifier"
    if quality_pct < min_quality or fragile:
        return "absent_douteux"
    return "absent"


def evaluate(term: str, occ: list[dict], quality_pct: float, pages, present_thr: float = 85,
             review_thr: float = 50, min_quality: float = 70, unread: int = 0) -> tuple[float, str]:
    """
    Score (0-100) et décision pour un mot-clé dans un dossier — point d'entrée unique utilisé par
    l'application, l'export et la ligne de commande.
      occ     : occurrences trouvées dans les documents lus (find_keyword)
      pages   : descriptions des pages de ces documents (pour is_fragile)
      unread  : nombre de documents du dossier impossibles à lire (corrompus, protégés…) :
                une absence ne peut alors jamais être affirmée.
    """
    score, certain = aggregate(occ)
    if not certain:      # mot seulement approchant : le score reste sous le seuil « présent »
        score = min(score, float(max(0, int(present_thr) - 1)))
    fragile = unread > 0 or is_fragile(term, pages)
    return score, decide(score, quality_pct, present_thr, review_thr, min_quality, fragile=fragile, certain=certain)
