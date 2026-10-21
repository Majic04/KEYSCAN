"""
Écriture manuscrite (module optionnel) : détection des zones manuscrites + lecture par TrOCR.

Pourquoi : Tesseract est conçu pour le texte imprimé ; sur une lettre ou une annotation écrite
à la main, il lit peu ou mal, et un mot-clé manuscrit passe inaperçu.

Fonctionnement, pour chaque page lue par OCR :
  1. Segmentation : la page est découpée en lignes (profil horizontal de l'encre),
     puis chaque ligne en morceaux (colonnes, et morceaux de ~12 mots au plus).
  2. Détection : un morceau est considéré comme MANUSCRIT si Tesseract n'y a pas reconnu
     de mots imprimés avec confiance (moins de 60 % de sa largeur couverte par des mots
     lus à ≥ 75 %). Les lignes imprimées bien lues ne sont pas relues.
  3. Lecture : chaque morceau manuscrit est lu par un modèle TrOCR (transformer image→texte,
     entraîné sur l'écriture manuscrite). La confiance d'une ligne est la probabilité moyenne
     des caractères générés (exp de la log-probabilité moyenne par jeton).

Modèles (téléchargés une seule fois dans KeyScan/models, puis utilisés hors ligne) :
  - "fr" : agomberto/trocr-large-handwritten-fr — TrOCR large affiné sur de l'écriture
           manuscrite française (licence MIT). Le plus adapté aux documents en français.
  - "en" : microsoft/trocr-base-handwritten — TrOCR base (anglais, IAM), plus léger et rapide.
  Un chemin vers un dossier local de modèle est aussi accepté (tests).

Installation (mode Python ; l'application installée l'inclut déjà) :
      python -m engine.handwriting --install fr
Auto-test :  python -m engine.handwriting --selftest
"""
from __future__ import annotations

import json
import os
import threading
import time

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# l'application de bureau fournit un dossier inscriptible (le code embarqué, lui, est en lecture seule)
MODELS_DIR = os.environ.get("KEYSCAN_MODELS") or os.path.join(ROOT, "models")
CONFIG = os.path.join(os.path.dirname(MODELS_DIR), "manuscrit.json") if os.environ.get("KEYSCAN_MODELS") else os.path.join(ROOT, "manuscrit.json")
# les modèles restent dans le dossier KeyScan (supprimer KeyScan supprime tout)
os.environ.setdefault("HF_HOME", MODELS_DIR)
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

MODELS = {
    "fr": {"model": "agomberto/trocr-large-handwritten-fr", "processor": "microsoft/trocr-large-handwritten",
           "label": "TrOCR français (manuscrit)", "size": "≈ 2,3 Go"},
    "en": {"model": "microsoft/trocr-base-handwritten", "processor": "microsoft/trocr-base-handwritten",
           "label": "TrOCR anglais (manuscrit, léger)", "size": "≈ 1,3 Go"},
}

PRINTED_CONF = 75        # un mot Tesseract lu au moins à ce niveau est considéré comme imprimé et bien lu
PRINTED_COVER = 0.6      # une ligne couverte à 60 % par de tels mots n'est pas relue
MAX_CHUNKS = 60          # garde-fou : au plus 60 morceaux manuscrits par page
MAX_ASPECT = 14          # TrOCR lit mieux des morceaux pas trop allongés (≈ 10-12 mots)
BATCH = 6

_lock = threading.Lock()
_engine = None           # (processor, model, tokenizer, device) une fois chargé
_load_error = None


# =========================================================================== configuration / état
def model_key() -> str:
    key = os.environ.get("KWF_HTR_MODEL")
    if not key and os.path.exists(CONFIG):
        try:
            key = json.load(open(CONFIG, encoding="utf-8")).get("model")
        except (OSError, ValueError):
            key = None
    return key or "fr"


def _spec(key: str | None = None) -> dict:
    key = key or model_key()
    if key in MODELS:
        return {"key": key, **MODELS[key]}
    return {"key": key, "model": key, "processor": key, "label": f"modèle local ({os.path.basename(key)})", "size": ""}


def libraries_ok() -> bool:
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers"))


def _cached(repo: str) -> bool:
    if os.path.isdir(repo):
        return True
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def status() -> dict:
    """État du module, affiché dans les Réglages."""
    spec = _spec()
    st = {"model": spec["key"], "label": spec["label"], "libraries": libraries_ok(), "ready": False, "error": _load_error}
    if st["libraries"]:
        st["ready"] = _cached(spec["model"]) and _cached(spec["processor"])
    return st


def available() -> bool:
    return status()["ready"]


# =========================================================================== chargement du modèle
def _load():
    global _engine, _load_error
    with _lock:
        if _engine is not None:
            return _engine
        import torch
        from transformers import AutoTokenizer, TrOCRProcessor, VisionEncoderDecoderModel
        from transformers.utils import logging as hf_logging
        hf_logging.set_verbosity_error()      # pas de messages techniques dans la fenêtre de KeyScan
        spec = _spec()
        local = {"local_files_only": True}
        processor = TrOCRProcessor.from_pretrained(spec["processor"], **local)
        # le modèle embarqué est stocké en demi-précision (2 fois plus léger) ; il est remis en pleine précision au chargement
        model = VisionEncoderDecoderModel.from_pretrained(spec["model"], torch_dtype=torch.float32, **local)
        tokenizer = AutoTokenizer.from_pretrained(spec["model"], **local)
        device = _pick_device(torch)
        model.to(device).eval()
        if model.config.decoder_start_token_id is None:
            model.config.decoder_start_token_id = tokenizer.cls_token_id or tokenizer.bos_token_id
        if model.config.pad_token_id is None:
            model.config.pad_token_id = tokenizer.pad_token_id
        _engine = (processor, model, tokenizer, device)
        _load_error = None
        return _engine


def _pick_device(torch) -> str:
    """Processeur graphique si disponible et fonctionnel (Apple Silicon : « mps »), sinon processeur classique."""
    forced = os.environ.get("KEYSCAN_HTR_DEVICE")
    if forced:
        return forced
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        try:   # certaines machines (virtuelles notamment) annoncent « mps » mais ne peuvent rien y allouer
            (torch.ones(256, 256, device="mps") * 2).sum().item()
            return "mps"
        except Exception:  # noqa: BLE001
            pass
    return "cpu"


def _fallback_cpu():
    """Bascule le modèle sur le processeur classique après un échec du processeur graphique."""
    global _engine
    with _lock:
        processor, model, tokenizer, device = _engine
        if device != "cpu":
            print(f"[manuscrit] {device} indisponible : lecture sur le processeur", flush=True)
            model.to("cpu")
            _engine = (processor, model, tokenizer, "cpu")
        return _engine


def recognize(images: list[Image.Image]) -> list[tuple[str, float]]:
    """Lit des images de lignes manuscrites. Retourne [(texte, confiance 0-100)]."""
    try:
        return _recognize(images)
    except RuntimeError:
        if _engine is None or _engine[3] == "cpu":
            raise
        _fallback_cpu()
        return _recognize(images)


def _recognize(images: list[Image.Image]) -> list[tuple[str, float]]:
    """Lit des images de lignes manuscrites. Retourne [(texte, confiance 0-100)]."""
    if not images:
        return []
    import torch
    processor, model, tokenizer, device = _load()
    out: list[tuple[str, float]] = []
    for i in range(0, len(images), BATCH):
        batch = [im.convert("RGB") for im in images[i:i + BATCH]]
        pixel_values = processor(images=batch, return_tensors="pt").pixel_values.to(device)
        with _lock, torch.no_grad():   # un seul passage à la fois sur le modèle (plusieurs analyses en parallèle)
            gen = model.generate(pixel_values, max_new_tokens=64, num_beams=1,
                                 output_scores=True, return_dict_in_generate=True)
            scores = model.compute_transition_scores(gen.sequences, gen.scores, normalize_logits=True)
        texts = tokenizer.batch_decode(gen.sequences, skip_special_tokens=True)
        pad, eos = model.config.pad_token_id, model.config.eos_token_id
        for b, text in enumerate(texts):
            ids = gen.sequences[b, 1:]
            keep = [j for j in range(scores.shape[1]) if j < len(ids) and int(ids[j]) not in (pad,)]
            lp = scores[b, keep].float() if keep else torch.tensor([-5.0])
            lp = lp[torch.isfinite(lp)]
            conf = float(torch.exp(lp.mean()).item()) * 100 if len(lp) else 0.0
            out.append((text.strip(), round(conf, 1)))
    return out


# =========================================================================== segmentation en lignes
def _box_sum(a: np.ndarray, r: int) -> np.ndarray:
    """Somme sur une fenêtre carrée (2r+1)² autour de chaque pixel (image intégrale : rapide, numpy seul)."""
    c = np.pad(a.astype(np.int32), ((r + 1, r), (r + 1, r))).cumsum(0).cumsum(1)
    k = 2 * r + 1
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def _hrun_mask(ink: np.ndarray, L: int) -> np.ndarray:
    """Pixels appartenant à un trait horizontal continu d'au moins L pixels (bord de carte, filet, soulignement)."""
    H, W = ink.shape
    if W <= L:
        return np.zeros_like(ink)
    c = np.pad(ink.astype(np.int32), ((0, 0), (1, 0))).cumsum(1)
    full = (c[:, L:] - c[:, :-L]) >= int(0.92 * L)           # full[:, x] : fenêtre [x, x+L) presque entièrement encrée
    F = np.pad(full.astype(np.int32), ((0, 0), (1, 0))).cumsum(1)
    x = np.arange(W)
    hi = np.minimum(x, W - L) + 1
    lo = np.maximum(0, x - L + 1)
    return (F[:, hi] - F[:, lo]) > 0                          # pixel couvert par au moins une telle fenêtre


def _ink(gray: Image.Image) -> np.ndarray:
    """
    Masque de l'encre : seuillage local (robuste aux ombres, au papier jauni, aux taches), puis nettoyage :
    grain du papier et pointillés (points isolés), bords de carte et filets (longs traits horizontaux).
    """
    g = gray.filter(ImageFilter.MedianFilter(3))
    a = np.asarray(g, dtype=np.int16)
    local = np.asarray(g.filter(ImageFilter.BoxBlur(25)), dtype=np.int16)
    ink = a < (local - 12)
    r = max(3, gray.size[0] // 600)                  # un trait d'écriture remplit bien sa petite fenêtre, pas un grain
    ink &= _box_sum(ink, r) >= 0.2 * (2 * r + 1) ** 2
    ink &= ~_hrun_mask(ink, max(40, gray.size[0] // 6))
    return ink


def _line_spacing(prof: np.ndarray) -> float:
    """Interligne (pixels) : premier pic de l'autocorrélation du profil d'encre."""
    p = prof - prof.mean()
    n = len(p)
    ac = np.correlate(p, p, mode="full")[n - 1:]
    if ac[0] <= 0:
        return 0.0
    lo, hi = max(8, n // 150), max(9, n // 4)
    seg = ac[lo:hi]
    peaks = [i for i in range(1, len(seg) - 1) if seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1] and seg[i] > 0.1 * ac[0]]
    if not peaks:
        return 0.0
    # le pic le plus fort (et non le premier : les jambages et les hampes créent un faux pic à mi-interligne)
    best = max(peaks, key=lambda i: seg[i])
    return float(lo + best)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Intervalles [début, fin) où mask est vrai."""
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def _line_bands(rows: np.ndarray) -> list[tuple[int, int]]:
    """
    Bandes horizontales des lignes de texte. Chaque ligne est un pic du profil d'encre ; la frontière entre
    deux lignes est le creux entre leurs pics. Fonctionne aussi quand les jambages d'une ligne manuscrite
    touchent la suivante (pas d'interligne blanc).
    """
    H = len(rows)
    sp = _line_spacing(rows)
    if sp < 8:                                    # pas de régularité : découpe classique aux interlignes blancs
        thr = max(2.0, 0.06 * float(np.percentile(rows[rows > 0], 90)))
        return [(a, b) for a, b in _runs(rows > thr) if b - a >= 6]
    k = max(3, int(sp / 3))
    sm = np.convolve(rows, np.ones(k) / k, mode="same")
    floor = 0.12 * float(sm.max())
    cand = [i for i in range(1, H - 1) if sm[i] >= sm[i - 1] and sm[i] > sm[i + 1] and sm[i] > floor]
    peaks = []
    for i in sorted(cand, key=lambda i: -sm[i]):          # les plus forts d'abord, espacés d'au moins 0,6 interligne
        if all(abs(i - j) >= 0.6 * sp for j in peaks):
            peaks.append(i)
    peaks.sort()
    bands = []
    for n, pk in enumerate(peaks):
        top = peaks[n - 1] + int(np.argmin(sm[peaks[n - 1]:pk])) if n else max(0, int(pk - 0.6 * sp))
        bot = pk + int(np.argmin(sm[pk:peaks[n + 1]])) if n + 1 < len(peaks) else min(H, int(pk + 0.6 * sp))
        # resserre la bande sur l'encre réelle (lignes isolées : pas de grande marge vide)
        ys = np.where(rows[top:bot] > 0.05 * sm[pk])[0]
        if len(ys):
            top, bot = top + int(ys[0]), top + int(ys[-1]) + 1
        if bot - top >= 6:
            bands.append((top, bot))
    return bands


def segment_lines(gray: Image.Image) -> list[tuple[int, int, int, int]]:
    """Découpe une page en morceaux de lignes de texte : [(x0, y0, x1, y1)] en pixels."""
    ink = _ink(gray)
    H, W = ink.shape
    rows = ink.sum(axis=1).astype(np.float32)
    if not (rows > 0).any():
        return []
    merged = _line_bands(rows)
    boxes = []
    for y0, y1 in merged:
        h = y1 - y0
        if h < 8 or h > 0.5 * H:
            continue
        cols = ink[y0:y1].sum(axis=0) >= 2
        segs = [(a, b) for a, b in _runs(cols) if b - a >= 2]
        if not segs:
            continue
        # regroupe les traits en morceaux ; un grand vide (> 1,8 h) sépare deux colonnes
        chunks = [[segs[0][0], segs[0][1], []]]
        for a, b in segs[1:]:
            gap = a - chunks[-1][1]
            if gap > 1.8 * h:
                chunks.append([a, b, []])
            else:
                if gap > 0.35 * h:
                    chunks[-1][2].append((chunks[-1][1], a))   # espace entre deux mots
                chunks[-1][1] = b
        for x0, x1, gaps in chunks:
            # morceaux trop allongés : coupés aux espaces entre mots
            pieces, start = [], x0
            for g0, g1 in gaps:
                if (g0 - start) > MAX_ASPECT * h:
                    pieces.append((start, g0)); start = g1
            pieces.append((start, x1))
            for a, b in pieces:
                if (b - a) < 1.0 * h or ink[y0:y1, a:b].sum() < 0.02 * h * (b - a):   # trop court ou presque vide
                    continue
                py, px = int(0.08 * h), int(0.25 * h)
                boxes.append((max(0, a - px), max(0, y0 - py), min(W, b + px), min(H, y1 + py)))
    return boxes


# =========================================================================== détection des zones manuscrites
def handwritten_regions(gray: Image.Image, ocr_words: list[tuple[list[float], float, str]]) -> list[tuple[int, int, int, int]]:
    """
    Morceaux de lignes que Tesseract n'a pas lus comme du texte imprimé fiable → candidats manuscrits.
    ocr_words : [(boîte en pixels [x0,y0,x1,y1], confiance, texte)] de la lecture Tesseract.
    """
    # mots imprimés bien lus (un caractère isolé compte s'il est lu avec une très bonne confiance : « 2 », « A »)
    good = [b for b, c, t in ocr_words if c >= PRINTED_CONF and (len(t.strip()) >= 2 or c >= 90)]
    out = []
    for box in segment_lines(gray):
        x0, y0, x1, y1 = box
        h = y1 - y0
        covered = np.zeros(x1 - x0, dtype=bool)
        for bx0, by0, bx1, by1 in good:
            iy = min(y1, by1) - max(y0, by0)
            if iy <= 0.4 * min(h, by1 - by0):
                continue
            a, b = int(max(x0, bx0)) - x0, int(min(x1, bx1)) - x0
            if b > a:
                covered[a:b] = True
        if covered.mean() < PRINTED_COVER:
            out.append(box)
        if len(out) >= MAX_CHUNKS:
            break
    return out


def read_handwriting(gray: Image.Image, ocr_words) -> list[dict]:
    """Détecte puis lit l'écriture manuscrite d'une page : [{"box": [x0,y0,x1,y1], "text", "conf"}]."""
    regions = handwritten_regions(gray, ocr_words)
    if not regions:
        return []
    crops = [gray.crop(b) for b in regions]
    results = recognize(crops)
    return [{"box": list(b), "text": t, "conf": c} for b, (t, c) in zip(regions, results) if t]


# =========================================================================== installation / auto-test (ligne de commande)
def _install(key: str):
    """
    Télécharge uniquement ce qui sert à la lecture : configuration, vocabulaire et poids du modèle.
    (Le dépôt du modèle français contient aussi des fichiers d'entraînement de plusieurs Go, ignorés ici.)
    """
    from huggingface_hub import HfApi, snapshot_download
    spec = _spec(key)
    print(f"Téléchargement du modèle « {spec['label']} » ({spec['size']}) dans {MODELS_DIR}")
    print("C'est fait une seule fois ; ensuite KeyScan fonctionne hors ligne.\n")
    small = ["*.json", "merges.txt", "vocab.*", "*.model"]          # configuration + vocabulaire (quelques Mo)
    files = HfApi().list_repo_files(spec["model"])
    weights = [f for f in files if f.endswith(".safetensors")] or [f for f in files if f == "pytorch_model.bin"]
    if not weights:
        raise SystemExit(f"Aucun fichier de poids trouvé dans {spec['model']}")
    snapshot_download(spec["model"], allow_patterns=small + weights)
    if spec["processor"] != spec["model"]:
        snapshot_download(spec["processor"], allow_patterns=small)   # préparation des images + jetons, sans poids
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump({"model": key}, f)
    print("\nModèle installé.")


def _selftest(path: str | None):
    path = path or os.path.join(ROOT, "exemples", "manuscrit.png")
    st = status()
    print(f"Module manuscrit : {st['label']} — prêt : {'oui' if st['ready'] else 'non'}")
    if not st["ready"]:
        raise SystemExit("Modèle absent : lancez d'abord l'installation.")
    gray = Image.open(path).convert("L")
    t = time.time()
    regions = segment_lines(gray)
    print(f"{len(regions)} ligne(s) détectée(s) dans {os.path.basename(path)}")
    res = recognize([gray.crop(b) for b in regions])
    for (text, conf) in res:
        print(f"  [{conf:5.1f} %] {text}")
    print(f"Lecture en {time.time() - t:.1f} s")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Module d'écriture manuscrite de KeyScan")
    ap.add_argument("--install", choices=sorted(MODELS), help="télécharge le modèle (fr ou en)")
    ap.add_argument("--selftest", nargs="?", const="", help="lit une image de test (par défaut exemples/manuscrit.png)")
    a = ap.parse_args()
    if a.install:
        try:
            _install(a.install)
        except KeyboardInterrupt:
            raise SystemExit("\nTéléchargement interrompu : relancez l'installation pour reprendre là où il s'est arrêté.")
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001 — message clair plutôt qu'une trace Python
            print(f"\nLe téléchargement du modèle a échoué : {type(e).__name__}")
            print("Vérifiez la connexion Internet (accès à huggingface.co), puis relancez l'installation :")
            print("elle reprendra là où elle s'est arrêtée.")
            raise SystemExit(1)
    if a.selftest is not None:
        _selftest(a.selftest or None)
    if not a.install and a.selftest is None:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
