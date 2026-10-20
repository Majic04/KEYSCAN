# KeyScan — détection de mots-clés dans des dossiers de documents hétérogènes

Projet Master 2027 · Centrale Nantes (sujet proposé par F. Plestan et M. Hamida).

Application **locale** (rien n'est envoyé sur Internet) qui permet aux responsables de master :

1. de saisir une liste de **mots-clés** ou d'expressions (« apprentissage automatique », « TOEIC »…) ;
2. de créer des **dossiers** (un par candidat) et d'y téléverser des documents : PDF texte, PDF scannés, PDF contenant des images collées, photos JPEG/PNG/TIFF ;
3. d'obtenir, pour chaque dossier et chaque mot-clé, une **décision** (Présent / À vérifier / Absent) accompagnée d'un **score de confiance en %** ;
4. de vérifier chaque détection (extrait de phrase + page avec le mot encadré) et d'**exporter** les décisions en CSV (Excel).

---

## 0. Application de bureau (recommandé)
Les installateurs se trouvent dans l'onglet **Releases** du dépôt GitHub :

| Ordinateur | Fichier |
|---|---|
| Mac à puce Apple (M1 et suivants) | `KeyScan-Mac-AppleSilicon.dmg` → glisser KeyScan dans Applications |
| Windows 10 / 11 (64 bits) | `KeyScan-Windows-Setup.exe` (sans droits administrateur) |

Tout est inclus (Python, Tesseract français/anglais, modèle d'écriture manuscrite) ; aucun accès Internet n'est nécessaire ensuite. KeyScan s'ouvre dans sa propre fenêtre ; les données sont rangées dans `~/Library/Application Support/KeyScan` (Mac) ou `%APPDATA%\KeyScan` (Windows) et conservées lors des mises à jour. Une ancienne installation « dossier KeyScan » est reprise automatiquement au premier lancement.

Première ouverture d'une application non signée : Mac → Réglages Système → Confidentialité et sécurité → « Ouvrir quand même » ; Windows → « Informations complémentaires » → « Exécuter quand même ».

**Construction** : à chaque envoi sur `main`, GitHub Actions (`.github/workflows/build.yml`) construit l'application sur Mac et sur Windows, prépare le modèle manuscrit (`build/prepare_model.py`), embarque Tesseract (`build/mac/bundle_tesseract.sh`, `build/windows/get_tesseract.ps1`), lance les bancs d'essai, **teste l'application construite** (`build/smoke_test.py`) puis publie les installateurs.

Les sections suivantes décrivent l'utilisation « depuis le code source » (développement).

## 1. Installation (depuis le code source)

### Prérequis
| Outil | Rôle | Installation |
|---|---|---|
| Python ≥ 3.10 | exécute l'application | https://www.python.org/downloads/ (cocher « Add Python to PATH » sous Windows) |
| Tesseract OCR 5 + langue française | lit le texte dans les images | voir ci-dessous |

**Tesseract**
- **Windows** : installeur UB-Mannheim https://github.com/UB-Mannheim/tesseract/wiki — pendant l'installation, cocher *Additional language data → French*. Le chemin `C:\Program Files\Tesseract-OCR\tesseract.exe` est détecté automatiquement.
- **macOS** : `brew install tesseract tesseract-lang`
- **Linux (Debian/Ubuntu)** : `sudo apt install tesseract-ocr tesseract-ocr-fra`

Vérification : `tesseract --list-langs` doit afficher `fra` et `eng`.
Si Tesseract est installé ailleurs, définir la variable d'environnement `TESSERACT_CMD` avec son chemin complet.

### Dépendances Python
```bash
cd keyscan
python -m venv .venv
# Windows : .venv\Scripts\activate      macOS/Linux : source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Lancement
```bash
python app.py
```
Le navigateur s'ouvre sur http://127.0.0.1:5000. Raccourcis : double-clic sur `lancer_windows.bat` ou `lancer_mac_linux.sh`.

Pour que les deux responsables utilisent la même instance depuis deux postes du réseau de l'école :
`python app.py --host 0.0.0.0` puis ouvrir `http://<adresse-IP-du-poste>:5000` depuis l'autre poste.

Les données (base SQLite + fichiers) sont stockées dans le dossier `data/`. Pour tout remettre à zéro, supprimer ce dossier.

## 3. Utilisation
L'interface tient en trois onglets (barre flottante en bas) et un bouton **+** :

| Écran | Ce qu'on y fait |
|---|---|
| **Mots-clés** | Taper un mot-clé puis Entrée. Coller une liste (un mot par ligne) les ajoute tous d'un coup. ✕ pour retirer. |
| **+** | Nouveau dossier : nom du candidat + documents glissés dans la zone. Lien « Importer plusieurs dossiers (.zip) » : chaque sous-dossier du .zip devient un candidat. |
| **Dossiers** | Liste des candidats ; l'anneau indique combien de mots-clés ont été trouvés (ex. 6/7). |
| Page d'un dossier | Au centre, l'anneau du résultat. En dessous, deux vues : *Mots-clés* (décision et score de chacun ; cliquer pour voir la preuve : extrait, page avec le mot encadré) et *Documents* (ajouter, relancer l'analyse, retirer). Menu ⋯ : renommer, supprimer. |
| **Réglages** | Prof actif, seuils de décision (enregistrés automatiquement), équipe, export CSV. |

### Deux profils entièrement distincts
Chaque prof a **son propre espace** ; seule la composition de l'équipe est commune.

| Propre à chaque prof | Commun |
|---|---|
| Dossiers | Liste des membres de l'équipe |
| Mots-clés | |
| Seuils de décision (Présent, À vérifier, Lecture minimale) | |
| Export CSV | |

- Changer de profil : **avatar en haut à droite** (une couleur par prof) ou Réglages → *Profil actif*. Le choix est mémorisé par poste.
- Un dossier est évalué avec les mots-clés et les seuils **de son prof** : le même document peut être « Présent » chez l'un et « À vérifier » chez l'autre.
- Mots-clés → **Reprendre les mots-clés de …** copie la liste d'un autre prof (sans doublon), pour démarrer vite.
- Menu ⋯ d'un dossier → **Confier à …** pour le transmettre (il sera alors évalué avec les critères de son nouveau prof).
- Un nouveau membre démarre avec un profil vierge (aucun dossier, aucun mot-clé, seuils par défaut). On ne peut retirer un membre que s'il n'a plus de dossiers ; son profil est alors supprimé.
- Mise à jour depuis une version précédente : les anciens mots-clés et seuils communs sont recopiés dans chaque profil au premier démarrage, rien n'est perdu.

### Codes PIN
- À l'ouverture, KeyScan demande **« Qui êtes-vous ? »** puis le code du profil. À la première ouverture d'un profil, on crée son code (4 à 8 chiffres, saisi deux fois).
- Un navigateur n'a qu'**un seul profil ouvert à la fois** : passer à l'autre profil (avatar ou Réglages) demande le code de l'autre.
- **Verrouiller** : menu de l'avatar ou Réglages → *Sécurité*. Verrouillage **automatique après 30 minutes** sans activité.
- **Changer son code** : Réglages → *Sécurité* → *Changer le code* (l'ancien est demandé). Les autres navigateurs ouverts sur ce profil sont alors verrouillés.
- Retirer un **autre** membre de l'équipe demande **son** code.
- Sécurité côté serveur : chaque requête est vérifiée (un prof ne peut ni lire, ni modifier, ni supprimer les dossiers, mots-clés ou réglages de l'autre, même en trafiquant les requêtes). Codes stockés hachés (PBKDF2), jamais en clair. Après 5 erreurs, attente imposée (30 s, puis de plus en plus longue).
- **Code oublié** : sur l'ordinateur où tourne KeyScan, dans le dossier KeyScan :
  - Mac : `.venv/bin/python app.py --reset-pin "Franck Plestan"`
  - Windows : `.venv\Scripts\python app.py --reset-pin "Franck Plestan"`

  Un nouveau code sera demandé à la prochaine ouverture du profil (dossiers, mots-clés et réglages sont conservés).

### Gros documents
Le nombre de pages est compté dès le dépôt. Pendant l'analyse, KeyScan affiche l'avancement **page par page** et le **temps restant estimé** : dans la liste (« Analyse : 12/140 pages · ≈ 2 min » + barre), au centre de la page du dossier (l'anneau se remplit) et sur chaque document (« Page 13/140 »). Un document en file d'attente affiche « En attente : 140 pages ».

L'analyse (OCR) tourne en arrière-plan ; les écrans se mettent à jour seuls.
Ajouter un mot-clé après coup ne relance pas l'OCR : la recherche est instantanée.

## 4. Comment la confiance est calculée

### Extraction
Pour chaque page :
- la **couche texte** du PDF est lue directement (PyMuPDF), puis **contrôlée** : une police sans table Unicode donne un texte copiable illisible (« DSSUHQWLVVDJH » au lieu de « apprentissage ») ; dans ce cas la page est relue par OCR ;
- si la page contient des **images**, presque pas de texte, ou une couche texte suspecte, elle est rendue à 300 dpi et passée à l'**OCR Tesseract** (français + anglais) :
  1. orientation automatique (0/90/180/270°) ;
  2. **redressement fin** de l'inclinaison (± 12°, au dixième de degré) par profils de projection ;
  3. **lectures successives** tant que la lecture reste médiocre : image brute → image nettoyée (contraste, filtre médian, seuillage d'Otsu) → **seuillage local** (fond non uniforme, faible contraste) → autre mode de segmentation. La meilleure lecture fait foi, les autres complètent.

### Recherche
Texte et mots-clés sont normalisés (minuscules, sans accents, ligatures) ; les symboles de **C++ / C#** sont conservés (« langage C » ne donne plus « C++ »). Une fenêtre glissante compare chaque groupe de mots lus au mot-clé (gère les césures « apprentis- / sage » et les mots collés par l'OCR).

| Situation | Ressemblance |
|---|---|
| Écriture identique (aux majuscules/accents près) | 1 |
| Singulier / pluriel (« réseau » / « réseaux ») | 0,97 |
| **Texte natif** : faute de frappe | tolérée seulement sur les mots ≥ 8 lettres (1 faute) |
| **OCR** : erreurs de lecture | ≤ 4 lettres : aucune · 5-6 : une confusion typique (rn↔m, cl↔d, 0↔o, 1/i↔l, 5↔s) · 7-10 : 1,5 · > 10 : 2,5 |
| Accents différents sur un mot court (« thèse » / « these ») | × 0,72 → passe en « à vérifier » |
| Sigle en majuscules lu en minuscules (« IA » / « ia ») | × 0,6 |

### Scores
| Grandeur | Formule |
|---|---|
| Confiance de lecture | 1 pour une couche texte saine ; confiance Tesseract pour l'OCR, **recalibrée** pour les correspondances exactes : c' = 1 − (1 − c) × 0,5^((L − 3)/3) (retrouver exactement un mot long par hasard est très improbable) |
| Score d'une occurrence | ressemblance × confiance de lecture |
| Score du mot-clé dans le dossier | S = 1 − (1 − s_max) × Π_autres (1 − s_i / 2) |
| Qualité de lecture du dossier | confiance moyenne de la lecture principale, pour le document le moins bien lu |

### Décision
| Décision | Condition (réglable dans « Réglages ») | Fiabilité affichée |
|---|---|---|
| **Présent** | S ≥ 85 % | S |
| **À vérifier** | 50 % ≤ S < 85 % | S |
| **Absent** | S < 50 % et qualité de lecture ≥ 70 % | qualité de lecture |
| **Absence incertaine** | S < 50 % mais absence impossible à garantir : documents mal lus, écriture manuscrite dans le dossier (TrOCR lit environ 1 caractère sur 8 de travers) ou mot-clé de 2 caractères dans un scan | qualité de lecture |

### Mesure de la précision (banc d'essai)
`banc_essai/` génère 16 documents piégés (texte natif, couche texte corrompue, césures, scans propres, basse résolution, JPEG bruité, photos inclinées de 4° et −7°, page à l'envers, flou, faible contraste, faux amis « These / Mister / langage C », petite police) et mesure 192 décisions (16 documents × 12 mots-clés) :
```bash
python banc_essai/make_bench.py banc_essai/docs
python banc_essai/evaluate.py . banc_essai/docs resultats.json
```
| Indicateur | Moteur 1.0 | Moteur 2.0 |
|---|---|---|
| Précision (« présent » justes) | 88,6 % | **100 %** |
| Rappel (mots présents trouvés) | 66,0 % | **95,7 %** |
| Exactitude des décisions fermes | 90,5 % | **99,5 %** |
| Faux « présent » | 4 | **0** |
| « Absent » sûrs à tort | 5 | **0** |
| Score moyen des vrais présents | 66,8 % | **95,7 %** |
| Score le plus haut d'un faux | 100 % | **72 %** (« à vérifier ») |
| Temps (16 documents) | 18,6 s | 20,4 s |

Quand le moteur change de version, tous les documents déjà téléversés sont ré-analysés automatiquement au démarrage.

## 5. Écriture manuscrite (module optionnel)
Tesseract est fait pour le texte imprimé : sur une lettre manuscrite, il produit du charabia et les mots-clés écrits à la main sont ratés. Le module manuscrit corrige cela.

**Installation (une seule fois)** — après avoir lancé KeyScan au moins une fois :
- Mac : double-clic sur **« Installer écriture manuscrite.command »**
- Windows : double-clic sur **`installer_manuscrit.bat`**

Il installe PyTorch et Transformers, télécharge le modèle dans `KeyScan/models/` puis lit `exemples/manuscrit.png` pour vérifier que tout fonctionne. Au redémarrage, KeyScan relit automatiquement tous les documents avec le module. L'état est visible dans Réglages → *Écriture manuscrite*.

| Modèle | Usage | Taille |
|---|---|---|
| **Français** (par défaut) — [agomberto/trocr-large-handwritten-fr](https://huggingface.co/agomberto/trocr-large-handwritten-fr), TrOCR large affiné sur de l'écriture manuscrite française (licence MIT ; taux d'erreur par caractère ≈ 9 % sur son jeu de test) | documents en français | ≈ 2,3 Go |
| Anglais — [microsoft/trocr-base-handwritten](https://huggingface.co/microsoft/trocr-base-handwritten) | plus léger et plus rapide | ≈ 1,3 Go |

**Fonctionnement** (`engine/handwriting.py`), pour chaque page lue par OCR :
1. **Segmentation** de la page en lignes (profil de l'encre, seuillage local), puis en morceaux de ~12 mots au plus.
2. **Détection** : un morceau est considéré comme manuscrit si Tesseract n'y a pas lu de texte imprimé fiable (moins de 60 % de sa largeur couverte par des mots lus à ≥ 75 %). Les lignes imprimées bien lues ne sont pas relues (gain de temps).
3. **Lecture** des morceaux manuscrits par TrOCR ; confiance d'une ligne = probabilité moyenne des caractères générés.
4. Les mots lus deviennent une source « écriture manuscrite » : même recherche floue que l'OCR, score = ressemblance × confiance du modèle (sans le bonus de correspondance exacte réservé à Tesseract, car un modèle de langage peut « deviner » un mot plausible). Dans les zones relues, la lecture ratée de Tesseract ne compte plus dans la qualité de lecture.

**Limites** : écriture très liée ou illisible, ratures, texte vertical. Lecture plus lente que l'OCR (environ 0,5 à 2 s par ligne manuscrite selon le Mac). Le modèle s'exécute entièrement sur l'ordinateur : aucun document n'est envoyé sur Internet.

## 6. Fluidité (60 images/s)
L'interface est conçue pour tourner à 60 images par seconde même sans carte graphique dédiée :
- fond fixe peint une seule fois (aucune animation permanente) ;
- vrai flou d'arrière-plan réservé à la barre d'onglets ; ailleurs, verre « peint » sans calcul de flou ;
- survols et transitions limités à `transform` et `opacity` (traités par la carte graphique) ;
- curseur piloté par les événements souris, à l'arrêt quand la souris ne bouge pas ;
- serveur : texte extrait gardé en mémoire, aperçus de pages mis en cache, plusieurs documents analysés en parallèle.

Mesure (Chromium, rendu logiciel, 15 dossiers) : ~7 images/s avant optimisation → **60 images/s, 0 image en retard** au repos, au survol, au défilement, à l'ouverture des fenêtres et en navigation.

Si l'affichage reste saccadé sur un poste :
1. **Chrome / Edge** → Paramètres → Système → activer « Utiliser l'accélération graphique si disponible », puis relancer le navigateur.
2. Vérifier dans `chrome://gpu` que « Compositing » est « Hardware accelerated ».
3. Sur un portable, brancher le secteur (le mode économie d'énergie bride l'affichage).
4. Ouvrir KeyScan dans Chrome, Edge, Safari ou Firefox récent plutôt que dans un ancien navigateur.

## 7. Architecture
```
keyscan/
├── desktop.py           application de bureau : fenêtre native, dossiers utilisateur, reprise des données
├── app.py               serveur Flask, base SQLite, file d'analyse, API, export CSV
├── engine/
│   ├── extract.py       extraction texte natif + contrôle, OCR multi-lectures, redressement
│   ├── handwriting.py   écriture manuscrite : segmentation, détection, lecture TrOCR (optionnel)
│   └── matcher.py       recherche floue, score calibré, décision
├── banc_essai/          documents piégés + mesure précision/rappel ; manuscrit/ : banc d'essai écriture manuscrite
├── build/               construction des installateurs (PyInstaller, Tesseract, modèle, DMG, Inno Setup, tests)
├── .github/workflows/   construction automatique Mac + Windows
├── templates/index.html interface (HTML/CSS/JS, sans dépendance externe)
├── requirements.txt
└── data/                créé au lancement : keyscan.db + fichiers téléversés
```
API REST principale : `/api/keywords`, `/api/dossiers`, `/api/dossiers/<id>/files`, `/api/import-zip`, `/api/results`, `/api/dossiers/<id>/keyword/<id>`, `/export.csv`.

## 8. Limites et pistes d'amélioration
- **Écriture manuscrite** : module TrOCR disponible (section 5) ; piste suivante : l'évaluer sur de vrais documents manuscrits annotés et, si besoin, affiner le modèle sur ces documents.
- **Calibration sur de vrais dossiers** : le banc d'essai est synthétique ; l'étape suivante est d'annoter à la main une vingtaine de vrais dossiers, de les passer dans `evaluate.py`, et d'ajuster les seuils (ou de calibrer les scores par régression logistique).
- **Synonymes / variantes** : ajouter des groupes de mots-clés équivalents (« machine learning » ≈ « apprentissage automatique ») ou une recherche sémantique par embeddings.
- **Formats** : ajouter .docx / .odt (python-docx) et les e-mails.
- **Sécurité** : en mode réseau (`--host 0.0.0.0`), ajouter une authentification simple si le réseau n'est pas de confiance.
