@echo off
setlocal
cd /d "%~dp0"
title KeyScan - ecriture manuscrite
echo KeyScan - installation du module d'ecriture manuscrite
echo ========================================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo Lancez d'abord "lancer_windows.bat" une fois, puis relancez ce fichier.
  pause
  exit /b 1
)
echo Quel modele installer ?
echo   1^) Francais (recommande^) : TrOCR affine sur l'ecriture manuscrite francaise, environ 2,3 Go
echo   2^) Anglais, plus leger et plus rapide : TrOCR base, environ 1,3 Go
set "MODELE=fr"
set /p CHOIX="Votre choix [1] : "
if "%CHOIX%"=="2" set "MODELE=en"
echo.
echo 1/3  Installation de PyTorch et Transformers (quelques minutes)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-manuscrit.txt
if errorlevel 1 goto :err
echo.
echo 2/3  Telechargement du modele (une seule fois)...
".venv\Scripts\python.exe" -m engine.handwriting --install %MODELE%
if errorlevel 1 goto :err
echo.
echo 3/3  Test de lecture sur exemples\manuscrit.png...
".venv\Scripts\python.exe" -m engine.handwriting --selftest
echo.
echo Termine. Fermez KeyScan s'il est ouvert, puis relancez "lancer_windows.bat".
pause
exit /b 0
:err
echo.
echo [ERREUR] L'installation a echoue. Verifiez la connexion Internet puis relancez ce fichier.
pause
exit /b 1
