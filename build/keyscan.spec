# -*- mode: python ; coding: utf-8 -*-
# Configuration PyInstaller de l'application KeyScan (Mac : KeyScan.app ; Windows : dossier KeyScan\KeyScan.exe).
# Lancer depuis la racine du projet :  pyinstaller build/keyscan.spec --noconfirm
#
# Avant la construction : les modèles OCR dans build/models/ocria-nano/ (avec ONNX Runtime) :
#   LITEPARSE_MODEL_DIR=build/models python -m engine.ocr --install
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
MAC = sys.platform == "darwin"
import re  # noqa: E402
VERSION = re.search(r'APP_VERSION = "([^"]+)"', open(os.path.join(ROOT, "desktop.py"), encoding="utf-8").read()).group(1)

models = os.path.join(ROOT, "build", "models", "ocria-nano")
if not os.path.isdir(models):
    raise SystemExit("Modèles OCR absents : lancez d'abord  LITEPARSE_MODEL_DIR=build/models python -m engine.ocr --install")
datas = [
    (os.path.join(ROOT, "templates"), "templates"),
    (os.path.join(ROOT, "static"), "static"),          # polices de l'interface (Atkinson Hyperlegible Next, Literata ; licence OFL)
    (os.path.join(ROOT, "exemples", "scan.pdf"), "exemples"),   # document lu par l'auto-test (--selftest)
    (os.path.join(ROOT, "build", "update"), "update"),     # scripts d'installation des mises à jour (updater.py)
    (models, os.path.join("models", "ocria-nano")),        # modèle OCR OCRia-nano-1 + ONNX Runtime
]
datas += collect_data_files("liteparse")
binaries = collect_dynamic_libs("liteparse")             # LiteParse (Rust) et PDFium
# tous les fichiers Python de engine/ et server/ (liste écrite à partir des dossiers : rien n'est oublié)
hidden = ["app", "updater", "certifi"] + [
    os.path.relpath(os.path.join(folder, name), ROOT)[:-3].replace(os.sep, ".").removesuffix(".__init__")
    for package in ("engine", "server")
    for folder, _, names in os.walk(os.path.join(ROOT, package)) if "__pycache__" not in folder
    for name in names if name.endswith(".py")
]
hidden += collect_submodules("webview")
hidden += collect_submodules("liteparse")                # LiteParse charge ses modules à la demande (parser, types…)
excludes = ["tkinter", "matplotlib", "IPython", "pandas", "tensorflow", "jax", "flax", "torch", "torchvision", "torchaudio",
            "transformers", "scipy", "sklearn", "notebook", "pytest"]

a = Analysis(
    [os.path.join(ROOT, "desktop.py")],
    pathex=[ROOT],
    binaries=binaries,
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
        version=VERSION,
        info_plist={
            "CFBundleName": "KeyScan",
            "CFBundleDisplayName": "KeyScan",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHumanReadableCopyright": "Projet Master 2027 — Centrale Nantes",
        },
    )
