; Installateur Windows de KeyScan (Inno Setup 6).
; Installation pour l'utilisateur courant : aucun droit administrateur nécessaire.
; version transmise par la construction (/DAppVersion=…), sinon :
#ifndef AppVersion
  #define AppVersion "1.4.0"
#endif

[Setup]
AppId={{5D88BE08-9A07-4B66-842C-2D28DD7D561C}
AppName=KeyScan
AppVersion={#AppVersion}
AppVerName=KeyScan {#AppVersion}
AppPublisher=Projet Master 2027 - Centrale Nantes
DefaultDirName={localappdata}\Programs\KeyScan
DefaultGroupName=KeyScan
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=KeyScan-Windows-Setup
SetupIconFile=..\icons\keyscan.ico
UninstallDisplayIcon={app}\KeyScan.exe
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "..\..\dist\KeyScan\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\KeyScan"; Filename: "{app}\KeyScan.exe"
Name: "{autodesktop}\KeyScan"; Filename: "{app}\KeyScan.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\KeyScan.exe"; Description: "Lancer KeyScan"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; les données de l'utilisateur (%APPDATA%\KeyScan) sont conservées volontairement
Type: filesandordirs; Name: "{app}"
