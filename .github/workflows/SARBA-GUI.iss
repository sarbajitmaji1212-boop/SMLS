#define AppName "SARBA GUI"
#define AppVersion "1.0.0"
#define AppPublisher "SARBA"
#define AppExeName "SARBA-GUI.exe"

[Setup]
AppId={{D5EC881D-45FB-4DA9-A2C0-BA4A0EFC2A42}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\SARBA GUI
DefaultGroupName=SARBA GUI
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=SARBA-GUI-Setup
SetupIconFile=..\assets\SG.ico
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\SARBA-GUI.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SARBA GUI"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{autodesktop}\SARBA GUI"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch SARBA GUI"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\vendor"
