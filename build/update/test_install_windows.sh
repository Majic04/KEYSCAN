#!/bin/bash
# Test (GitHub, Windows) : l'installateur qu'on vient de construire est lancé par le script de mise à jour,
# en mode silencieux, comme le fait KeyScan à sa fermeture.
#   bash build/update/test_install_windows.sh <installateur .exe>
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"; cp "$1" "$WORK/setup.exe"
APPEXE="$LOCALAPPDATA\\Programs\\KeyScan\\KeyScan.exe"
# 999999 : numéro d'un processus qui n'existe pas (KeyScan déjà fermé)
cmd.exe //c "$(cygpath -w "$ROOT/build/update/install_windows.cmd")" 999999 "$(cygpath -w "$WORK/setup.exe")" "$APPEXE" 0
cat "$WORK/installation.log"
check() { if eval "$2"; then echo "OK     $1"; else echo "ÉCHEC  $1"; FAIL=1; fi; }
FAIL=0
check "installation silencieuse réussie" 'grep -q "Nouvelle version installee" "$WORK/installation.log"'
check "KeyScan.exe installé" '[ -f "$(cygpath -u "$APPEXE")" ]'
check "installateur supprimé" '[ ! -e "$WORK/setup.exe" ]'
exit $FAIL
