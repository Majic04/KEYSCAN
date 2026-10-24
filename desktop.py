"""
KeyScan — application de bureau (Mac et Windows).

Ce fichier est le point d'entrée de l'application installée :
  - il prépare les chemins (données de l'utilisateur, Tesseract et modèle manuscrit embarqués) ;
  - il démarre le serveur KeyScan sur l'ordinateur (127.0.0.1, jamais accessible depuis le réseau) ;
  - il ouvre une fenêtre native (WebKit sur Mac, Edge WebView2 sur Windows) qui affiche l'interface.

Options (utilisées pour les tests automatiques) :
  --server-only     démarre le serveur sans fenêtre
  --port N          port du serveur (par défaut 47815)
  --selftest        vérifie Tesseract et le module manuscrit embarqués, puis quitte
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

APP_NAME = "KeyScan"
APP_VERSION = "1.5.0"          # version unique : reprise par la construction (PyInstaller, Inno Setup, étiquette Git)
DEFAULT_PORT = 47815
FROZEN = getattr(sys, "frozen", False)
BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


# =========================================================================== dossiers
def user_dir() -> str:
    """Dossier des données de l'utilisateur (survit aux mises à jour de l'application)."""
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    path = os.environ.get("KEYSCAN_HOME") or os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


HOME = user_dir()
DATA = os.path.join(HOME, "data")
LOG = os.path.join(HOME, "keyscan.log")


def setup_environment():
    """Chemins utilisés par le serveur et le moteur (à faire AVANT d'importer app)."""
    os.environ["KEYSCAN_DATA"] = DATA
    os.environ["KEYSCAN_MODELS"] = os.path.join(HOME, "models")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")          # l'application n'appelle jamais Internet
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    # Tesseract embarqué
    tdir = os.path.join(BUNDLE, "tesseract")
    exe = os.path.join(tdir, "tesseract.exe" if os.name == "nt" else "tesseract")
    if os.path.exists(exe):
        os.environ["TESSERACT_CMD"] = exe
        os.environ["TESSDATA_PREFIX"] = os.path.join(tdir, "tessdata")
        if os.name == "nt":
            os.environ["PATH"] = tdir + os.pathsep + os.environ.get("PATH", "")
    # modèle d'écriture manuscrite embarqué
    mdir = os.path.join(BUNDLE, "models", "trocr-fr")
    if os.path.isdir(mdir) and not os.environ.get("KWF_HTR_MODEL"):
        os.environ["KWF_HTR_MODEL"] = mdir


def redirect_output():
    """Application sans console : tout ce qui est affiché va dans un journal (utile en cas de souci)."""
    if FROZEN or not sys.stdout or not sys.stdout.isatty():
        try:
            if os.path.exists(LOG) and os.path.getsize(LOG) > 5_000_000:
                os.replace(LOG, LOG + ".1")
            f = open(LOG, "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = f
            print(f"\n===== {APP_NAME} {APP_VERSION} — {time.strftime('%Y-%m-%d %H:%M:%S')} =====")
        except OSError:
            pass


# =========================================================================== reprise d'une ancienne installation
LEGACY = [
    os.path.join("~", "Documents", "KeyScan", "data"),
    os.path.join("~", "Downloads", "keyscan", "data"),
    os.path.join("~", "Downloads", "KeyScan", "data"),
    os.path.join("~", "Desktop", "KeyScan", "data"),
    os.path.join("~", "Documents", "keyscan", "data"),
]


def migrate_legacy_data() -> str | None:
    """
    Au premier lancement, reprend les dossiers, mots-clés, réglages et codes PIN d'une installation
    « dossier KeyScan » précédente (copie : l'ancienne installation n'est pas modifiée).
    """
    if os.path.exists(os.path.join(DATA, "keyscan.db")):
        return None
    for cand in LEGACY:
        src = os.path.expanduser(cand)
        if not os.path.exists(os.path.join(src, "keyscan.db")):
            continue
        os.makedirs(DATA, exist_ok=True)
        shutil.copytree(src, DATA, dirs_exist_ok=True)
        new_files = os.path.join(DATA, "files")
        con = sqlite3.connect(os.path.join(DATA, "keyscan.db"))
        try:   # chaque document est retrouvé par son nom de fichier dans le nouveau dossier
            for doc_id, path in con.execute("SELECT id, path FROM documents").fetchall():
                cand = os.path.join(new_files, os.path.basename(path.replace("\\", "/")))
                if os.path.exists(cand):
                    con.execute("UPDATE documents SET path=? WHERE id=?", (cand, doc_id))
            con.commit()
        finally:
            con.close()
        print(f"Données reprises depuis {src}")
        return src
    return None


# =========================================================================== serveur
def _is_keyscan(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/session", timeout=1.5) as r:
            return "profiles" in json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def _free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def start_server(port: int):
    """Démarre KeyScan dans un fil d'exécution ; retourne (url, serveur ou None si déjà ouvert ailleurs)."""
    if not _free(port):
        if _is_keyscan(port):                # KeyScan est déjà ouvert : on réutilise son serveur
            return f"http://127.0.0.1:{port}/", None
        with socket.socket() as s:           # port occupé par autre chose : on en prend un libre
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    import app as keyscan
    from werkzeug.serving import make_server
    if keyscan.reset_pins_on_new_version(APP_VERSION):
        print(f"Nouvelle version {APP_VERSION} : codes PIN effacés, chaque profil en choisira un nouveau")
    keyscan.start()
    srv = make_server("127.0.0.1", port, keyscan.app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/", srv


# =========================================================================== pont fenêtre ↔ système
class NativeAPI:
    """Fonctions appelées par l'interface quand elle tourne dans la fenêtre de l'application."""

    def __init__(self):
        self.window = None

    def save_file(self, filename: str, text: str) -> bool:
        """Enregistrer (export CSV) via la boîte de dialogue du système."""
        import webview
        res = self.window.create_file_dialog(webview.SAVE_DIALOG, save_filename=filename,
                                             file_types=("Fichier CSV (*.csv)", "Tous les fichiers (*.*)"))
        if not res:
            return False
        path = res if isinstance(res, str) else res[0]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text.lstrip("﻿"))
        return True

    def open_file(self, filename: str, b64: str) -> bool:
        """Ouvrir un document déposé avec l'application par défaut (Aperçu, Acrobat…)."""
        d = tempfile.mkdtemp(prefix="keyscan-")
        path = os.path.join(d, os.path.basename(filename) or "document")
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", path])
        return True

    def version(self) -> str:
        return APP_VERSION


# =========================================================================== auto-test (intégration continue)
def selftest() -> int:
    """Vérifie que Tesseract (avec le français) et le module manuscrit embarqués fonctionnent."""
    # sous Windows, une application sans console n'a pas de sortie : le compte rendu est aussi écrit dans un fichier
    report = open(os.path.join(HOME, "selftest.txt"), "w", encoding="utf-8")
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    def print(*args):  # noqa: A001
        line = " ".join(str(x) for x in args)
        report.write(line + "\n"); report.flush()
        if sys.stdout:
            sys.stdout.write(line + "\n")
    import pytesseract
    from engine.extract import configure_tesseract
    ok = True
    cmd = configure_tesseract()
    print("Tesseract :", cmd)
    try:
        langs = pytesseract.get_languages(config="")
        print("Langues :", langs)
        ok &= "fra" in langs and "eng" in langs
    except Exception as e:  # noqa: BLE001
        print("Tesseract KO :", e)
        ok = False
    from engine import handwriting
    st = handwriting.status()
    print("Écriture manuscrite :", st)
    sample = os.path.join(BUNDLE, "exemples", "manuscrit.png")
    if st.get("ready") and os.path.exists(sample):
        from PIL import Image
        g = Image.open(sample).convert("L")
        t = time.time()
        res = handwriting.recognize([g.crop(b) for b in handwriting.segment_lines(g)])
        for text, conf in res:
            print(f"  [{conf:5.1f} %] {text}")
        print(f"  lecture en {time.time() - t:.1f} s")
        ok &= bool(res) and any(text for text, _ in res)
    else:
        ok = False
    print("AUTO-TEST", "OK" if ok else "ÉCHEC")
    return 0 if ok else 1


# =========================================================================== démarrage
def main():
    import argparse
    ap = argparse.ArgumentParser(prog=APP_NAME)
    ap.add_argument("--server-only", action="store_true")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--reset-pin", metavar="NOM", help="efface le code PIN d'un profil (code oublié)")
    a, _ = ap.parse_known_args()

    setup_environment()
    if a.selftest:
        sys.exit(selftest())
    if a.reset_pin:
        import app as keyscan
        keyscan.init_db()
        with keyscan.db() as con:
            n = con.execute("DELETE FROM settings WHERE key=?", (f"pin:{a.reset_pin}",)).rowcount
        msg = (f"Code de « {a.reset_pin} » effacé : un nouveau code sera demandé à la prochaine ouverture."
               if n else f"Aucun code trouvé pour « {a.reset_pin} ».")
        print(msg)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
        sys.exit(0)
    if not a.server_only or FROZEN:
        redirect_output()           # application installée : tout va dans le journal keyscan.log
    migrate_legacy_data()
    url, srv = start_server(a.port)
    print(f"{APP_NAME} {APP_VERSION} : {url}  (données : {DATA})", flush=True)

    if a.server_only:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    try:
        import webview
    except Exception as e:  # noqa: BLE001 — pas de fenêtre native : on ouvre le navigateur
        print("Fenêtre native indisponible :", e)
        import webbrowser
        webbrowser.open(url)
        while True:
            time.sleep(3600)

    api = NativeAPI()
    window = webview.create_window(
        APP_NAME, url, js_api=api, width=1280, height=860, min_size=(900, 640),
        background_color="#EAF3FA", text_select=True,
    )
    api.window = window
    try:
        webview.start(private_mode=True)     # rien n'est conservé par la fenêtre : le code PIN est redemandé à chaque ouverture
    finally:
        if srv:
            srv.shutdown()
    os._exit(0)


if __name__ == "__main__":
    if FROZEN and BUNDLE not in sys.path:
        sys.path.insert(0, BUNDLE)
    main()
