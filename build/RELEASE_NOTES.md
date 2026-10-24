## Nouveautés de la version 1.7

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
