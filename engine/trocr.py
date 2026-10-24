"""
Le modèle qui lit l'écriture manuscrite : TrOCR (un réseau de neurones qui transforme l'image
d'une ligne écrite à la main en texte).

Ce fichier s'occupe uniquement du modèle : savoir s'il est installé, le charger, lui faire lire
des images, et l'installer. Le repérage des lignes manuscrites sur une page est dans handwriting.py.

Modèles possibles (téléchargés une seule fois, puis utilisés sans Internet) :
  - "fr" : agomberto/trocr-large-handwritten-fr, entraîné sur de l'écriture française (licence MIT) ;
  - "en" : microsoft/trocr-base-handwritten, anglais, plus léger.
  On peut aussi donner le chemin d'un dossier contenant un modèle (c'est ce que fait l'application installée).

En ligne de commande :
    python -m engine.trocr               état du module
    python -m engine.trocr --install fr  téléchargement du modèle (mode Python uniquement)
    python -m engine.trocr --selftest    lecture de exemples/manuscrit.png
"""
from __future__ import annotations

import importlib.util
import json
import os
import threading
import time

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Dossier des modèles : fourni par l'application de bureau (dossier de l'utilisateur), sinon KeyScan/models.
MODELS_DIR = os.environ.get("KEYSCAN_MODELS") or os.path.join(ROOT, "models")
CHOICE_FILE = os.path.join(os.path.dirname(MODELS_DIR) if os.environ.get("KEYSCAN_MODELS") else ROOT, "manuscrit.json")
os.environ.setdefault("HF_HOME", MODELS_DIR)               # les modèles restent dans le dossier de KeyScan
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

MODELS = {
    "fr": {"model": "agomberto/trocr-large-handwritten-fr", "processor": "microsoft/trocr-large-handwritten",
           "label": "TrOCR français (manuscrit)", "size": "≈ 2,3 Go"},
    "en": {"model": "microsoft/trocr-base-handwritten", "processor": "microsoft/trocr-base-handwritten",
           "label": "TrOCR anglais (manuscrit, léger)", "size": "≈ 1,3 Go"},
}
LINES_PER_BATCH = 6                # nombre d'images de lignes lues ensemble

_model_lock = threading.Lock()     # un seul passage à la fois dans le modèle (plusieurs documents sont lus en parallèle)
_loaded = None                     # {"processor", "model", "tokenizer", "device"} une fois chargé


# =========================================================================== quel modèle, est-il installé ?
def chosen_model() -> dict:
    """Le modèle choisi : variable KWF_HTR_MODEL, sinon fichier manuscrit.json, sinon le modèle français."""
    key = os.environ.get("KWF_HTR_MODEL")
    if not key and os.path.exists(CHOICE_FILE):
        try:
            with open(CHOICE_FILE, encoding="utf-8") as f:
                key = json.load(f).get("model")
        except (OSError, ValueError):
            key = None
    key = key or "fr"
    if key in MODELS:
        return {"key": key, **MODELS[key]}
    # un chemin de dossier : modèle et préparation des images sont dans ce même dossier
    return {"key": key, "model": key, "processor": key, "label": f"modèle local ({os.path.basename(key)})", "size": ""}


def libraries_installed() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("torch", "transformers"))


def _downloaded(repo: str) -> bool:
    if os.path.isdir(repo):
        return True
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 — absent du disque
        return False


def status() -> dict:
    """État du module, affiché dans les Réglages : {"model", "label", "libraries", "ready"}."""
    spec = chosen_model()
    ready = libraries_installed() and _downloaded(spec["model"]) and _downloaded(spec["processor"])
    return {"model": spec["key"], "label": spec["label"], "libraries": libraries_installed(), "ready": ready}


def available() -> bool:
    return status()["ready"]


# =========================================================================== chargement
def _best_device(torch) -> str:
    """Carte graphique si elle fonctionne (Apple : « mps », NVIDIA : « cuda »), sinon processeur (« cpu »)."""
    if os.environ.get("KEYSCAN_HTR_DEVICE"):
        return os.environ["KEYSCAN_HTR_DEVICE"]
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        try:   # certaines machines virtuelles annoncent « mps » sans pouvoir s'en servir : on essaie
            (torch.ones(256, 256, device="mps") * 2).sum().item()
            return "mps"
        except Exception:  # noqa: BLE001
            pass
    return "cpu"


def _load() -> dict:
    """Charge le modèle la première fois qu'on en a besoin (quelques secondes), puis le garde en mémoire."""
    global _loaded
    with _model_lock:
        if _loaded is None:
            import torch
            from transformers import AutoTokenizer, TrOCRProcessor, VisionEncoderDecoderModel
            from transformers.utils import logging as hf_logging
            hf_logging.set_verbosity_error()               # pas de messages techniques
            spec = chosen_model()
            processor = TrOCRProcessor.from_pretrained(spec["processor"], local_files_only=True)
            # le modèle embarqué est stocké en demi-précision (2 fois plus léger) ; on le remet en pleine précision
            model = VisionEncoderDecoderModel.from_pretrained(spec["model"], torch_dtype=torch.float32, local_files_only=True)
            tokenizer = AutoTokenizer.from_pretrained(spec["model"], local_files_only=True)
            if model.config.decoder_start_token_id is None:
                model.config.decoder_start_token_id = tokenizer.cls_token_id or tokenizer.bos_token_id
            if model.config.pad_token_id is None:
                model.config.pad_token_id = tokenizer.pad_token_id
            device = _best_device(torch)
            model.to(device).eval()
            _loaded = {"processor": processor, "model": model, "tokenizer": tokenizer, "device": device}
        return _loaded


def _move_to_cpu():
    """La carte graphique a échoué (mémoire…) : on continue sur le processeur."""
    with _model_lock:
        if _loaded and _loaded["device"] != "cpu":
            print(f"[manuscrit] {_loaded['device']} indisponible : lecture sur le processeur", flush=True)
            _loaded["model"].to("cpu")
            _loaded["device"] = "cpu"


# =========================================================================== lecture
def read_lines(images: list[Image.Image]) -> list[tuple[str, float]]:
    """Lit des images de lignes manuscrites. Retourne [(texte lu, confiance de 0 à 100)], dans le même ordre."""
    if not images:
        return []
    try:
        return _read_lines(images)
    except RuntimeError:
        if _loaded is None or _loaded["device"] == "cpu":
            raise
        _move_to_cpu()
        return _read_lines(images)


def _read_lines(images: list[Image.Image]) -> list[tuple[str, float]]:
    import torch
    m = _load()
    results = []
    for start in range(0, len(images), LINES_PER_BATCH):
        batch = [image.convert("RGB") for image in images[start:start + LINES_PER_BATCH]]
        pixels = m["processor"](images=batch, return_tensors="pt").pixel_values.to(m["device"])
        with _model_lock, torch.no_grad():
            out = m["model"].generate(pixels, max_new_tokens=64, num_beams=1, output_scores=True, return_dict_in_generate=True)
            log_probs = m["model"].compute_transition_scores(out.sequences, out.scores, normalize_logits=True)
        texts = m["tokenizer"].batch_decode(out.sequences, skip_special_tokens=True)
        for i, text in enumerate(texts):
            results.append((text.strip(), _line_confidence(m, out.sequences[i, 1:], log_probs[i])))
    return results


def _line_confidence(m: dict, generated_ids, log_probs) -> float:
    """
    Confiance d'une ligne = probabilité moyenne des caractères écrits par le modèle
    (exponentielle de la moyenne des log-probabilités, en ignorant le remplissage).
    """
    import torch
    pad = m["model"].config.pad_token_id
    keep = [j for j in range(log_probs.shape[0]) if j < len(generated_ids) and int(generated_ids[j]) != pad]
    values = log_probs[keep].float() if keep else torch.tensor([-5.0])
    values = values[torch.isfinite(values)]
    if not len(values):
        return 0.0
    return round(float(torch.exp(values.mean()).item()) * 100, 1)


# =========================================================================== installation et test (ligne de commande)
def install(key: str):
    """
    Télécharge seulement ce qui sert à lire : configuration, vocabulaire et poids du modèle
    (le dépôt du modèle français contient aussi plusieurs Go de fichiers d'entraînement, inutiles ici).
    """
    from huggingface_hub import HfApi, snapshot_download
    spec = {"key": key, **MODELS[key]}
    print(f"Téléchargement du modèle « {spec['label']} » ({spec['size']}) dans {MODELS_DIR}")
    print("C'est fait une seule fois ; ensuite KeyScan fonctionne hors ligne.\n")
    small_files = ["*.json", "merges.txt", "vocab.*", "*.model"]
    files = HfApi().list_repo_files(spec["model"])
    weights = [f for f in files if f.endswith(".safetensors")] or [f for f in files if f == "pytorch_model.bin"]
    if not weights:
        raise SystemExit(f"Aucun fichier de poids trouvé dans {spec['model']}")
    snapshot_download(spec["model"], allow_patterns=small_files + weights)
    if spec["processor"] != spec["model"]:
        snapshot_download(spec["processor"], allow_patterns=small_files)
    with open(CHOICE_FILE, "w", encoding="utf-8") as f:
        json.dump({"model": key}, f)
    print("\nModèle installé.")


def selftest(path: str | None = None):
    from .handwriting import find_text_lines
    path = path or os.path.join(ROOT, "exemples", "manuscrit.png")
    state = status()
    print(f"Module manuscrit : {state['label']}, prêt : {'oui' if state['ready'] else 'non'}")
    if not state["ready"]:
        raise SystemExit("Modèle absent : lancez d'abord  python -m engine.trocr --install fr")
    gray = Image.open(path).convert("L")
    started = time.time()
    lines = find_text_lines(gray)
    print(f"{len(lines)} ligne(s) détectée(s) dans {os.path.basename(path)}")
    for text, confidence in read_lines([gray.crop(box) for box in lines]):
        print(f"  [{confidence:5.1f} %] {text}")
    print(f"Lecture en {time.time() - started:.1f} s")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Lecture de l'écriture manuscrite (TrOCR)")
    parser.add_argument("--install", choices=sorted(MODELS), help="télécharge le modèle (fr ou en)")
    parser.add_argument("--selftest", nargs="?", const="", help="lit une image de test (par défaut exemples/manuscrit.png)")
    args = parser.parse_args()
    if args.install:
        try:
            install(args.install)
        except KeyboardInterrupt:
            raise SystemExit("\nTéléchargement interrompu : relancez l'installation, elle reprendra où elle s'est arrêtée.")
        except Exception as error:  # noqa: BLE001 — message clair plutôt qu'une trace Python
            raise SystemExit(f"\nLe téléchargement a échoué ({type(error).__name__}). Vérifiez l'accès à huggingface.co, "
                             "puis relancez l'installation : elle reprendra où elle s'est arrêtée.")
    elif args.selftest is not None:
        selftest(args.selftest or None)
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
