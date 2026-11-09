; Instalador do Vision (Inno Setup 6). Gere com compilar-instalador.bat, que passa a versao.
; Instala na pasta do usuario, sem pedir administrador.

#ifndef Versao
  #define Versao "0.0"
#endif

[Setup]
AppId={{51CE840C-0FD4-4D96-88E1-14292E8585FA}
AppName=Vision
AppVersion={#Versao}
AppVerName=Vision {#Versao}
AppPublisher=Samuel Evaristo
AppPublisherURL=https://github.com/beterraba409/EspelhaTela
AppSupportURL=https://github.com/beterraba409/EspelhaTela/issues
DefaultDirName={localappdata}\Programs\Vision
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Vision-Setup-{#Versao}
SetupIconFile=..\icone.ico
UninstallDisplayIcon={app}\Vision.exe
UninstallDisplayName=Vision
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Vision.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\LEIA-ME.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Vision"; Filename: "{app}\Vision.exe"
Name: "{autodesktop}\Vision"; Filename: "{app}\Vision.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Vision.exe"; Description: "{cm:LaunchProgram,Vision}"; Flags: nowait postinstall
