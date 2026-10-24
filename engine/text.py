"""
Le texte lu dans un document, mot par mot.

Chaque mot lu devient un « token » : un petit dictionnaire. Les clés sont volontairement courtes
(une lettre) car des milliers de tokens sont enregistrés pour chaque document.

    clé   signification                                                   exemple
    ----  --------------------------------------------------------------  ----------------------
    "t"   le mot tel qu'il a été lu, ponctuation comprise                  "Réseaux,"
    "r"   la partie du mot correspondant à ce token (casse d'origine)      "Réseaux"
    "n"   la même partie, normalisée : minuscules, sans accents            "reseaux"
    "c"   confiance de lecture, de 0 à 100 (100 = texte du PDF)            87.0
    "p"   numéro de page (la première page est 1)                          1
    "s"   source : "texte" (PDF), "ocr" (Tesseract), "manuscrit" (TrOCR)  "ocr"
    "w"   numéro du mot lu (un mot comme « Sous-Traitance » donne          12
          deux tokens qui partagent ce numéro)
    "b"   position sur la page [gauche, haut, droite, bas], de 0 à 1        [0.1, 0.2, 0.3, 0.22]
    "k"   numéro de la lecture (une page scannée peut être lue plusieurs   0
          fois, avec des réglages différents)
    "x"   présent (= 1) si le token ne doit pas compter dans la qualité    1
          de lecture (lecture secondaire, ou lecture ratée)
"""
from __future__ import annotations

import re
import unicodedata

# Une partie de mot = une suite de lettres ou de chiffres, suivie éventuellement de « ++ » ou « # »
# pour garder les noms de langages : C++, C#, F#.
_PART_IN_RAW_TEXT = re.compile(r"[^\W_]+(?:\+\+|#)?")
_PART_IN_NORMALIZED_TEXT = re.compile(r"[a-z0-9]+(?:\+\+|#)?")


def normalize(text: str) -> str:
    """Minuscules, sans accents, ligatures ouvertes : « Œuvre Été » → « oeuvre ete »."""
    text = text.lower().replace("œ", "oe").replace("æ", "ae")
    text = unicodedata.normalize("NFKD", text)                # « é » devient « e » + accent séparé
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def word_parts(text: str) -> list[tuple[str, str]]:
    """
    Découpe un texte en parties de mots : [(partie telle qu'écrite, partie normalisée)].
        « Sous-Traitance, »  →  [("Sous", "sous"), ("Traitance", "traitance")]
        « l'IA »             →  [("l", "l"), ("IA", "ia")]
    """
    parts = []
    for match in _PART_IN_RAW_TEXT.finditer(text):
        raw = match.group(0)
        for normalized in _PART_IN_NORMALIZED_TEXT.findall(normalize(raw)):
            parts.append((raw, normalized))
    return parts


def normalized_words(text: str) -> list[str]:
    """Les parties de mots normalisées d'un texte : « Réseaux de neurones » → ["reseaux", "de", "neurones"]."""
    return [normalized for _, normalized in word_parts(text)]


def make_tokens(word: str, *, confidence: float, page: int, source: str, word_id: int, box: list[float],
                reading: int = 0, secondary: bool = False) -> list[dict]:
    """Les tokens d'un mot lu (un mot composé en donne plusieurs). Voir le tableau en haut du fichier."""
    tokens = []
    for raw, normalized in word_parts(word):
        token = {"t": word, "r": raw, "n": normalized, "c": float(confidence), "p": page, "s": source,
                 "w": word_id, "b": box, "k": reading}
        if secondary:
            token["x"] = 1
        tokens.append(token)
    return tokens


def next_word_id(tokens: list[dict]) -> int:
    """Numéro à donner au prochain mot lu."""
    return tokens[-1]["w"] + 1 if tokens else 0
