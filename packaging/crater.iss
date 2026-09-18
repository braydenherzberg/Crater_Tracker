; Inno Setup script for the Windows installer. Built by CI:
;   iscc /DAppVersion=0.5.0 packaging\crater.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E3C9E57-2B7C-4E0B-9C8E-5A1C3B7F2D41}
AppName=Crater
AppVersion={#AppVersion}
AppPublisher=Crater contributors
DefaultDirName={localappdata}\Programs\Crater
DefaultGroupName=Crater
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Crater-Windows-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\Crater.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\Crater\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Crater"; Filename: "{app}\Crater.exe"
Name: "{autodesktop}\Crater"; Filename: "{app}\Crater.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\Crater.exe"; Description: "Launch Crater"; Flags: nowait postinstall skipifsilent
