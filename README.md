# KeyScan

**Retrouver des mots-clés dans les dossiers de candidature, avec un score de confiance.**
Projet Master 2027 · Centrale Nantes (sujet proposé par F. Plestan et M. Hamida).

Chaque responsable crée un dossier par candidat, y dépose ses documents (PDF texte, PDF scannés, photos, lettres manuscrites) et choisit les mots-clés à y chercher. Pour chaque mot-clé, KeyScan répond **Présent**, **À vérifier**, **Absent** ou **Absence incertaine**, avec un score en % et la preuve (extrait de phrase, page avec le mot encadré). Tout reste sur l'ordinateur : aucun document n'est envoyé sur Internet.

---

## Installer

Télécharger la dernière version dans **[Releases](../../releases/latest)** :

| Ordinateur | Fichier |
|---|---|
| Mac à puce Apple (M1 à M5) | `KeyScan-Mac-AppleSilicon.dmg` |
| Windows 10 / 11 | `KeyScan-Windows-Setup.exe` (sans droits administrateur) |

Tout est inclus : lecture des scans (Tesseract, français et anglais) et de l'écriture manuscrite (TrOCR).

**Mac, le plus simple** : coller dans le Terminal (télécharge, installe et ouvre KeyScan, sans blocage de macOS) :
```
curl -fL -o /tmp/KeyScan.dmg https://github.com/Majic04/KEYSCAN/releases/latest/download/KeyScan-Mac-AppleSilicon.dmg && hdiutil attach -nobrowse -quiet /tmp/KeyScan.dmg && rm -rf /Applications/KeyScan.app && cp -R /Volumes/KeyScan/KeyScan.app /Applications/ && hdiutil detach -quiet /Volumes/KeyScan && xattr -dr com.apple.quarantine /Applications/KeyScan.app && rm /tmp/KeyScan.dmg && open /Applications/KeyScan.app
```
L'application n'est pas signée par Apple ni Microsoft : à la première ouverture, Mac → Réglages Système → Confidentialité et sécurité → « Ouvrir quand même » ; Windows → « Informations complémentaires » → « Exécuter quand même ».

Les données sont rangées dans `~/Library/Application Support/KeyScan` (Mac) ou `%APPDATA%\KeyScan` (Windows) et conservées lors des mises à jour.

## Utiliser

| Écran | Ce qu'on y fait |
|---|---|
| **Dossiers** | Un candidat par ligne ; l'anneau indique combien de ses mots-clés sont trouvés. |
| **+** (nouveau dossier) | Nom du candidat, **mots-clés de départ** (liste par défaut, copie d'un autre dossier, ou aucun) + mots-clés en plus, documents à glisser. Import de plusieurs dossiers d'un coup (.zip). |
| Page d'un dossier | Au centre, le résultat. *Mots-clés* : décision et score de chacun ; un clic montre la preuve. **Modifier les mots-clés** : la liste propre à ce dossier. *Documents* : ajouter, relancer, retirer. |
| **Mots-clés** | La **liste par défaut**, proposée à chaque nouveau dossier. La modifier ne change pas les dossiers existants. |
| **Réglages** | Seuils de décision, équipe, code PIN, export CSV. |

- **Deux profils séparés** (un par responsable), chacun protégé par un **code PIN** : dossiers, mots-clés et seuils propres à chacun. Verrouillage automatique après 30 min. Code oublié : `KeyScan --reset-pin "Prénom Nom"` (voir l'écran du code).
- **Gros documents** : avancement page par page et temps restant.
- **Fichier déposé deux fois** : refusé (même contenu, quel que soit le nom) et jamais compté deux fois.
- **Document illisible** (corrompu, protégé) : alerte sur le dossier, et aucune absence n'est affirmée tant qu'il n'est pas remplacé.

## Comment la décision est prise

1. **Lecture** de chaque page : texte du PDF (contrôlé : une couche texte corrompue est relue par OCR), sinon **Tesseract** (redressement, orientation, plusieurs passes de nettoyage), et **TrOCR** pour les lignes écrites à la main.
2. **Recherche** du mot-clé, sans tenir compte des majuscules ni des accents, tolérante aux erreurs typiques de l'OCR et aux césures.
3. **Score d'une occurrence** = ressemblance avec le mot-clé × confiance de lecture.
4. **Score du dossier** : les occurrences **exactes** se renforcent entre elles ; une occurrence seulement **approchante** (« these » pour « thèse », lecture manuscrite approximative) compte pour sa seule valeur, **même répétée**, et ne peut jamais donner « Présent ».

| Décision | Condition (seuils réglables) |
|---|---|
| **Présent** | score ≥ 85 % avec au moins une occurrence exacte |
| **À vérifier** | 50 % ≤ score < 85 %, ou occurrence seulement approchante |
| **Absent** | score < 50 % et documents bien lus |
| **Absence incertaine** | score < 50 %, mais l'absence ne peut pas être garantie : lecture insuffisante, document illisible dans le dossier, écriture manuscrite, ou mot-clé de 2 caractères dans un scan |

**Mesures** (banc de 16 documents piégés × 12 mots-clés = 192 décisions, `tests/`) : précision **100 %** (aucun faux « Présent »), rappel **95,7 %**, aucun « Absent » affirmé à tort. Écriture manuscrite : ≈ 1 caractère sur 8 mal lu, d'où des décisions prudentes (« À vérifier », « Absence incertaine »).

## Le moteur, en Python seul

Toute l'analyse (lecture, recherche, scores, décisions) est en Python, dans `engine/`. L'interface ne fait qu'afficher les résultats calculés par le serveur. Le moteur s'utilise aussi sans interface :

```bash
pip install -r requirements.txt          # + Tesseract : brew install tesseract tesseract-lang / apt install tesseract-ocr-fra
python -m engine CV.pdf lettre.jpg --mots "thèse, robotique, TOEIC"
python -m engine dossier/*.pdf --mots-fichier mots.txt --json
```

Application complète depuis le code source : `python app.py` (s'ouvre dans le navigateur, données dans `data/`).
Écriture manuscrite en mode Python : `pip install -r requirements-manuscrit.txt` puis `python -m engine.handwriting --install`.

## Tests

```bash
python tests/test_regles.py                                   # règles de décision (répétitions, doublons, illisibles…)
python tests/make_bench.py /tmp/banc && python tests/evaluate.py . /tmp/banc resultats.json   # précision / rappel
```
À chaque envoi sur `main`, GitHub lance ces tests. Quand `APP_VERSION` (dans `desktop.py`) annonce une nouvelle version, les applications Mac et Windows sont en plus construites, testées sur de vrais Mac et Windows, puis publiées (`.github/workflows/build.yml`).

## Organisation du code

```
app.py            serveur local (Flask, SQLite) : profils, dossiers, mots-clés, file d'analyse, export CSV
desktop.py        application de bureau : fenêtre native, dossiers utilisateur
engine/
  extract.py      lecture des PDF et images (texte natif, Tesseract, redressement)
  handwriting.py  écriture manuscrite (détection des lignes, lecture TrOCR)
  matcher.py      recherche tolérante, scores, décisions
  __main__.py     ligne de commande
templates/        interface (une page HTML, sans dépendance externe)
tests/            tests des règles et bancs d'essai (imprimé et manuscrit)
build/            construction des installateurs Mac et Windows
exemples/         documents d'exemple
```
