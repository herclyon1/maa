; Ark Relay installer (Inno Setup 6). Built by packaging/build.py, which stages the files
; and passes /DStage=<stage folder> /DAppVersion=<manifest version>.
; Modelled on AUTO-MAS's own installer (res/packaging/AUTO-MAS.iss in its repo:
; PrivilegesRequired=admin, {autopf}, whole folder copied, {app} removed on uninstall).
;
; Everything the relay needs on the machine is set up here, so the machine's state can
; be read from this file:
;   {app}\runtime\python      embedded Python 3.14 + Pillow + pywin32
;   {app}\versions\<n>        relay code; updates add folders, current.txt picks one
;   {app}\watchdog            ArkRelayWatchdog service (auto start, restart on failure)
;   task \ArkRelay\main       starts the relay at logon (highest privileges, no time limit)
;   C:\ProgramData\ark-relay  data (.env, state, logs): created here, kept on uninstall
;                             unless the user says otherwise
;   the old relay             stopped and disabled at install (packaging/legacy.py
;                             takeover), deleted at uninstall (legacy.py remove,
;                             the list is relay/handover/legacy-items.json)
;   AUTO-MAS settings         the jobs it already does handed to it at install,
;                             put back at uninstall (relay/handover/automas_handover.py)
; The order of all of that is in packaging/switch.py; this file only copies files and
; calls it. Setup parameter /SKIPHANDOVER=1 skips the AUTO-MAS step (cloud test machine).

#ifndef Stage
  #define Stage "stage"
#endif
#ifndef AppVersion
  #define AppVersion "0"
#endif
#define AppName "Ark Relay"
#define Py "{app}\runtime\python\python.exe"
#define PyW "{app}\runtime\python\pythonw.exe"

[Setup]
AppId={{6F1E2B7A-3C54-4D8B-9E21-7A0C5D3F8B11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=herclyon
DefaultDirName={autopf}\ArkRelay
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=ArkRelay-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
UninstallDisplayName={#AppName}
CloseApplications=no
WizardStyle=modern

[Dirs]
Name: "{commonappdata}\ark-relay"; Flags: uninsneveruninstall
Name: "{commonappdata}\ark-relay\state"; Flags: uninsneveruninstall

[Files]
Source: "{#Stage}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Stage}\versions\*"; DestDir: "{app}\versions"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Stage}\watchdog\*"; DestDir: "{app}\watchdog"; Flags: ignoreversion recursesubdirs
Source: "{#Stage}\launch.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Stage}\current.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "legacy.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "switch.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Stage}\handover\*"; DestDir: "{app}\handover"; Flags: ignoreversion recursesubdirs

[Run]
; Nothing here: the switch-over runs from [Code] (CurStepChanged) so that its exit code
; is checked. The steps are in switch.py.

[UninstallDelete]
; Version folders added by updates are not in [Files]; remove the whole folder.
Type: filesandordirs; Name: "{app}"

[Code]
var
  OldCurrent: String;

function ReadCurrent(): String;
var
  S: AnsiString;
begin
  Result := '';
  if LoadStringFromFile(ExpandConstant('{app}\current.txt'), S) then
    Result := Trim(String(S));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  // Upgrading over an earlier install: stop it so its files are not in use.
  OldCurrent := ReadCurrent();
  if FileExists(ExpandConstant('{app}\launch.py')) then
  begin
    Exec('sc.exe', 'stop ArkRelayWatchdog', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Exec(ExpandConstant('{#Py}'), '"' + ExpandConstant('{app}\launch.py') + '" stop', '',
         SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;

function RunSwitch(Args: String): Integer;
begin
  if not Exec(ExpandConstant('{#Py}'), '"' + ExpandConstant('{app}\switch.py') + '" ' + Args,
              ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Result) then
    Result := -1;
  Log('switch.py ' + Args + ' -> ' + IntToStr(Result));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Args: String;
begin
  if CurStep <> ssPostInstall then
    exit;
  // An installer older than the code the updater already brought in must not roll it
  // back: keep the newer version folder current.
  if (OldCurrent <> '') and DirExists(ExpandConstant('{app}\versions\') + OldCurrent) and
     (StrToInt64Def(OldCurrent, 0) > StrToInt64Def('{#AppVersion}', 0)) then
    SaveStringToFile(ExpandConstant('{app}\current.txt'), OldCurrent + #13#10, False);
  Args := 'install "--user=' + GetUserNameString() + '"';
  if ExpandConstant('{param:SKIPHANDOVER|0}') = '1' then
    Args := Args + ' --skip-handover';
  if (RunSwitch(Args) <> 0) and not WizardSilent() then
    MsgBox('The switch-over did not finish; the old relay was left running. ' +
           'Details: the setup log.', mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // Before the files go: stop everything, put AUTO-MAS back, remove the old relay's
  // leftovers (switch.py uninstall).
  if CurUninstallStep = usUninstall then
    RunSwitch('uninstall');
  // The data folder holds his records (.env with the push keys, state, logs). Kept
  // unless he says to delete it; a silent uninstall keeps it.
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
    if MsgBox('Also delete the relay''s data (C:\ProgramData\ark-relay: settings, state, logs)?',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{commonappdata}\ark-relay'), True, True, True);
end;
