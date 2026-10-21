## Nouveautés de la version 1.1

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
