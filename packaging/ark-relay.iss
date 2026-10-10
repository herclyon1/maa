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
;                             takeover), deleted at uninstall (legacy.py remove)

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

[Run]
; 1. The old relay must not run beside this one: both would push and power off.
Filename: "{#Py}"; Parameters: """{app}\legacy.py"" takeover"; Flags: runhidden waituntilterminated; StatusMsg: "Stopping the old relay..."
; 2. The main program: at logon, in the user's session, highest privileges (MAA runs
;    as administrator), no execution time limit (the default would end it after 72 h),
;    never a second copy.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""$a=New-ScheduledTaskAction -Execute '{#PyW}' -Argument '\""{app}\launch.py\""'; $t=New-ScheduledTaskTrigger -AtLogOn -User '{username}'; $p=New-ScheduledTaskPrincipal -UserId '{username}' -LogonType Interactive -RunLevel Highest; $s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew; Register-ScheduledTask -TaskPath '\ArkRelay\' -TaskName 'main' -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null"""; Flags: runhidden waituntilterminated; StatusMsg: "Registering the logon task..."
; 3. The watchdog service; Windows restarts it 3 s after any failure.
Filename: "{#Py}"; Parameters: """{app}\watchdog\ark_watchdog.py"" install"; Flags: runhidden waituntilterminated; StatusMsg: "Registering the watchdog service..."
Filename: "sc.exe"; Parameters: "failure ArkRelayWatchdog reset= 60 actions= restart/3000/restart/3000/restart/3000"; Flags: runhidden waituntilterminated
Filename: "sc.exe"; Parameters: "start ArkRelayWatchdog"; Flags: runhidden waituntilterminated
; 4. Start the relay now rather than at the next logon.
Filename: "schtasks.exe"; Parameters: "/run /tn ""\ArkRelay\main"""; Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "sc.exe"; Parameters: "stop ArkRelayWatchdog"; Flags: runhidden waituntilterminated; RunOnceId: "StopWatchdog"
Filename: "{#Py}"; Parameters: """{app}\launch.py"" stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopMain"
; Each version folder's `state` is a junction to C:\ProgramData\ark-relay\state
; (relay/pkg_layout.py link_state). Remove the junctions first, so deleting {app}
; below cannot reach into the data folder. rmdir without /s removes a junction only.
Filename: "cmd.exe"; Parameters: "/c for /d %d in (""{app}\versions\*"") do @if exist ""%d\state"" rmdir ""%d\state"""; Flags: runhidden waituntilterminated; RunOnceId: "UnlinkState"
Filename: "{#Py}"; Parameters: """{app}\watchdog\ark_watchdog.py"" remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveWatchdog"
Filename: "schtasks.exe"; Parameters: "/delete /tn ""\ArkRelay\main"" /f"; Flags: runhidden waituntilterminated; RunOnceId: "DeleteTask"
Filename: "{#Py}"; Parameters: """{app}\legacy.py"" remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveLegacy"

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

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // An installer older than the code the updater already brought in must not roll it
  // back: keep the newer version folder current.
  if (CurStep = ssPostInstall) and (OldCurrent <> '') and
     DirExists(ExpandConstant('{app}\versions\') + OldCurrent) and
     (StrToInt64Def(OldCurrent, 0) > StrToInt64Def('{#AppVersion}', 0)) then
    SaveStringToFile(ExpandConstant('{app}\current.txt'), OldCurrent + #13#10, False);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // The data folder holds his records (.env with the push keys, state, logs). Kept
  // unless he says to delete it; a silent uninstall keeps it.
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
    if MsgBox('Also delete the relay''s data (C:\ProgramData\ark-relay: settings, state, logs)?',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{commonappdata}\ark-relay'), True, True, True);
end;
