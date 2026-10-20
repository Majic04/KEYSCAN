"""Génère un banc d'essai de documents « difficiles » avec la vérité terrain (mots-clés réellement présents)."""
import json, os, random, sys
try:
    import pymupdf as fitz  # PyMuPDF ≥ 1.24.3
except ImportError:  # anciennes versions de PyMuPDF
    import fitz
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
random.seed(7)
def _font(*candidates):
    for c in candidates:
        if os.path.exists(c):
            return c
    raise SystemExit("Police introuvable : ajoutez son chemin dans make_bench.py")


# polices disponibles selon le système (Linux, Windows, macOS)
SANS = _font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf",
             "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf")
SERIF = _font("/usr/share/fonts/truetype/freefont/FreeSerif.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
              "C:/Windows/Fonts/times.ttf", "/System/Library/Fonts/Supplemental/Times New Roman.ttf", SANS)

KW = ["apprentissage automatique", "TOEIC", "vision par ordinateur", "robotique", "thèse", "réseaux de neurones",
      "Master", "Python", "C++", "commande non linéaire", "IA", "stage"]
truth = {}


def img_text(lines, font=SANS, size=34, w=1500, fg=30, bg=255, pad=50, spacing=16):
    f = ImageFont.truetype(font, size)
    h = pad * 2 + len(lines) * (size + spacing) + 20
    im = Image.new("L", (w, h), bg)
    d = ImageDraw.Draw(im)
    y = pad
    for ln in lines:
        d.text((pad, y), ln, fill=fg, font=f)
        y += size + spacing
    return im


def noise(im, amount):
    px = im.load()
    for _ in range(int(im.width * im.height * amount)):
        x, y = random.randrange(im.width), random.randrange(im.height)
        px[x, y] = random.randint(0, 255)
    return im


def pdf_native(name, lines, keep_unicode=True):
    d = fitz.open(); p = d.new_page()
    p.insert_font(fontname="dv", fontfile=SANS)
    y = 80
    for ln in lines:
        p.insert_text((60, y), ln, fontname="dv", fontsize=12); y += 20
    path = os.path.join(OUT, name)
    d.save(path); d.close()
    if not keep_unicode:  # couche texte corrompue (police sans table ToUnicode)
        d = fitz.open(path)
        for x in range(1, d.xref_length()):
            if "ToUnicode" in d.xref_get_keys(x):
                d.xref_set_key(x, "ToUnicode", "null")
        d.save(path + ".tmp"); d.close(); os.replace(path + ".tmp", path)


def pdf_image(name, im, heading=None):
    tmp = os.path.join(OUT, "_tmp.png"); im.convert("RGB").save(tmp)
    d = fitz.open(); p = d.new_page()
    y0 = 60
    if heading:
        p.insert_text((60, 60), heading, fontsize=13); y0 = 80
    r = fitz.Rect(40, y0, 555, y0 + 515 * im.height / im.width)
    p.insert_image(r, filename=tmp); d.save(os.path.join(OUT, name)); d.close(); os.remove(tmp)


def add(name, kws):
    assert all(k in KW for k in kws), kws
    truth[name] = kws


# 1. texte natif propre
pdf_native("01_natif_propre.pdf", ["Relevé de notes – Master Robotique", "Module : Apprentissage automatique, mention Très bien",
                                   "Projets réalisés en Python et en C++.", "Stage de fin d'études chez Airbus."])
add("01_natif_propre.pdf", ["Master", "robotique", "apprentissage automatique", "Python", "C++", "stage"])
# 2. texte natif : faux amis
pdf_native("02_natif_pieges.pdf", ["Curriculum vitae – compétences : langage C, Java, JavaScript.",
                                   "These projects were completed during my bachelor's degree.",
                                   "Profil robuste et autonome, vision stratégique.", "Membre du club Mister Chips."])
add("02_natif_pieges.pdf", [])
# 3. césure en fin de ligne
pdf_native("03_natif_cesure.pdf", ["Le candidat a suivi un cours d'apprentis-", "sage automatique et de réseaux de neu-",
                                   "rones profonds. Il prépare une thèse en IA."])
add("03_natif_cesure.pdf", ["apprentissage automatique", "réseaux de neurones", "thèse", "IA"])
# 4. majuscules / sans accents
pdf_native("04_natif_casse.pdf", ["RÉSEAUX DE NEURONES ET VISION PAR ORDINATEUR", "Cours de commande non-lineaire (2e annee)",
                                  "Score TOEIC : 910"])
add("04_natif_casse.pdf", ["réseaux de neurones", "vision par ordinateur", "commande non linéaire", "TOEIC"])
# 5. couche texte corrompue (s'affiche bien, mais le texte copiable est illisible)
pdf_native("05_natif_corrompu.pdf", ["Master en robotique et apprentissage automatique.", "Développement en Python.",
                                     "Stage de six mois en laboratoire."], keep_unicode=False)
add("05_natif_corrompu.pdf", ["Master", "robotique", "apprentissage automatique", "Python", "stage"])
# 6. scan propre
pdf_image("06_scan_propre.pdf", noise(img_text(["Lettre de recommandation", "Elle maîtrise la vision par ordinateur",
                                                "et les réseaux de neurones.", "Score TOEIC : 925."]), .01))
add("06_scan_propre.pdf", ["vision par ordinateur", "réseaux de neurones", "TOEIC"])
# 7. scan basse résolution
im = img_text(["Attestation de réussite au Master.", "Mémoire sur la commande non linéaire", "des robots manipulateurs."], size=34)
im = im.resize((im.width // 3, im.height // 3), Image.BILINEAR)
pdf_image("07_scan_basse_res.pdf", im)
add("07_scan_basse_res.pdf", ["Master", "commande non linéaire"])
# 8. JPEG très compressé + bruit
im = noise(img_text(["Compétences : Python, C++,", "apprentissage automatique.", "Thèse en préparation."], size=32), .06)
im.convert("RGB").save(os.path.join(OUT, "08_jpeg_bruit.jpg"), quality=18)
add("08_jpeg_bruit.jpg", ["Python", "C++", "apprentissage automatique", "thèse"])
# 9. photo inclinée de 4°
im = img_text(["Stage de recherche en robotique mobile.", "Intelligence artificielle (IA) appliquée."])
im.rotate(4, expand=True, fillcolor=255, resample=Image.BICUBIC).convert("RGB").save(os.path.join(OUT, "09_incline_4.jpg"), quality=80)
add("09_incline_4.jpg", ["stage", "robotique", "IA"])
# 10. photo inclinée de -7°
im = img_text(["Master Vision par ordinateur,", "projet de réseaux de neurones."])
im.rotate(-7, expand=True, fillcolor=255, resample=Image.BICUBIC).convert("RGB").save(os.path.join(OUT, "10_incline_m7.jpg"), quality=80)
add("10_incline_m7.jpg", ["Master", "vision par ordinateur", "réseaux de neurones"])
# 11. page à l'envers
im = img_text(["Certificat TOEIC obtenu en 2025.", "Niveau avancé en Python."])
im.rotate(180).convert("RGB").save(os.path.join(OUT, "11_envers.jpg"), quality=85)
add("11_envers.jpg", ["TOEIC", "Python"])
# 12. flou
im = img_text(["Commande non linéaire et robotique", "industrielle. Stage chez Renault."]).filter(ImageFilter.GaussianBlur(2.2))
pdf_image("12_flou.pdf", im)
add("12_flou.pdf", ["commande non linéaire", "robotique", "stage"])
# 13. faible contraste
im = noise(img_text(["Le jury souligne la qualité de la thèse", "et des travaux en apprentissage automatique."], fg=150, bg=200), .03)
pdf_image("13_contraste.pdf", im)
add("13_contraste.pdf", ["thèse", "apprentissage automatique"])
# 14. scan : faux amis
pdf_image("14_scan_pieges.pdf", noise(img_text(["Les étudiants de Mister Laval ont visité", "l'usine. Langage C uniquement.",
                                                "Vision globale du projet. Via Lyon."]), .01))
add("14_scan_pieges.pdf", [])
# 15. PDF mixte (titre en texte + paragraphe en image)
pdf_image("15_mixte.pdf", img_text(["Master 1 validé.", "Projet Python de vision par ordinateur."]), heading="Dossier de candidature")
add("15_mixte.pdf", ["Master", "Python", "vision par ordinateur"])
# 16. petite police à empattements
im = img_text(["Mention bien en IA et en robotique ;", "stage effectué au LS2N (Nantes)."], font=SERIF, size=22, w=900)
pdf_image("16_serif_petit.pdf", im)
add("16_serif_petit.pdf", ["IA", "robotique", "stage"])

json.dump({"keywords": KW, "truth": truth}, open(os.path.join(OUT, "truth.json"), "w"), ensure_ascii=False, indent=1)
print(len(truth), "documents")
