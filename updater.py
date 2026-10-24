"""
Mise à jour automatique de l'application installée (Mac et Windows).

Comment ça marche :
  1. Au lancement, puis toutes les 6 heures, on demande à GitHub le numéro de la dernière version publiée.
     C'est le seul échange de KeyScan avec Internet : aucun document ni aucune donnée ne quitte l'ordinateur.
  2. Si elle est plus récente que celle installée, son installateur est téléchargé en arrière-plan
     (dans le dossier de KeyScan, sous « mises-a-jour »), puis son empreinte SHA-256 est vérifiée.
  3. L'interface affiche « Mise à jour prête ». Un clic sur « Redémarrer » ferme KeyScan, installe la nouvelle
     version et la rouvre. Sans clic, elle s'installe à la fermeture de KeyScan.

L'installation elle-même est faite par un petit script lancé juste avant de quitter (il attend que KeyScan
soit fermé pour remplacer ses fichiers) :
    build/update/install_mac.sh        Mac : copie KeyScan.app depuis l'image disque
    build/update/install_windows.cmd   Windows : lance l'installateur en mode silencieux

Pour essayer à la main :  KeyScan --check-update   (affiche la dernière version publiée)
Pour désactiver :         variable d'environnement KEYSCAN_NO_UPDATE=1
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.request

REPOSITORY = "Majic04/KEYSCAN"
LATEST_RELEASE = os.environ.get("KEYSCAN_UPDATE_URL") or f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
INSTALLERS = {"darwin": "KeyScan-Mac-AppleSilicon.dmg", "win32": "KeyScan-Windows-Setup.exe"}
CHECK_EVERY = 6 * 3600          # secondes entre deux vérifications

FROZEN = getattr(sys, "frozen", False)
BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BUNDLE, "update") if FROZEN else os.path.join(BUNDLE, "build", "update")

# Ce que l'interface affiche (voir status()).
_state = {"current": None, "latest": None, "step": "off", "progress": 0.0, "message": "", "file": None}
_lock = threading.Lock()
_installing = False


# =========================================================================== petites fonctions
def version_numbers(text: str) -> tuple[int, ...]:
    """« v1.10.2 » → (1, 10, 2) : les versions se comparent nombre par nombre (1.10 est après 1.9)."""
    return tuple(int(number) for number in re.findall(r"\d+", text)[:3])


def is_newer(candidate: str, current: str) -> bool:
    return version_numbers(candidate) > version_numbers(current)


def _set(**values):
    with _lock:
        _state.update(values)


def status() -> dict:
    """
    Pour l'interface : {"current", "latest", "step", "progress", "message"}.
    step vaut : "off" (désactivée), "check" (vérification), "uptodate" (à jour), "download" (téléchargement,
    progress de 0 à 1), "ready" (prête à installer), "error" (message explique pourquoi).
    """
    with _lock:
        return {key: value for key, value in _state.items() if key != "file"}


def _https_context() -> ssl.SSLContext:
    """Certificats du système, plus ceux fournis avec l'application (certifi) : l'application installée n'a pas toujours les premiers."""
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(certifi.where())
    except (ImportError, OSError):
        pass
    return context


def _open(url: str, timeout: float = 30):
    request = urllib.request.Request(url, headers={"User-Agent": "KeyScan", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=timeout, context=_https_context())


def installed_app() -> str | None:
    """Ce que la mise à jour remplace : KeyScan.app (Mac) ou KeyScan.exe (Windows). None hors application installée."""
    if not FROZEN:
        return None
    if sys.platform == "darwin":
        app = os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..", ".."))   # …/KeyScan.app
        if "/AppTranslocation/" in app:          # lancé depuis un emplacement temporaire de macOS
            app = "/Applications/KeyScan.app"
        return app if app.endswith(".app") else None
    if sys.platform == "win32":
        return sys.executable
    return None


# =========================================================================== 1. vérifier, 2. télécharger
def latest_release() -> dict:
    """La dernière version publiée : {"version", "url", "size", "sha256"} (l'installateur pour cet ordinateur)."""
    with _open(LATEST_RELEASE) as response:
        release = json.loads(response.read().decode("utf-8"))
    wanted = INSTALLERS.get(sys.platform, "")
    for asset in release.get("assets", []):
        if asset.get("name") == wanted:
            digest = asset.get("digest") or ""                 # « sha256:… », fourni par GitHub
            return {"version": release["tag_name"].lstrip("v"), "url": asset["browser_download_url"],
                    "size": asset.get("size") or 0, "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else None}
    return {"version": release["tag_name"].lstrip("v"), "url": None, "size": 0, "sha256": None}


def _download(release: dict, folder: str) -> str:
    """Télécharge l'installateur (d'abord dans un fichier « .part ») et vérifie sa taille et son empreinte."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{release['version']}-{INSTALLERS[sys.platform]}")
    if os.path.exists(path):
        return path                                            # déjà téléchargé (et vérifié) lors d'un lancement précédent
    for old in os.listdir(folder):                             # anciens téléchargements : inutiles
        if not old.startswith(release["version"] + "-") and old != "installation.log":
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
    digest, received = hashlib.sha256(), 0
    try:
        with _open(release["url"], timeout=60) as response, open(path + ".part", "wb") as f:
            while chunk := response.read(1 << 20):
                f.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if release["size"]:
                    _set(progress=round(received / release["size"], 3))
        if release["size"] and received != release["size"]:
            raise OSError("téléchargement incomplet")
        if release["sha256"] and digest.hexdigest() != release["sha256"]:
            raise OSError("fichier abîmé pendant le téléchargement")
    except Exception:
        os.remove(path + ".part")                              # rien de partiel ne reste sur le disque
        raise
    os.replace(path + ".part", path)
    return path


def check_now(folder: str):
    """Une vérification complète : y a-t-il plus récent ? si oui, téléchargement."""
    if _state["step"] in ("check", "download", "ready"):
        return
    _set(step="check", message="")
    try:
        release = latest_release()
        _set(latest=release["version"])
        if not is_newer(release["version"], _state["current"]):
            return _set(step="uptodate")
        if not release["url"]:
            return _set(step="uptodate")                       # publiée sans installateur pour cet ordinateur
        app = installed_app()
        if not app or not os.access(os.path.dirname(app), os.W_OK):
            return _set(step="error", message="Mise à jour automatique impossible ici : installez KeyScan dans le dossier Applications.")
        _set(step="download", progress=0.0)
        _set(step="ready", file=_download(release, folder), progress=1.0)
        print(f"Mise à jour {release['version']} téléchargée : installée à la fermeture de KeyScan")
    except Exception as error:  # noqa: BLE001 — pas d'Internet, GitHub indisponible… : on réessaiera plus tard
        _set(step="error", message=f"Mise à jour impossible pour l'instant ({error}). Nouvel essai plus tard."[:200])
        print("Mise à jour :", error)


def start(current_version: str, folder: str) -> bool:
    """Lance la vérification au démarrage puis toutes les 6 heures (application installée seulement)."""
    _set(current=current_version)
    if not installed_app() or os.environ.get("KEYSCAN_NO_UPDATE"):
        return False

    def loop():
        while True:
            check_now(folder)
            time.sleep(CHECK_EVERY)
            if _state["step"] == "error":
                _set(step="uptodate")                          # on retente

    threading.Thread(target=loop, daemon=True).start()
    return True


# =========================================================================== 3. installer
def install(relaunch: bool) -> bool:
    """
    Lance le script d'installation, qui attend la fermeture de KeyScan puis remplace l'application.
    À appeler juste avant de quitter. Retourne False s'il n'y a rien à installer.
    """
    global _installing
    with _lock:
        installer, app = _state["file"], installed_app()
        if _installing or _state["step"] != "ready" or not installer or not app:
            return False
        _installing = True
    arguments = [str(os.getpid()), installer, app, "1" if relaunch else "0"]
    if sys.platform == "darwin":
        subprocess.Popen(["/bin/bash", os.path.join(SCRIPTS, "install_mac.sh"), *arguments],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        command = ["cmd", "/c", os.path.join(SCRIPTS, "install_windows.cmd"), *arguments]
        try:   # le script doit survivre à la fermeture de KeyScan
            subprocess.Popen(command, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, close_fds=True)
        except OSError:
            subprocess.Popen(command, creationflags=flags, close_fds=True)
    print("Installation de la mise à jour lancée" + (" (KeyScan va redémarrer)" if relaunch else ""))
    return True


# =========================================================================== essai à la main
def print_latest(current_version: str) -> int:
    """KeyScan --check-update : affiche la dernière version publiée (vérifie aussi l'accès sécurisé à GitHub)."""
    try:
        release = latest_release()
    except Exception as error:  # noqa: BLE001
        print("Vérification impossible :", error)
        return 1
    newer = is_newer(release["version"], current_version)
    print(f"Version installée : {current_version} · dernière version publiée : {release['version']}"
          + (" → mise à jour disponible" if newer else " → à jour"))
    print("Installateur pour cet ordinateur :", release["url"] or "aucun")
    return 0
