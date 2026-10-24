"""
Test (GitHub, Windows) : l'installateur qu'on vient de construire est lancé par le script de mise à jour,
en mode silencieux, comme le fait KeyScan à sa fermeture.

usage : python build/update/test_install_windows.py <installateur .exe>
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
work = tempfile.mkdtemp(prefix="keyscan-maj-")
setup = os.path.join(work, "setup.exe")
shutil.copy(sys.argv[1], setup)
app_exe = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "KeyScan", "KeyScan.exe")

# 999999 : numéro d'un processus qui n'existe pas (KeyScan est déjà fermé)
subprocess.run(["cmd", "/c", os.path.join(HERE, "install_windows.cmd"), "999999", setup, app_exe, "0"], timeout=900)
log_path = os.path.join(work, "installation.log")
log = open(log_path, encoding="utf-8", errors="replace").read() if os.path.exists(log_path) else ""
print(log)

failures = []
for name, ok in [("installation silencieuse réussie", "Nouvelle version installee" in log),
                 ("KeyScan.exe installé", os.path.exists(app_exe)),
                 ("installateur supprimé", not os.path.exists(setup))]:
    print(("OK     " if ok else "ÉCHEC  ") + name)
    if not ok:
        failures.append(name)
sys.exit(1 if failures else 0)
