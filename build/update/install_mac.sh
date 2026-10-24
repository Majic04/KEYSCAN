#!/bin/bash
# Installe une nouvelle version de KeyScan sur Mac, une fois l'application fermée (lancé par updater.py).
#   install_mac.sh <numéro du processus KeyScan> <image disque .dmg> <chemin de KeyScan.app> <relancer : 1 ou 0>
# Le compte rendu est écrit dans « installation.log », à côté de l'image disque.
PID="$1"; DMG="$2"; APP="$3"; RELAUNCH="${4:-0}"
exec >>"$(dirname "$DMG")/installation.log" 2>&1
echo "== $(date '+%Y-%m-%d %H:%M:%S') : $DMG → $APP"

# 1. attendre que KeyScan soit fermé (2 minutes au plus)
for _ in $(seq 1 240); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done

# 2. ouvrir l'image disque
MOUNT="$(mktemp -d /tmp/keyscan-maj.XXXXXX)"
if ! hdiutil attach -nobrowse -noautoopen -quiet -mountpoint "$MOUNT" "$DMG"; then
  echo "Image disque illisible : elle sera téléchargée de nouveau"
  rm -f "$DMG"; rmdir "$MOUNT"
  [ "$RELAUNCH" = "1" ] && open "$APP"
  exit 1
fi

# 3. remplacer l'application ; l'ancienne est gardée de côté tant que la copie n'est pas complète
rm -rf "$APP.ancienne"
if mv "$APP" "$APP.ancienne" && ditto "$MOUNT/KeyScan.app" "$APP"; then
  rm -rf "$APP.ancienne"
  rm -f "$DMG"
  echo "Nouvelle version installée"
else
  echo "Échec de la copie : l'ancienne version est remise en place"
  rm -rf "$APP"
  mv "$APP.ancienne" "$APP"
fi
hdiutil detach -quiet "$MOUNT" || hdiutil detach -force -quiet "$MOUNT"
rmdir "$MOUNT" 2>/dev/null
xattr -dr com.apple.quarantine "$APP" 2>/dev/null   # pas de blocage « application téléchargée » au lancement

# 4. rouvrir KeyScan si on l'a demandé (bouton « Redémarrer »)
[ "$RELAUNCH" = "1" ] && open "$APP"
exit 0
