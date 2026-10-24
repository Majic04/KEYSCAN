"""
La décision pour un mot-clé dans un dossier : Présent, À vérifier, Absent ou Absence incertaine.

1. Score du mot-clé (0 à 100), à partir de ses occurrences dans tous les documents du dossier :
   - les occurrences « certaines » (le mot lu EST le mot-clé) se renforcent entre elles :
         S = 1 - (1 - meilleur score) × Π (1 - autre score / 2)
   - une occurrence seulement « approchante » (« these » pour « thèse », lecture manuscrite à peu près)
     ne se cumule jamais : trois « these » ne valent pas un « thèse ». Elle compte pour sa meilleure
     valeur, et le score reste sous le seuil « Présent ».

2. Décision (seuils réglables par chaque responsable) :
   Présent             score ≥ 85 et au moins une occurrence certaine
   À vérifier          score ≥ 50 (un mot proche a été lu)
   Absent              score < 50 et documents bien lus
   Absence incertaine  score < 50 mais l'absence ne peut pas être garantie :
                       lecture insuffisante, document illisible dans le dossier,
                       écriture manuscrite, ou mot-clé de 2 lettres dans un scan.
"""
from __future__ import annotations

from .search import Keyword

PRESENT, TO_CHECK, ABSENT, UNCERTAIN = "present", "a_verifier", "absent", "absent_douteux"
LABELS = {PRESENT: "Présent", TO_CHECK: "À vérifier", ABSENT: "Absent", UNCERTAIN: "Absence incertaine"}


def combine(scores: list[float]) -> float:
    """Plusieurs occurrences sûres d'un même mot se renforcent : 0,9 et 0,8 donnent 0,96."""
    if not scores:
        return 0.0
    best, *others = sorted(scores, reverse=True)
    missing = 1 - best
    for score in others:
        missing *= 1 - score / 2
    return 1 - missing


def keyword_score(occurrences: list[dict]) -> tuple[float, bool]:
    """Score (0-100) d'un mot-clé, et s'il existe au moins une occurrence certaine."""
    certain = [o["score"] for o in occurrences if o.get("certain", True)]
    approximate = [o["score"] for o in occurrences if not o.get("certain", True)]
    score = max(combine(certain), max(approximate, default=0.0))
    return round(score * 100, 1), bool(certain)


def absence_is_uncertain(term: str, pages: list[dict]) -> bool:
    """
    Cas où, même bien lu, un dossier ne permet pas d'affirmer qu'un mot est absent :
      - il contient de l'écriture manuscrite (environ une lettre sur huit est mal lue) ;
      - le mot-clé fait 2 lettres ou moins (« IA », « C# ») et un document a été lu par OCR :
        une seule lettre mal lue suffit à le manquer.
    pages : la description des pages de tous les documents du dossier.
    """
    if any(page.get("manuscrit") for page in pages):
        return True
    scanned = any(page.get("mode") in ("ocr", "mixte") for page in pages)
    return scanned and Keyword(term).length <= 2


def decide(score: float, quality: float, present_threshold: float, check_threshold: float, min_quality: float,
           uncertain: bool = False, certain: bool = True) -> str:
    if score >= present_threshold and certain:
        return PRESENT
    if score >= check_threshold:
        return TO_CHECK
    if quality < min_quality or uncertain:
        return UNCERTAIN
    return ABSENT


def evaluate(term: str, occurrences: list[dict], quality: float, pages: list[dict], present_thr: float = 85,
             review_thr: float = 50, min_quality: float = 70, unread: int = 0) -> tuple[float, str]:
    """
    Score (0-100) et décision pour un mot-clé dans un dossier. C'est le seul endroit où une décision est prise :
    l'application, l'export et la ligne de commande passent tous par ici.
      occurrences : trouvées dans les documents lus du dossier (search.find_keyword)
      quality     : qualité de lecture du document le moins bien lu (0-100)
      pages       : description des pages de ces documents
      unread      : nombre de documents du dossier impossibles à lire (corrompus, protégés…)
    """
    score, has_certain = keyword_score(occurrences)
    if not has_certain:
        score = min(score, float(max(0, int(present_thr) - 1)))   # mot seulement approchant : sous le seuil
    uncertain = unread > 0 or absence_is_uncertain(term, pages)
    return score, decide(score, quality, present_thr, review_thr, min_quality, uncertain, has_certain)
