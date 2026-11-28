"""
Les tableaux d'une page : où sont-ils ? (pour dire si un mot-clé a été lu DANS un tableau)

Une zone de tableau est une boîte [gauche, haut, droite, bas], de 0 à 1, dans le même repère que les mots lus
(voir text.py, clé « b »).

  - PDF avec texte : PyMuPDF trouve les tableaux dessinés (traits du tableau) : pdf_tables(page).
  - Scan, photo : on cherche les traits horizontaux et verticaux qui se croisent en grille : image_tables(image).

Un cadre seul (2 traits horizontaux + 2 verticaux : un encadré, le bord de la page) n'est pas un tableau :
il faut au moins deux cases. Un tableau sans aucun trait (colonnes seulement alignées) n'est pas repéré.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

MIN_CELLS = 2                 # un tableau a au moins 2 cases (sinon : un simple cadre)
WORK_WIDTH = 1200             # l'image est réduite à cette largeur pour chercher les traits
H_LINE = 0.06                 # un trait horizontal fait au moins 6 % de la largeur de la page
V_LINE = 0.02                 # un trait vertical au moins 2 % de la hauteur (une ligne de tableau)
INK = 160                     # en dessous de ce gris (0-255), un pixel est de l'encre
TOLERANCE = 0.006             # écart toléré entre deux traits qui se croisent (part de la page)


# =========================================================================== PDF avec texte
def pdf_tables(page) -> list[list[float]]:
    """Les tableaux dessinés d'une page PDF (PyMuPDF), en boîtes de 0 à 1."""
    try:
        found = page.find_tables().tables
    except Exception:  # noqa: BLE001 — page étrange : on ne bloque pas la lecture pour un tableau
        return []
    width, height = page.rect.width, page.rect.height
    boxes = []
    for table in found:
        if table.row_count * table.col_count < MIN_CELLS:
            continue
        x0, y0, x1, y1 = table.bbox
        boxes.append([round(x0 / width, 4), round(y0 / height, 4), round(x1 / width, 4), round(y1 / height, 4)])
    return boxes


# =========================================================================== scan, photo
def long_runs(mask: np.ndarray, length: int) -> np.ndarray:
    """Les pixels qui font partie d'une suite d'au moins « length » pixels d'encre sur leur ligne (axe 1)."""
    rows, cols = mask.shape
    if length < 1 or length > cols:
        return np.zeros_like(mask)
    sums = np.cumsum(np.pad(mask.astype(np.int32), ((0, 0), (1, 0))), axis=1)
    full = (sums[:, length:] - sums[:, :-length]) == length          # une suite complète commence ici
    # un pixel est couvert si une suite complète commence dans les « length » pixels qui le précèdent
    starts = np.pad(full.astype(np.int32), ((0, 0), (length - 1, length - 1)))
    sums = np.cumsum(np.pad(starts, ((0, 0), (1, 0))), axis=1)
    return (sums[:, length:] - sums[:, :-length])[:, :cols] > 0


def _segments(mask: np.ndarray) -> list[list[int]]:
    """Les traits d'un masque, ligne par ligne : [rang, début, fin], les rangs voisins qui se recouvrent fusionnés."""
    pieces = []
    for row in np.nonzero(mask.any(axis=1))[0]:
        line = np.concatenate(([0], mask[row].astype(np.int8), [0]))
        edges = np.flatnonzero(np.diff(line))
        pieces += [[int(row), int(start), int(end)] for start, end in zip(edges[::2], edges[1::2])]
    merged: list[list[int]] = []                    # [premier rang, dernier rang, début, fin]
    for row, start, end in pieces:
        for line in merged:
            if row - line[1] <= 2 and min(end, line[3]) - max(start, line[2]) > 0.5 * (end - start):
                line[1], line[2], line[3] = row, min(start, line[2]), max(end, line[3])
                break
        else:
            merged.append([row, row, start, end])
    return [[(first + last) / 2, start, end] for first, last, start, end in merged]


def image_tables(image: Image.Image) -> list[list[float]]:
    """Les tableaux à traits d'une image de page, en boîtes de 0 à 1 (même repère que l'image donnée)."""
    gray = image.convert("L")
    scale = min(1.0, WORK_WIDTH / gray.width)
    if scale < 1:
        gray = gray.resize((round(gray.width * scale), round(gray.height * scale)), Image.BILINEAR)
    ink = np.asarray(gray) < INK
    height, width = ink.shape
    horizontal = _segments(long_runs(ink, max(8, int(H_LINE * width))))            # [y, x0, x1]
    vertical = _segments(long_runs(ink.T, max(8, int(V_LINE * height))))            # [x, y0, y1]
    if len(horizontal) < 2 or len(vertical) < 2:
        return []

    # les traits qui se croisent forment un même tableau (union de groupes)
    tolerance = TOLERANCE * max(width, height)
    lines = [("h", h) for h in horizontal] + [("v", v) for v in vertical]
    group = list(range(len(lines)))

    def root(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i

    for i, (_, (y, x0, x1)) in enumerate(lines[:len(horizontal)]):
        for j, (_, (x, y0, y1)) in enumerate(lines[len(horizontal):], start=len(horizontal)):
            if x0 - tolerance <= x <= x1 + tolerance and y0 - tolerance <= y <= y1 + tolerance:
                group[root(i)] = root(j)

    tables: dict[int, dict] = {}
    for i, (kind, line) in enumerate(lines):
        tables.setdefault(root(i), {"h": [], "v": []})[kind].append(line)
    boxes = []
    for parts in tables.values():
        rows, cols = len(parts["h"]) - 1, len(parts["v"]) - 1
        if rows < 1 or cols < 1 or rows * cols < MIN_CELLS:
            continue
        left = min([x0 for _, x0, _ in parts["h"]] + [x for x, _, _ in parts["v"]])
        right = max([x1 for _, _, x1 in parts["h"]] + [x for x, _, _ in parts["v"]])
        top = min([y for y, _, _ in parts["h"]] + [y0 for _, y0, _ in parts["v"]])
        bottom = max([y for y, _, _ in parts["h"]] + [y1 for _, _, y1 in parts["v"]])
        boxes.append([round(left / width, 4), round(top / height, 4), round(right / width, 4), round(bottom / height, 4)])
    return boxes


# =========================================================================== un mot dans un tableau ?
def in_table(box: list[float] | None, tables: list[list[float]] | None) -> bool:
    """Le centre du mot est-il dans une des zones de tableau de sa page ?"""
    if not box or not tables:
        return False
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(left <= x <= right and top <= y <= bottom for left, top, right, bottom in tables)
