@echo off
setlocal
cd /d "%~dp0"
title KeyScan

rem --- 1. trouver Python (lanceur "py" en priorite, sinon "python")
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo [ERREUR] Python est introuvable.
  echo Installez-le depuis https://www.python.org/downloads/
  echo en cochant "Add Python to PATH", puis relancez ce fichier.
  pause
  exit /b 1
)

rem --- 2. creer l'environnement local si besoin
if not exist ".venv\Scripts\python.exe" (
  echo Creation de l'environnement Python local...
  if exist ".venv" rmdir /s /q ".venv"
  %PY% -m venv .venv
  if errorlevel 1 goto :venv_error
)

rem --- 3. installer / verifier les bibliotheques (rapide si deja installees)
echo Verification des bibliotheques...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo L'environnement semble abime : reconstruction...
  rmdir /s /q ".venv"
  %PY% -m venv .venv
  if errorlevel 1 goto :venv_error
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :pip_error
)

rem --- 4. lancer KeyScan
".venv\Scripts\python.exe" app.py %*
pause
exit /b 0

:venv_error
echo.
echo [ERREUR] Impossible de creer l'environnement Python (.venv).
echo Verifiez que Python 3.10 ou plus recent est installe.
pause
exit /b 1

:pip_error
echo.
echo [ERREUR] L'installation des bibliotheques a echoue.
echo Verifiez votre connexion Internet, puis relancez ce fichier.
pause
exit /b 1
