"""
Tests de la mise à jour automatique (updater.py), avec un faux « GitHub » sur l'ordinateur :
comparaison des versions, lecture de la dernière publication, téléchargement vérifié par son empreinte.
L'installation elle-même (scripts de build/update) est testée sur de vrais Mac et Windows par GitHub.

usage : python tests/test_mise_a_jour.py      (code de sortie 1 en cas d'échec)
"""
import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import updater  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("OK     " if cond else "ÉCHEC  ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


# --------------------------------------------------------------------------- comparaison des versions
check("1.10.0 est plus récente que 1.9.3", updater.is_newer("1.10.0", "1.9.3"))
check("v1.6.1 est plus récente que 1.6.0", updater.is_newer("v1.6.1", "1.6.0"))
check("même version : pas de mise à jour", not updater.is_newer("1.6.0", "1.6.0"))
check("version plus ancienne ignorée", not updater.is_newer("1.5.0", "1.6.0"))

# --------------------------------------------------------------------------- un faux GitHub
INSTALLER = os.urandom(300_000)                       # le « fichier d'installation » publié
release = {"tag_name": "v9.0.0", "assets": []}


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(release).encode() if self.path == "/latest" else INSTALLER
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), FakeGitHub)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}"
updater.LATEST_RELEASE = BASE + "/latest"
updater.INSTALLERS[sys.platform] = "KeyScan-Test.dmg"
updater._open = lambda url, timeout=30: __import__("urllib.request").request.urlopen(url, timeout=timeout)   # http local
work = tempfile.mkdtemp(prefix="keyscan-maj-")
updater.installed_app = lambda: os.path.join(work, "KeyScan.app")
folder = os.path.join(work, "mises-a-jour")


def publish(digest):
    release["assets"] = [{"name": "KeyScan-Test.dmg", "browser_download_url": BASE + "/installateur", "size": len(INSTALLER),
                          "digest": f"sha256:{digest}"}]


publish(hashlib.sha256(INSTALLER).hexdigest())
info = updater.latest_release()
check("dernière publication lue", info["version"] == "9.0.0" and info["url"].endswith("/installateur") and info["sha256"], str(info))

updater._set(current="9.0.0", step="off", file=None)
updater.check_now(folder)
check("déjà à jour : rien n'est téléchargé", updater.status()["step"] == "uptodate" and not os.path.exists(folder))

publish("0" * 64)                                     # empreinte fausse : fichier abîmé
updater._set(current="1.6.0", step="off", file=None)
updater.check_now(folder)
check("fichier abîmé refusé", updater.status()["step"] == "error" and not os.listdir(folder),
      updater.status()["message"])

publish(hashlib.sha256(INSTALLER).hexdigest())
updater._set(step="off")
updater.check_now(folder)
state = updater.status()
check("nouvelle version téléchargée et vérifiée", state["step"] == "ready" and state["latest"] == "9.0.0" and state["progress"] == 1.0, str(state))
path = os.path.join(folder, "9.0.0-KeyScan-Test.dmg")
check("fichier complet", os.path.exists(path) and open(path, "rb").read() == INSTALLER)

print("\nÉchecs : " + ", ".join(failures) if failures else "\nTous les tests de mise à jour sont passés.")
sys.exit(1 if failures else 0)
