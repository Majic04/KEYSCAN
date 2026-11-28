## Nouveautés de la version 1.19.1

- **Correction : mots comptés en double sur les pages avec un tableau ou des cadres.** Sur un scan droit qui contient des traits (tableau, encadré, formulaire), la version 1.19 relisait la page dans d'autres sens et pouvait compter le même mot plusieurs fois, encadré au mauvais endroit (par exemple « date » 12 fois au lieu de 3 dans l'export). Chaque mot est maintenant compté une seule fois, à sa place.
- **Correction : fausse alerte « Lu en partie seulement ».** Les traits d'un tableau ou d'un cadre étaient comptés comme du texte non lu : une page bien lue pouvait être signalée à tort et rendre une absence « incertaine ».
- Les documents déjà déposés sont relus une fois au premier lancement.

## Version 1.19

- **Mots en biais, verticaux ou à l'envers enfin lus** sur les scans et les photos. Avant, seuls les mots à peu près horizontaux étaient lus : un mot écrit en diagonale, à la verticale ou à l'envers (tampon, annotation, en-tête de tableau, nuage de mots) était manqué.
  - Quand une page est mal lue, KeyScan la relit tournée dans d'autres sens (90°, 180°, 270°, en diagonale et aux angles voisins), et chaque mot trouvé est encadré au bon endroit de la page.
  - Sur un banc de 30 images de nuages de mots : **73 %** des mots retrouvés au lieu de 24 % (94 % sur une image parfaite), toujours sans aucun faux « Présent ».
  - Les documents ordinaires (CV, lettres, scans droits) sont bien lus du premier coup : ils ne sont pas relus et pas ralentis.
- **Page lue en partie seulement** : quand moins de la moitié du texte d'une page est reconnue (scan très abîmé), KeyScan n'affirme plus « Absent » mais « Absence incertaine », et l'écrit en rouge sous le document.
- « lecture X % » sous un document devient « **confiance de lecture** X % » : c'est la confiance dans les mots lus, pas la part de la page lue.
- **Preuve d'un mot ouverte depuis un document** : le verdict de ce document s'affiche d'abord (par exemple « À vérifier » pour un mot mal orthographié), puis celui de tout le dossier, puis les autres documents du dossier.
- Les « mots » lus à l'envers (lettres retournées) sont écartés.
- **Relecture automatique** : au premier lancement, tous les documents déjà déposés sont relus une fois avec le nouveau moteur. Cela peut prendre quelques minutes.

## Version 1.18

- **Nouvelle interface** : des cartes bleu nuit très arrondies sur un fond ardoise, un accent violet en dégradé, des boutons en pilule et une police ronde (Outfit).
  - Barre du haut en pilule, avec une icône pour chaque page.
  - Sur l'accueil, chaque dossier montre un **anneau** : la part des mots-clés trouvés (vert) et à vérifier (orange).
  - Dans un dossier : un grand anneau et une barre en dégradé par décision, des boutons-tuiles (Ajouter, Dossier, Mots-clés, Plus), et les mots trouvés en pastilles colorées.
  - Curseurs, choix, cases à cocher et code PIN aux couleurs violettes.
- Les animations de la version précédente sont gardées : survol, appui, apparition des cartes, anneaux qui se remplissent, barres qui se remplissent.

## Version 1.17

- **Interface à la façon de macOS** :
  - police du système, barre d'outils unifiée, barre latérale translucide ;
  - contrôles segmentés, menus et fenêtres comme ceux du système, tableau « Comparer » façon Finder.
- **Petites animations** :
  - les boutons s'enfoncent au clic, les cartes et les tuiles se soulèvent au survol ;
  - les mots trouvés « sautent » comme dans la recherche de Safari ;
  - les cases à cocher se dessinent, la zone de dépôt réagit quand on y glisse un fichier ;
  - une barre de progression brillante pendant la lecture.
  Tout est coupé si macOS demande de réduire les animations.
- **Le curseur rond est retiré** : le curseur normal du système revient.
- **Importer : trois façons de ranger les documents**, pour un dossier comme pour des .zip :
  - **un dossier KeyScan par sous-dossier** (comme avant) ;
  - **tout dans un seul dossier KeyScan** : un dossier de PDF devient un seul candidat ;
  - **un dossier KeyScan par fichier** : chaque PDF devient son propre candidat.
  On choisit avant d'importer, avec un schéma de ce qui sera créé. Déposer un dossier ou des .zip sur l'accueil ouvre ce choix.
- **Ajouter un dossier entier à un dossier existant** : « … → Ajouter un dossier de documents », ou glisser le dossier sur la zone de dépôt.

## Version 1.16

- **Lecture plus rapide, sans réglage** : le choix « Économe / Rapide » disparaît des Réglages. Le moteur OCRia-nano-1 étant léger, KeyScan lit maintenant plusieurs documents en même temps : un par cœur du processeur, jusqu'à 4, en gardant toujours un cœur libre. La lecture reste en priorité basse, pour que l'ordinateur reste utilisable pendant un gros import.

## Version 1.15

- **Nouveau moteur de lecture : OCRia-nano-1** (LlamaIndex) remplace Tesseract et TrOCR pour les scans et les photos. C'est un petit modèle (8 millions de paramètres) qui tourne sur le processeur, sans Internet.
  - Sur le banc d'essai (16 documents piégés × 12 mots-clés), il trouve **100 %** des mots présents, contre 95,7 % avec Tesseract, toujours sans aucun faux « Présent ».
  - Les photos penchées ou couchées sont toujours remises droites.
  - L'application est beaucoup plus légère : PyTorch et le module manuscrit sont retirés.
- **Écriture manuscrite** : elle n'est plus lue par un module dédié. Une écriture régulière est souvent lue, une écriture difficile ne l'est pas : vérifiez les lettres manuscrites dans l'aperçu.
- **Relecture automatique** : au premier lancement, tous les documents déjà déposés sont relus une fois avec le nouveau moteur. Cela peut prendre quelques minutes.

## Version 1.14

- **Un mot non trouvé est maintenant déclaré « Absent »** : nouveau réglage « Mot non trouvé » dans Réglages → Seuils de décision.
  - **Absent** (par défaut) : KeyScan tranche. Seul un document impossible à ouvrir laisse « Absence incertaine », pour ne pas conclure à partir d'un document jamais lu.
  - **Prudent** (l'ancien fonctionnement) : « Absence incertaine » dès qu'un document est difficile à lire (scan de mauvaise qualité, texte manuscrit, mot très court).
- En mode prudent, **une signature ou un paraphe ne suffit plus** à rendre toutes les absences incertaines : il faut un vrai texte manuscrit (au moins 3 lignes).

## Version 1.13

- **Nouvel export CSV, le tableau des fréquences** : une ligne par document, une colonne par mot-clé. Chaque case indique combien de fois le mot a été lu dans ce document. Les documents sont groupés par dossier, et les dossiers par profil (toute l'équipe, ou seulement les dossiers cochés dans « Comparer »). Une case vide signifie que le mot n'est pas recherché dans ce dossier ou que le document n'est pas encore lu.
- **Import d'un .zip à plusieurs candidats, plus robuste** : chaque sous-dossier devient un dossier KeyScan et sa lecture démarre aussitôt.
  - Un .zip par candidat, rangé dans le .zip du lot ou déposé à plusieurs, devient aussi un dossier.
  - Plusieurs dossiers englobants (« Lot/Candidats 2027/… ») sont traversés automatiquement.
  - Les sous-dossiers d'un candidat (« Dupont/diplômes/… ») restent dans son dossier.
  - Une archive abîmée est signalée par un message.
- **Accueil** : une zone pour déposer directement un dossier ou un .zip de candidats.

## Version 1.12

- **Mode sombre** : toute l'application passe en bleu nuit. Seul ce qui compte s'allume : les mots-clés trouvés (surligneur vert pour « présent », jaune pour « à vérifier ») et les pages des documents.
- **Accueil** : une carte par dossier, avec en grand le nombre de mots-clés trouvés (« 8/10 ») et les mots eux-mêmes surlignés, ainsi que les mots à vérifier et les documents illisibles.
- **Page d'un dossier, tout sur un seul écran** :
  - quatre compteurs en haut (présents, à vérifier, incertains, absents) ;
  - les mots-clés en grandes tuiles surlignées, les mots à vérifier en premier ;
  - les documents juste en dessous, avec tous leurs mots trouvés ;
  - à droite, l'aperçu de la page du document avec les mots-clés encadrés. Les marges blanches sont retirées pour que le texte soit plus grand. On change de document ou de page sans quitter le dossier.
- **Preuve d'un mot** : le mot en très grand, puis son image dans le document, avant le texte lu.

## Version 1.11

- **Importer un .zip dans un dossier** : « Ajouter des documents » (ou un glisser-déposer) accepte maintenant les archives .zip, dans un dossier existant comme à la création d'un nouveau dossier. Chaque PDF ou image de l'archive est ajouté, y compris dans ses sous-dossiers ; les fichiers cachés du Mac sont ignorés. Le message indique les documents ajoutés, les doublons et ce qui a été refusé (format non pris en charge, archive abîmée ou protégée).
- **Réglages → Lecture des documents** : le choix « Rapide » / « Économe » s'affiche tout de suite (il fallait changer de page pour le voir).
- **Équipe** : l'ajout ou le retrait d'une personne s'affiche aussitôt.
- **Seuils** : les décisions des dossiers suivent immédiatement les nouveaux seuils.
- **Comparer** : trier une colonne ne fait plus remonter la page en haut.

## Version 1.10

- **Nouvelle apparence, en relief doux (neumorphisme)** : une seule matière claire d'où tout est moulé. Les boutons sont en relief, les champs et zones de dépôt sont creusés, et ce qui est choisi (onglet, dossier ouvert, option) est enfoncé. Les couleurs sont plus claires ; les polices ne changent pas.
- **Toujours en thème clair**, même si l'ordinateur est réglé en mode sombre.
- **Plein écran** : l'application reste groupée au centre avec des marges égales, le contenu n'est plus collé à gauche, et tout est un peu plus grand sur les grands écrans.
- **Survol des boutons du haut** : le cercle du curseur n'est plus coupé par le bord de la fenêtre.

## Version 1.9

- **Beaucoup moins de calcul sur les PDF avec un logo ou une photo** (CV, relevés de notes) : le texte de ces PDF est déjà lisible directement, mais la moindre image faisait relire toute la page par l'OCR, puis par le modèle manuscrit. Désormais seules les grandes images (un document photographié collé dans le PDF) sont lues, et seulement leur zone. Sur un lot de documents types, le temps de lecture passe de 64 s à 18 s et les lignes envoyées au modèle manuscrit de 36 à 6.
- **Sens de la page vérifié seulement quand c'est utile** : une page droite et bien lue n'est plus analysée pour savoir si elle est à l'envers.
- **Réglages → Lecture des documents** : « Économe » (un document à la fois, par défaut) ou « Rapide » (deux à la fois).
- Si le module manuscrit est momentanément indisponible au démarrage, KeyScan ne relit plus tous les dossiers.
- Les décisions sont inchangées : mêmes résultats sur les bancs d'essai imprimé et manuscrit.

## Version 1.8

- **Gros dossiers (30 documents et plus)** : KeyScan lit 2 documents à la fois au plus, sur la moitié des cœurs du processeur et en priorité basse. L'ordinateur chauffe moins et reste utilisable ; la lecture est en contrepartie plus lente.
- **Écriture manuscrite** : 30 lignes par page au plus sont confiées au modèle manuscrit, la partie la plus coûteuse.
- **Barre de progression** : elle compte maintenant tous les documents du dossier (« 12 sur 31 documents lus ») au lieu de repartir de zéro à chaque document, et le suivi reprend tout seul après une demande ratée.
- **Nouveau dossier** : il faut déposer au moins un document pour le créer.
- Un document dont la lecture a été interrompue par un arrêt de KeyScan n'est plus relancé tout seul : il est signalé, avec le bouton « Relire ».

## Version 1.7

- **Mises à jour automatiques** : KeyScan vérifie au lancement, puis toutes les 6 heures, si une nouvelle version est publiée. Elle se télécharge en arrière-plan (son empreinte est vérifiée), puis un bouton « Version … prête · Redémarrer » apparaît en haut de l'écran. Sans clic, elle s'installe à la fermeture de KeyScan. Plus besoin de retélécharger l'application.
- Seul le numéro de la dernière version est demandé à GitHub : aucun document ni aucune donnée ne quitte l'ordinateur.
- Réglages → Application : version installée, avancement du téléchargement, « Rechercher maintenant ».
- Cette version 1.7 s'installe encore à la main une dernière fois ; les suivantes arrivent toutes seules.

## Version 1.6

- **Plusieurs candidats d'un coup** : « Importer plusieurs candidats » accepte le dossier qui contient un sous-dossier par candidat (déposé ou choisi), ou un `.zip`. Chaque sous-dossier devient un dossier KeyScan avec la liste par défaut, et tous les documents sont lus en parallèle.
- **Nouvel onglet « Comparer »** : tous les dossiers dans un tableau, une ligne par candidat et une colonne par mot-clé, avec la marque du surligneur dans chaque case (un clic ouvre la preuve). On trie par mot-clé et on filtre les candidats.
- **Actions sur plusieurs dossiers** : on coche des dossiers puis on leur ajoute des mots-clés (ou la liste par défaut), on retire un mot-clé, on les relit, on les exporte (CSV des seuls dossiers cochés) ou on les supprime.
- **Code réorganisé pour être relu facilement** : un fichier par rôle, en Python (`engine/` pour la lecture et les décisions, `server/` pour l'application) comme dans l'interface (`static/js/`). Le README explique le trajet d'un document. Les décisions sont inchangées (mêmes résultats sur les bancs d'essai).

## Version 1.5

- **Mots imbriqués** : un mot-clé n'est plus trouvé à l'intérieur d'un mot plus long. « pour » n'est plus « présent » à cause de « pourquoi », y compris quand ce mot arrive découpé : coupure en fin de ligne (« pour- / quoi »), trait d'union invisible du PDF, ou lettres que l'OCR a séparées alors qu'elles se touchent sur l'image.
- Restent trouvés : l'élision (« l'apprentissage », « d'ingénieur ») et un mot-clé coupé lui-même en fin de ligne (« apprentis- / sage »). Une partie de mot composé (« Master » dans « Master-Recherche ») est proposée « à vérifier ».

## Version 1.4

- **Logo** : une loupe posée sur un document, avec le K de KeyScan dans la lentille. Il sert d'icône d'application (Mac et Windows) et apparaît dans l'en-tête.
- **Police Syne** pour les titres, les noms et les chiffres : une grotesque large et originale, dessinée à Paris par Bonjour Monde pour le centre d'art Synesthésies (licence libre OFL).
- **Codes PIN réinitialisés à chaque nouvelle version** : à la première ouverture après une mise à jour, chaque profil choisit un nouveau code. Les dossiers, mots-clés et réglages sont conservés.

## Version 1.3

- **Nouvelle interface, « le bureau du jury »** : la liste des candidats reste à gauche (avec une recherche), le dossier ouvert à droite. Les mots-clés sont rangés par décision et surlignés comme au feutre : vert présent, jaune à vérifier ; une absence incertaine est soulignée en pointillé. Les preuves s'ouvrent dans un volet à côté du dossier.
- Polices intégrées, choisies pour la lecture : Atkinson Hyperlegible Next pour l'interface, Literata pour les noms et les extraits de documents.
- Les pages des documents utilisent les mêmes couleurs de surligneur que l'interface.
- Un document illisible est expliqué en clair (« fichier corrompu ou protégé ») au lieu d'un message technique.

## Version 1.2

- **Écriture manuscrite bien mieux lue** sur les vraies lettres (papier jauni, écriture cursive, lignes serrées) : découpage des lignes refait (grain du papier, pointillés et bords de carte ignorés, lignes qui se touchent séparées), et une lettre manuscrite n'est plus retournée à l'envers par erreur.
- **Où sont les mots « À vérifier »** : dans l'onglet Documents, chaque document liste ses mots à vérifier avec leur page ; un clic montre un zoom sur le mot, ce qui a été lu, et la page entière. Le bouton œil affiche le document avec tous ses mots-clés encadrés et nommés (vert : présent, orange : à vérifier).
- **Clics plus fiables** : un appui au bord d'un bouton, ou pendant le rafraîchissement d'une analyse en cours, n'est plus perdu.

## Version 1.1

- **Mots-clés propres à chaque dossier** : à la création, partir de la liste par défaut, copier un autre dossier ou partir de zéro, puis « Modifier les mots-clés » dans le dossier. La liste par défaut (onglet Mots-clés) n'est plus imposée à tous les dossiers.
- **Mot seulement approchant** (« these » pour « thèse », lecture manuscrite approximative) : il reste « À vérifier » même s'il est répété, et ne devient plus jamais « Présent ».
- **Fichiers en double** : un même fichier déposé deux fois est refusé et n'est jamais compté deux fois.
- **Documents illisibles** : alerte sur le dossier, « Absence incertaine » au lieu de « Absent », et colonne « Documents non lus » dans l'export CSV.
- Animations plus soignées (transitions de pages, anneaux, scores qui défilent), toujours à 60 images par seconde.
- Moteur utilisable en ligne de commande, sans interface : `python -m engine`.

Les dossiers existants gardent leurs mots-clés : chacun reçoit une copie de l'ancienne liste.

## Télécharger

| Ordinateur | Fichier |
|---|---|
| **Mac** à puce Apple (M1, M2, M3, M4…) | `KeyScan-Mac-AppleSilicon.dmg` |
| **Windows** 10 ou 11 (64 bits) | `KeyScan-Windows-Setup.exe` |

Tout est inclus : l'application, la lecture des scans (Tesseract, français + anglais) et la lecture de l'écriture manuscrite (TrOCR). Rien d'autre à installer, aucun accès Internet nécessaire ensuite.

## Installer

**Mac — méthode la plus simple (recommandée)** : ouvrir l'app **Terminal**, coller cette ligne puis Entrée. Elle télécharge, vérifie, installe et ouvre KeyScan, sans aucun blocage de macOS :

```
curl -fL -o /tmp/KeyScan.dmg https://github.com/Majic04/KEYSCAN/releases/latest/download/KeyScan-Mac-AppleSilicon.dmg && hdiutil attach -nobrowse -quiet /tmp/KeyScan.dmg && rm -rf /Applications/KeyScan.app && cp -R /Volumes/KeyScan/KeyScan.app /Applications/ && hdiutil detach -quiet /Volumes/KeyScan && xattr -dr com.apple.quarantine /Applications/KeyScan.app && rm /tmp/KeyScan.dmg && open /Applications/KeyScan.app
```

**Mac — à la main** : ouvrir le `.dmg`, glisser **KeyScan** dans **Applications**. Si macOS dit que le fichier ou l'application est **« endommagé »** (c'est ce qu'il affiche pour toute application non signée par Apple téléchargée avec un navigateur), coller dans le Terminal :
`xattr -c ~/Downloads/KeyScan-Mac-AppleSilicon.dmg` (pour le disque) ou `xattr -dr com.apple.quarantine /Applications/KeyScan.app` (pour l'application), puis rouvrir.

**Windows** : lancer `KeyScan-Windows-Setup.exe`. Si Windows affiche « Windows a protégé votre ordinateur », cliquer **« Informations complémentaires » → « Exécuter quand même »** (une seule fois). Aucun droit administrateur n'est nécessaire.

Les données (dossiers, mots-clés, réglages, codes PIN) sont conservées d'une version à l'autre. Une ancienne installation « dossier KeyScan » est reprise automatiquement au premier lancement.
