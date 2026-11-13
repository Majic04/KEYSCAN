"""
Logo de KeyScan : une loupe posée sur un document ; dans la lentille, la lettre K grossie.
Couleurs de l'interface : encre #1C2B3F, papier blanc, surligneur jaune #FFE35A, stylo bleu #2B4ACB.

Produit :
  static/logo.svg              logo seul (en-tête de l'application, écran du code)
  build/icons/keyscan.png      icône d'application 1024 px (carré arrondi bleu)
  build/icons/keyscan.icns     Mac
  build/icons/keyscan.ico      Windows
Le K est tracé à partir de la police Syne (licence OFL) ; il faut fontTools + brotli + cairosvg pour régénérer.
"""
import io
import os

import cairosvg
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INK, PAPER, HL, PEN, RULE = "#1C2B3F", "#FFFFFF", "#FFE35A", "#2B4ACB", "#C5CED9"


def k_path(cx, cy, height, max_width):
    """Contour du K (Syne extra-gras), centré en (cx, cy), de hauteur donnée, en coordonnées SVG."""
    font = TTFont(os.path.join(ROOT, "static", "fonts", "syne-800.woff2"))
    gs = font.getGlyphSet()
    name = font.getBestCmap()[ord("K")]
    bp = BoundsPen(gs)
    gs[name].draw(bp)
    x0, y0, x1, y1 = bp.bounds
    s = min(height / (y1 - y0), max_width / (x1 - x0))
    dx = cx - (x0 + x1) / 2 * s
    dy = cy + (y0 + y1) / 2 * s
    pen = SVGPathPen(gs)
    gs[name].draw(TransformPen(pen, (s, 0, 0, -s, dx, dy)))   # l'axe y des polices monte, celui du SVG descend
    return pen.getCommands()


def mark(dark_ring=INK):
    """Dessin du logo dans un repère 1000 × 1000."""
    lens_c, lens_r = (585, 585), 235
    lines = "".join(
        f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{RULE}" stroke-width="26" stroke-linecap="round"/>'
        for x0, x1, y in [(225, 560, 260), (225, 600, 335), (225, 480, 410), (225, 380, 485), (225, 330, 560), (225, 340, 635)])
    return f"""
  <path d="M180 120 h360 l130 130 v600 a44 44 0 0 1 -44 44 h-446 a44 44 0 0 1 -44 -44 v-686 a44 44 0 0 1 44 -44 z"
        fill="{PAPER}" stroke="{INK}" stroke-width="30" stroke-linejoin="round"/>
  <path d="M540 120 v86 a44 44 0 0 0 44 44 h86" fill="none" stroke="{INK}" stroke-width="30" stroke-linejoin="round"/>
  {lines}
  <line x1="{lens_c[0] + 170}" y1="{lens_c[1] + 170}" x2="895" y2="895" stroke="{dark_ring}" stroke-width="86" stroke-linecap="round"/>
  <circle cx="{lens_c[0]}" cy="{lens_c[1]}" r="{lens_r}" fill="{HL}" stroke="{dark_ring}" stroke-width="44"/>
  <path d="{k_path(lens_c[0] + 6, lens_c[1] + 2, 255, 245)}" fill="{INK}"/>
  <path d="M{lens_c[0] - 150} {lens_c[1] - 95} a{lens_r - 60} {lens_r - 60} 0 0 1 95 -78" fill="none" stroke="#FFFFFF" stroke-opacity=".75"
        stroke-width="22" stroke-linecap="round"/>"""


def logo_svg():
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="80 60 880 880" role="img" aria-label="KeyScan">{mark()}\n</svg>\n'


def icon_svg():
    # icône d'application : carré arrondi bleu stylo, logo au centre (≈ 80 % de la surface utile, grille macOS)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
  <rect x="92" y="92" width="840" height="840" rx="190" fill="{PEN}"/>
  <g transform="translate(82 74) scale(0.8)">{mark()}</g>
</svg>
"""


if __name__ == "__main__":
    with open(os.path.join(ROOT, "static", "logo.svg"), "w", encoding="utf-8") as f:
        f.write(logo_svg())
    png = cairosvg.svg2png(bytestring=icon_svg().encode(), output_width=1024, output_height=1024)
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    out = os.path.join(ROOT, "build", "icons")
    os.makedirs(out, exist_ok=True)
    img.save(os.path.join(out, "keyscan.png"))
    img.save(os.path.join(out, "keyscan.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(os.path.join(out, "keyscan.icns"))
    # favicon de l'interface
    fav = cairosvg.svg2png(bytestring=logo_svg().encode(), output_width=64, output_height=64)
    with open(os.path.join(ROOT, "static", "favicon.png"), "wb") as f:
        f.write(fav)
    print("logo et icônes régénérés")
