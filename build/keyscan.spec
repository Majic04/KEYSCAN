# -*- mode: python ; coding: utf-8 -*-
# Configuration PyInstaller de l'application KeyScan (Mac : KeyScan.app ; Windows : dossier KeyScan\KeyScan.exe).
# Lancer depuis la racine du projet :  pyinstaller build/keyscan.spec --noconfirm
#
# Avant la construction :
#   build/models/trocr-fr/   modèle manuscrit préparé par build/prepare_model.py
#   build/tesseract/          Tesseract + tessdata (build/mac/bundle_tesseract.sh ou build/windows/get_tesseract.ps1)
# Variable KEYSCAN_NO_HTR=1 : construction sans le module manuscrit (essais rapides).
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
WITH_HTR = os.environ.get("KEYSCAN_NO_HTR") != "1"
MAC = sys.platform == "darwin"
WIN = sys.platform == "win32"

datas = [
    (os.path.join(ROOT, "templates"), "templates"),
    (os.path.join(ROOT, "exemples", "manuscrit.png"), "exemples"),
]
tess = os.path.join(ROOT, "build", "tesseract")
if os.path.isdir(tess):
    datas.append((tess, "tesseract"))
hidden = ["app", "engine", "engine.extract", "engine.matcher", "engine.handwriting"]
hidden += collect_submodules("webview")
excludes = ["tkinter", "matplotlib", "IPython", "pandas", "tensorflow", "jax", "flax", "torchvision", "torchaudio",
            "scipy", "sklearn", "notebook", "pytest"]

if WITH_HTR:
    model = os.path.join(ROOT, "build", "models", "trocr-fr")
    if not os.path.isdir(model):
        raise SystemExit("Modèle manuscrit absent : lancez d'abord build/prepare_model.py")
    datas.append((model, os.path.join("models", "trocr-fr")))
    keep = ("trocr", "vision_encoder_decoder", "vit", "roberta", "auto", "deit", "beit", "xlm_roberta")

    def wanted(name):
        if "modeling_tf" in name or "modeling_flax" in name or ".tf_" in name or "_tf_" in name:
            return False
        if name.startswith("transformers.models."):
            return name.split(".")[2] in keep
        return True

    hidden += collect_submodules("transformers", filter=wanted)
    datas += collect_data_files("transformers", include_py_files=False)
    for pkg in ("transformers", "tokenizers", "huggingface-hub", "safetensors", "regex", "requests", "tqdm",
                "numpy", "packaging", "filelock", "pyyaml", "torch"):
        datas += copy_metadata(pkg)
else:
    excludes += ["torch", "transformers", "tokenizers", "safetensors", "huggingface_hub"]

a = Analysis(
    [os.path.join(ROOT, "desktop.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
icon = os.path.join(ROOT, "build", "icons", "keyscan.icns" if MAC else "keyscan.ico")
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="KeyScan",
    console=False,               # application graphique : pas de fenêtre de terminal
    icon=icon,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="KeyScan", upx=False)

if MAC:
    app = BUNDLE(
        coll,
        name="KeyScan.app",
        icon=icon,
        bundle_identifier="fr.keyscan.app",
        version="1.0.0",
        info_plist={
            "CFBundleName": "KeyScan",
            "CFBundleDisplayName": "KeyScan",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHumanReadableCopyright": "Projet Master 2027 — Centrale Nantes",
        },
    )
