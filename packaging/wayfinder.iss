; Inno Setup 6 script: wraps dist\Wayfinder (from wayfinder.spec) into dist\WayfinderSetup-<version>.exe.
; Browser data in %LOCALAPPDATA%\AtlasBrowser (profiles, passwords, keys) is never touched by setup or uninstall.
#define AppName "Wayfinder"
#define AppExe "Wayfinder.exe"
#define AppVersion GetVersionNumbersString(AddBackslash(SourcePath) + "..\dist\Wayfinder\Wayfinder.exe")

[Setup]
AppId={{6B0F3C55-2E1A-4D8B-9A57-0C9E4F7A1D23}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\atlasbrowser\assets\wayfinder.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=..\dist
OutputBaseFilename=WayfinderSetup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Wayfinder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Drop files left by an older build so stale Qt DLLs never mix with new ones.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Wayfinder.Desktop"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Wayfinder.Desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
