"""
Lance une étape de construction GitHub et rend son résultat lisible depuis l'API GitHub (« annotations ») :
  - en cas d'échec : les 60 dernières lignes affichées sont publiées comme annotation d'erreur ;
  - les lignes marquées « RÉSUMÉ: » par les bancs d'essai et le test final sont publiées comme notes.

usage : python build/ci.py [--note] "<titre>" <commande> [arguments…]
  --note : publie aussi la fin de l'affichage en cas de réussite (résultats des bancs d'essai)
"""
import subprocess
import sys
from collections import deque


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


args = sys.argv[1:]
note_all = args[0] == "--note"
if note_all:
    args = args[1:]
title, cmd = esc(args[0]).replace(":", "%3A").replace(",", "%2C"), args[1:]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
tail = deque(maxlen=80)
notes = []
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, encoding="utf-8", errors="replace")
for line in p.stdout:
    sys.stdout.write(line)
    sys.stdout.flush()
    line = line.rstrip("\n")
    tail.append(line)
    if line.startswith("RÉSUMÉ:") or line.startswith("OK     ") or line.startswith("ÉCHEC  "):
        notes.append(line)
code = p.wait()
if note_all and not code:
    print(f"::notice title={title}::" + esc("\n".join(tail)[-60000:]))
elif notes:
    print(f"::notice title={title}::" + esc("\n".join(notes)[-60000:]))
if code:
    print(f"::error title={title} (code {code})::" + esc("\n".join(tail)[-60000:]))
sys.exit(code)
