; Inno Setup 6 script: wraps dist\Pelagic (from pelagic.spec) into dist\PelagicSetup-<version>.exe.
; Browser data in %LOCALAPPDATA%\AtlasBrowser (profiles, passwords, keys) is never touched by setup or uninstall.
#define AppName "Pelagic"
#define AppExe "Pelagic.exe"
#define AppVersion GetVersionNumbersString(AddBackslash(SourcePath) + "..\dist\Pelagic\Pelagic.exe")

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
SetupIconFile=..\atlasbrowser\assets\pelagic.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=..\dist
; ISCC /DUpdater builds PelagicUpdate-<version>.exe: same payload, no wizard pages, keeps the
; existing folder and shortcut choices, closes Pelagic and reopens it when done.
; ISCC /DDemoKeyFile=<path> builds PelagicSetup-Demo-<version>.exe, which also sets ANTHROPIC_API_KEY for the
; Windows account (only if it isn't set already; removed on uninstall). The key is read from that file at
; compile time and never stored in this repo. Anyone with the demo installer can extract the key.
#ifdef DemoKeyFile
  #define DemoKeyHandle FileOpen(DemoKeyFile)
  #define DemoKey Trim(FileRead(DemoKeyHandle))
  #expr FileClose(DemoKeyHandle)
OutputBaseFilename=PelagicSetup-Demo-{#AppVersion}
ChangesEnvironment=yes
#elif defined(Updater)
OutputBaseFilename=PelagicUpdate-{#AppVersion}
CloseApplications=force
#else
OutputBaseFilename=PelagicSetup-{#AppVersion}
#endif
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
#ifndef Updater
CloseApplications=yes
#endif
RestartApplications=no
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Pelagic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Drop files left by an older build so stale Qt DLLs never mix with new ones.
Type: filesandordirs; Name: "{app}\_internal"
; The app used to be called Wayfinder (same AppId, so this upgrades it): remove its exe and shortcuts.
Type: files; Name: "{app}\Wayfinder.exe"
Type: files; Name: "{autoprograms}\Wayfinder.lnk"
Type: files; Name: "{autodesktop}\Wayfinder.lnk"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Pelagic.Desktop"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Pelagic.Desktop"; Tasks: desktopicon

[Registry]
; Register as a web browser so Pelagic appears in Settings > Default apps (the user still picks it there).
#define Caps "Software\Clients\StartMenuInternet\Pelagic\Capabilities"
Root: HKA; Subkey: "Software\Classes\PelagicHTML"; ValueType: string; ValueData: "Pelagic HTML Document"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\PelagicHTML"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\PelagicHTML\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\PelagicHTML\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\Pelagic"; ValueType: string; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\Pelagic\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\Pelagic\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"""
Root: HKA; Subkey: "{#Caps}"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKA; Subkey: "{#Caps}"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Pelagic web browser"
Root: HKA; Subkey: "{#Caps}"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "{#Caps}\StartMenu"; ValueType: string; ValueName: "StartMenuInternet"; ValueData: "Pelagic"
Root: HKA; Subkey: "{#Caps}\URLAssociations"; ValueType: string; ValueName: "http"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "{#Caps}\URLAssociations"; ValueType: string; ValueName: "https"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "{#Caps}\FileAssociations"; ValueType: string; ValueName: ".htm"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "{#Caps}\FileAssociations"; ValueType: string; ValueName: ".html"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "{#Caps}\FileAssociations"; ValueType: string; ValueName: ".xhtml"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "{#Caps}\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "{#Caps}\FileAssociations"; ValueType: string; ValueName: ".svg"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "{#Caps}\FileAssociations"; ValueType: string; ValueName: ".md"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "{#Caps}\FileAssociations"; ValueType: string; ValueName: ".markdown"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "{#Caps}\FileAssociations"; ValueType: string; ValueName: ".txt"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "{#Caps}\FileAssociations"; ValueType: string; ValueName: ".log"; ValueData: "PelagicHTML"
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "Pelagic"; ValueData: "{#Caps}"; Flags: uninsdeletevalue
; "Open with Pelagic" for documents and text files (fileview.py renders .md/.txt/.log).
#define OpenWith(Ext) 'Root: HKA; Subkey: "Software\Classes\' + Ext + '\OpenWithProgids"; ValueType: string; ValueName: "PelagicHTML"; ValueData: ""; Flags: uninsdeletevalue'
#emit OpenWith(".htm")
#emit OpenWith(".html")
#emit OpenWith(".pdf")
#emit OpenWith(".md")
#emit OpenWith(".markdown")
#emit OpenWith(".txt")
#emit OpenWith(".log")

#ifdef DemoKeyFile
Root: HKCU; Subkey: "Environment"; ValueType: string; ValueName: "ANTHROPIC_API_KEY"; ValueData: "{#DemoKey}"; Flags: uninsdeletevalue; Check: NoAnthropicKeyYet
#endif

[Run]
#ifdef Updater
Filename: "{app}\{#AppExe}"; Flags: nowait skipifsilent
#else
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
#endif

#ifdef Updater
[Code]
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := True;
end;
#endif

#ifdef DemoKeyFile
[Code]
// Leave a key the user already set alone (a previous demo install counts as set, so upgrades keep it).
function NoAnthropicKeyYet(): Boolean;
begin
  Result := GetEnv('ANTHROPIC_API_KEY') = '';
end;

function SetEnvironmentVariable(lpName, lpValue: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

// The registry value only reaches processes started after Windows refreshes the environment, so the
// "Launch Pelagic" checkbox would start it without the key. Give setup's own environment the key so it inherits it.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and NoAnthropicKeyYet() then
    SetEnvironmentVariable('ANTHROPIC_API_KEY', '{#DemoKey}');
end;
#endif
