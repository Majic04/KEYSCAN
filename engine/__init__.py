"""
Le moteur de KeyScan : 100 % Python, utilisable sans l'interface (python -m engine).

Le parcours d'un document :

    fichier (PDF, image)
        │  extract.py      lire chaque page : texte du PDF, sinon OCR (ocr.py),
        │                  plus l'écriture manuscrite (handwriting.py → trocr.py)
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
ENGINE_VERSION = "2.1"
