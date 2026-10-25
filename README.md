# KeyScan

Projet PIAA1 (option INFOIA) pour les masters de Centrale Nantes : retrouver des mots-clés dans les
dossiers de candidature (PDF, scans, photos, lettres manuscrites).

Pour chaque mot-clé d'un dossier, KeyScan répond **Présent**, **À vérifier**, **Absent** ou
**Absence incertaine**, avec un score et l'endroit où le mot a été lu (extrait + image de la page).
Tout tourne sur l'ordinateur, rien n'est envoyé sur Internet.

## Installation

1. Python 3.10 ou plus récent.
2. Tesseract avec le français :
   - Mac : `brew install tesseract tesseract-lang`
   - Windows : installateur de UB Mannheim (cocher « French »)
   - Linux : `sudo apt install tesseract-ocr tesseract-ocr-fra`
3. `pip install -r requirements.txt`

Les deux dernières lignes de `requirements.txt` (torch, transformers) servent à lire l'écriture manuscrite.
On peut les enlever : KeyScan marche sans, mais ne lit alors que le texte imprimé.
Le modèle manuscrit (TrOCR français, environ 2 Go) est téléchargé automatiquement la première fois.

## Lancer

```
python app.py
```
puis ouvrir http://127.0.0.1:5000. Chaque prof a son profil protégé par un code (créé à la première connexion).
Code oublié : `python app.py --oubli-code "Franck Plestan"`.

Sans interface : `python moteur.py cv.pdf lettre.jpg --mots "thèse, robotique"`

Tests : `python tests.py`

## Fichiers

- `moteur.py` : lecture des documents (texte du PDF, OCR avec Tesseract, écriture manuscrite avec TrOCR),
  recherche des mots-clés et décision
- `app.py` : le serveur (Flask + SQLite) : profils, dossiers, lecture en arrière-plan, résultats, export CSV
- `index.html` : l'interface
- `tests.py` : les tests
- `exemples/` : quelques documents pour essayer

## Comment la décision est prise

1. Lecture de chaque page : le texte du PDF s'il est lisible, sinon l'OCR (après redressement de la page).
   Les lignes que Tesseract n'arrive pas à lire sont données à TrOCR (écriture manuscrite).
2. Recherche du mot-clé sans tenir compte des majuscules ni des accents, avec quelques erreurs de lecture
   tolérées pour l'OCR. Un mot-clé n'est pas trouvé à l'intérieur d'un autre mot (« pour » dans « pourquoi »).
3. Score d'une occurrence = ressemblance × confiance de lecture. Plusieurs occurrences exactes se renforcent ;
   un mot seulement proche (« these » pour « thèse ») reste « à vérifier » même s'il est répété.
4. Décision :

| Décision | Quand |
|---|---|
| Présent | score ≥ 85 % avec une occurrence exacte |
| À vérifier | score entre 50 et 85 %, ou mot seulement proche |
| Absent | score < 50 % et documents bien lus |
| Absence incertaine | score < 50 % mais on ne peut pas l'affirmer : document illisible, lecture mauvaise, écriture manuscrite, ou mot de 2 lettres dans un scan |

Les seuils sont au début de `moteur.py`.

Un même fichier déposé deux fois dans un dossier est refusé.
