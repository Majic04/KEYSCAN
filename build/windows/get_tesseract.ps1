# Prépare Tesseract autonome pour l'application Windows : build\tesseract\ (tesseract.exe + DLL + langues fra/eng/osd).
# Source : installeur officiel UB-Mannheim (Université de Mannheim), installé en silence dans un dossier temporaire.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Out = Join-Path $Root "build\tesseract"
$Tmp = Join-Path $env:RUNNER_TEMP "tess-install"
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Force -Path $Out, $Tmp | Out-Null

$Url = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
$Setup = Join-Path $Tmp "tesseract-setup.exe"
Invoke-WebRequest -Uri $Url -OutFile $Setup
$Dest = Join-Path $Tmp "Tesseract-OCR"
Start-Process -FilePath $Setup -ArgumentList "/S", "/D=$Dest" -Wait

# binaire + DLL (sans les outils d'entraînement ni la documentation)
Get-ChildItem $Dest -File | Where-Object { $_.Extension -in ".exe", ".dll" -and $_.Name -notmatch "^(unins|text2image|lstmtraining|combine_tessdata|cntraining|mftraining|shapeclustering|wordlist2dawg|ambiguous_words|classifier_tester|dawg2wordlist|set_unicharset_properties|unicharset_extractor|merge_unicharsets|lstmeval|combine_lang_model|cntraining)" } |
  Copy-Item -Destination $Out
New-Item -ItemType Directory -Force -Path (Join-Path $Out "tessdata") | Out-Null
foreach ($L in "fra", "eng", "osd") {
  Invoke-WebRequest -Uri "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/$L.traineddata" -OutFile (Join-Path $Out "tessdata\$L.traineddata")
}
$env:TESSDATA_PREFIX = Join-Path $Out "tessdata"
& (Join-Path $Out "tesseract.exe") --list-langs
if ($LASTEXITCODE -ne 0) { throw "Tesseract autonome ne démarre pas" }
"{0:N0} Mo" -f ((Get-ChildItem $Out -Recurse | Measure-Object Length -Sum).Sum / 1MB)
