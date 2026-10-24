@echo off
rem Installe une nouvelle version de KeyScan sur Windows, une fois l'application fermée (lancé par updater.py).
rem   install_windows.cmd <numéro du processus KeyScan> <installateur .exe> <KeyScan.exe> <relancer : 1 ou 0>
rem Le compte rendu est écrit dans « installation.log », à côté de l'installateur.
setlocal
set "PID=%~1"
set "SETUP=%~2"
set "APPEXE=%~3"
set "RELAUNCH=%~4"
set "LOG=%~dp2installation.log"
echo == %date% %time% : %SETUP% >> "%LOG%"

rem 1. attendre que KeyScan soit fermé (2 minutes au plus ; « ping » sert de pause d'une seconde).
rem    Chemins complets : un autre « find » (celui de Git, par exemple) peut se trouver avant celui de Windows.
set /a WAITED=0
:wait
"%SystemRoot%\System32\tasklist.exe" /FI "PID eq %PID%" /NH | "%SystemRoot%\System32\find.exe" "%PID%" >nul
if errorlevel 1 goto install
set /a WAITED+=1
if %WAITED% GEQ 120 goto install
"%SystemRoot%\System32\ping.exe" -n 2 127.0.0.1 >nul
goto wait

rem 2. installateur en mode silencieux (aucune fenêtre, aucune question)
:install
"%SETUP%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG="%~dp2setup.log"
if errorlevel 1 (
  echo Echec de l'installation, code %errorlevel% >> "%LOG%"
) else (
  del "%SETUP%"
  echo Nouvelle version installee >> "%LOG%"
)

rem 3. rouvrir KeyScan si on l'a demandé (bouton « Redémarrer »)
if "%RELAUNCH%"=="1" start "" "%APPEXE%"
endlocal
