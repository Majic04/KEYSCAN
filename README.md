# KeyScan

<img src="static/logo.svg" alt="Logo KeyScan : une loupe sur un document, un K dans la lentille" width="96">

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

L'écran est un bureau : à gauche la liste des candidats (avec recherche), à droite le dossier ouvert.

| Endroit | Ce qu'on y fait |
|---|---|
| **Colonne de gauche** | Un candidat par ligne. La petite bande indique un mot-clé par case : vert trouvé, jaune à vérifier. **Nouveau** crée un dossier : nom, mots-clés de départ (liste par défaut, copie d'un autre dossier, ou aucun), mots-clés en plus, documents. |
| **Importer plusieurs candidats** | On dépose (ou on choisit) le dossier qui contient **un sous-dossier par candidat**, ou un `.zip` : chaque sous-dossier devient un dossier KeyScan avec la liste par défaut, et tous les documents sont lus en parallèle. |
| **Comparer** | Tous les dossiers dans un tableau : une ligne par candidat, une colonne par mot-clé, la même marque que le surligneur dans chaque case (un clic ouvre la preuve). On **coche** des dossiers pour agir sur tous à la fois : ajouter des mots-clés, ajouter la liste par défaut, relire, exporter, supprimer. Un clic sur un mot-clé en haut d'une colonne permet de trier ou de le retirer des dossiers cochés. |
| **Dossier ouvert** | Les mots-clés sont rangés par décision : *Présents* et *À vérifier* sont surlignés comme au feutre, *Absence incertaine* est soulignée en pointillé. Un clic ouvre la preuve dans un volet : zoom sur le mot, ce qui a été lu, page entière. **Modifier les mots-clés** change la liste de ce dossier seulement. L'onglet *Documents* montre, pour chaque document, les mots à vérifier et leur page ; l'œil affiche le document avec tous les mots-clés surlignés. |
| **Liste par défaut** | Proposée à chaque nouveau dossier. La modifier ne change pas les dossiers existants. |
| **Réglages** | Seuils de décision, équipe, code PIN, export CSV. |

- **Deux profils séparés** (un par responsable), chacun protégé par un **code PIN** : dossiers, mots-clés et seuils propres à chacun. Verrouillage automatique après 30 min. Après chaque mise à jour de l'application, chaque profil choisit un nouveau code. Code oublié : `KeyScan --reset-pin "Prénom Nom"` (voir l'écran du code).
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
Écriture manuscrite en mode Python : `pip install -r requirements-manuscrit.txt` puis `python -m engine.trocr --install fr`.

## Tests

```bash
python tests/test_regles.py                                   # règles de décision (répétitions, doublons, illisibles…)
python tests/test_serveur.py                                  # serveur : profils, import de plusieurs candidats, actions groupées
python tests/make_bench.py /tmp/banc && python tests/evaluate.py . /tmp/banc resultats.json   # précision / rappel
```
À chaque envoi sur `main`, GitHub lance ces tests. Quand `APP_VERSION` (dans `desktop.py`) annonce une nouvelle version, les applications Mac et Windows sont en plus construites, testées sur de vrais Mac et Windows, puis publiées (`.github/workflows/build.yml`).

## Organisation du code

Le code est écrit pour être relu : un fichier = un rôle, des noms en clair, des commentaires en français.

```
app.py              lance KeyScan depuis le code source (python app.py)
desktop.py          application de bureau : fenêtre native, dossier des données, auto-test

engine/             LE MOTEUR : lire les documents et décider (Python seul, sans interface)
  text.py           format d'un mot lu (« token »), mise en forme normalisée (sans accents ni majuscules)
  extract.py        lire un document : texte du PDF, ou image → OCR
  ocr.py            Tesseract : préparation de l'image, orientation, redressement, plusieurs lectures
  handwriting.py    repérer les lignes écrites à la main sur une page
  trocr.py          lire ces lignes avec le modèle TrOCR (installation, chargement)
  search.py         chercher un mot-clé : ressemblance, erreurs d'OCR tolérées, mots imbriqués (« pour » ≠ « pourquoi »)
  decision.py       transformer les occurrences en score et en décision
  __main__.py       ligne de commande (python -m engine …)

server/             L'APPLICATION : base de données, profils, API pour l'interface
  database.py       la base SQLite et le dossier des données
  migrations.py     mise à jour d'une base créée par une ancienne version
  profiles.py       l'équipe, les seuils de chacun, les codes PIN, la session
  keywords.py       les listes de mots-clés (par dossier, et la liste par défaut)
  uploads.py        dépôt des fichiers, import de plusieurs candidats
  analysis.py       lecture des documents en arrière-plan (jusqu'à 4 à la fois)
  results.py        calcul des décisions de chaque dossier
  previews.py       image d'une page avec les mots surlignés
  routes/           les adresses de l'API, un fichier par sujet (session, keywords, dossiers, documents, results, settings)

templates/index.html  la page (sa structure seulement)
static/css/           l'apparence
static/js/            l'interface, en petits fichiers : utils, state, pages, compare, dialogs, actions, lock, cursor, start
tests/              tests des règles, du serveur, et bancs d'essai (imprimé et manuscrit)
build/              construction des installateurs Mac et Windows
exemples/           documents d'exemple
```

### Le trajet d'un document

1. **Dépôt** — `server/uploads.py` enregistre le fichier dans `data/files/`, calcule son empreinte (un doublon est refusé) et met son numéro dans la file d'attente.
2. **Lecture** — un « ouvrier » de `server/analysis.py` le prend et appelle `engine.extract.read_document()`. Chaque page est lue (texte du PDF, sinon OCR, et TrOCR pour l'écriture manuscrite) ; on obtient la liste des mots lus, avec leur position et leur confiance. Elle est enregistrée dans la base : **un document n'est lu qu'une fois**.
3. **Recherche** — quand l'interface demande les résultats, `server/results.py` cherche chaque mot-clé du dossier dans ces mots (`engine.search.find_keyword()`), puis `engine.decision.evaluate()` donne le score et la décision avec les seuils du responsable. Ajouter un mot-clé ne relance donc pas la lecture.
4. **Affichage** — l'interface (`static/js/`) reçoit tout en une fois (`/api/results`) et dessine les pages ; la preuve d'un mot est une image de la page fabriquée par `server/previews.py`, le mot encadré.

## Polices et logo

Polices intégrées, toutes sous licence libre SIL OFL (licences dans `static/fonts/`) : **Syne** (titres, noms, chiffres), **Atkinson Hyperlegible Next** (texte de l'interface), **Literata** (mots et extraits venant des documents). Le logo et les icônes se régénèrent avec `python build/make_logo.py`.
