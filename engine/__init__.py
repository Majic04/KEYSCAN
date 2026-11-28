"""
Le moteur de KeyScan : 100 % Python, utilisable sans l'interface (python -m engine).

Le parcours d'un document :

    fichier (PDF, image)
        │  extract.py      lire chaque page : texte du PDF, sinon OCR (ocr.py, modèle OCRia-nano)
        ▼
    mots lus (« tokens », format décrit dans text.py)
        │  search.py       chercher chaque mot-clé : ressemblance × confiance de lecture
        ▼
    occurrences (où, quoi, avec quel score)
        │  decision.py     score du mot-clé dans le dossier, puis décision
        ▼
    Présent / À vérifier / Absent / Absence incertaine
"""
# Quand ce numéro change, l'application relit tous les documents déjà déposés.
ENGINE_VERSION = "3.2"        # 3.0 : OCRia-nano remplace Tesseract et TrOCR
                              # 3.1 : mots en biais / verticaux / à l'envers relus dans d'autres sens, couverture des pages
                              # 3.2 : angles voisins des diagonales (un mot collé à un autre était lu coupé)
