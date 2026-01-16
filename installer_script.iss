
[Setup]
AppName=Petrovich Parser Pro
AppVersion=1.0.0
DefaultDirName={autopf}\PetrovichParser
DefaultGroupName=Petrovich Parser
UninstallDisplayIcon={app}\PetrovichParser.exe
Compression=lzma2
SolidCompression=yes
OutputDir=.
OutputBaseFilename=PetrovichParser_Setup
SetupIconFile=app_icon.ico
PrivilegesRequired=admin

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\PetrovichParser.exe"; DestDir: "{app}"; Flags: ignoreversion
; NOTE: We don't need to include Cook or categories_config.txt here 
; because they are bundled inside the EXE and the app will copy them 
; to the local folder on first run.

[Icons]
Name: "{group}\Petrovich Parser Pro"; Filename: "{app}\PetrovichParser.exe"
Name: "{autodesktop}\Petrovich Parser Pro"; Filename: "{app}\PetrovichParser.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PetrovichParser.exe"; Description: "{cm:LaunchProgram,Petrovich Parser Pro}"; Flags: nowait postinstall skipifsilent
