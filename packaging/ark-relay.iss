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
;   task \ArkRelay\main       starts the relay at logon of the user at the console
;                             (highest privileges, no time limit, normal priority)
;   C:\ProgramData\ark-relay  data (.env, state, logs): created here, kept on uninstall
;                             unless the user says otherwise
;   the old relay             retired 2026-10-11 (scripts/windows/retire_legacy.py):
;                             install refuses while its service still exists (two
;                             relays would both push and power off); what it left is
;                             deleted at uninstall (packaging/legacy.py remove, the
;                             list is relay/handover/legacy-items.json)
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
; Copied in this order. switch.py (and legacy.py, which it imports) first: when Setup
; ends part way, DeinitializeSetup runs {app}\switch.py resume, and a file already
; replaced is not put back by the rollback, so this way it is the new one in most cases.
Source: "legacy.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "switch.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Stage}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Stage}\versions\*"; DestDir: "{app}\versions"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Stage}\watchdog\*"; DestDir: "{app}\watchdog"; Flags: ignoreversion recursesubdirs
Source: "{#Stage}\launch.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Stage}\current.txt"; DestDir: "{app}"; Flags: ignoreversion
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
  SwitchFailed: Boolean;
  // PrepareToInstall stopped the installed relay and the switch-over (ssPostInstall)
  // has not taken over yet. Setup ending in between - Cancel, or a file that could not
  // be replaced (Abort, also the default answer of a /SUPPRESSMSGBOXES run) - would
  // leave the machine with no relay until the next logon; DeinitializeSetup starts the
  // previous version again then (switch.py resume).
  StoppedForUpgrade: Boolean;

function ReadCurrent(): String;
var
  S: AnsiString;
begin
  Result := '';
  if LoadStringFromFile(ExpandConstant('{app}\current.txt'), S) then
    Result := Trim(String(S));
end;

// '1234-2' (a re-deploy of 1234, see relay/pkg_layout.py) -> 1234.
function VersionOf(Name: String): Int64;
var
  Head: String;
begin
  Head := Name;
  if Pos('-', Head) > 0 then
    Head := Copy(Head, 1, Pos('-', Head) - 1);
  Result := StrToInt64Def(Head, 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  // Upgrading over an earlier install: stop the watchdog and the relay and wait until
  // both have exited (switch.py stop), so none of the files below are in use.
  OldCurrent := ReadCurrent();
  if FileExists(ExpandConstant('{app}\switch.py')) then
  begin
    // Set before the stop: one that stopped only part of it needs the start too.
    StoppedForUpgrade := True;
    Exec(ExpandConstant('{#Py}'), '"' + ExpandConstant('{app}\switch.py') + '" stop',
         ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code);
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
  Rc: Integer;
begin
  if CurStep <> ssPostInstall then
    exit;
  // From here switch.py install owns the outcome: on failure it goes back to the old
  // relay itself, and a resume on top would start the new watchdog next to it.
  StoppedForUpgrade := False;
  // An installer older than the code the updater already brought in must not roll it
  // back: keep the newer version folder current.
  if (OldCurrent <> '') and DirExists(ExpandConstant('{app}\versions\') + OldCurrent) and
     (VersionOf(OldCurrent) > VersionOf('{#AppVersion}')) then
    SaveStringToFile(ExpandConstant('{app}\current.txt'), OldCurrent + #13#10, False);
  Args := 'install "--user=' + GetUserNameString() + '"';
  if ExpandConstant('{param:SKIPHANDOVER|0}') = '1' then
    Args := Args + ' --skip-handover';
  // switch.py has already gone back to the old relay when it fails (switch.py revert).
  Rc := RunSwitch(Args);
  SwitchFailed := Rc <> 0;
  if SwitchFailed and not WizardSilent() then
    // 8: the old relay is still installed (switch.py install refuses; nothing started).
    if Rc = 8 then
      MsgBox('没有装上：老中继还在这台电脑上，两个中继不能同时跑，新中继没有打开。' +
             '先撤掉老中继再装。原因写在 C:\ProgramData\ark-relay\switch.log 里。',
             mbError, MB_OK)
    else
      MsgBox('新中继没有切换成功，已经退回老中继继续跑。原因写在安装日志里。',
             mbError, MB_OK);
end;

// A silent install (the updater, the cloud test) sees the failure in the exit code.
function GetCustomSetupExitCode(): Integer;
begin
  if SwitchFailed then
    Result := 1
  else
    Result := 0;
end;

// Inno Setup calls DeinitializeSetup on every way out once InitializeSetup has passed:
// after a cancel or a failed file it has already rolled back (Setup.Install.pas, then
// DeinitSetup in Setup.MainFunc.pas), so the files left are final. CancelButtonClick
// would miss a failed file, and CurStepChanged has no step for a failure (ssDone is
// after a successful install only). {app} is a plain value by now (WizardDirValue).
procedure DeinitializeSetup();
begin
  if not StoppedForUpgrade then
    exit;
  if RunSwitch('resume "--current=' + OldCurrent + '"') <> 0 then
    if not WizardSilent() then
      MsgBox('升级没有装完，原来的中继也没能重新开起来。原因写在 ' +
             'C:\ProgramData\ark-relay\switch.log 里；重新登录或重启电脑后它会自己开。',
             mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // Before the files go: stop everything, put AUTO-MAS back, remove the old relay's
  // leftovers (switch.py uninstall).
  // An exception here stops the uninstall before any file is deleted (Inno Setup,
  // Setup.Uninstall.pas: CurUninstallStepChanged(usUninstall) runs before
  // PerformUninstall and its exceptions are fatal). switch.py has started the relay
  // again in that case.
  if CurUninstallStep = usUninstall then
    if RunSwitch('uninstall') <> 0 then
    begin
      if not UninstallSilent() then
        MsgBox('没有卸载：AUTO-MAS 的设置没能改回原样（它可能正在跑任务）。' +
               '中继已经重新开起来，什么都没删。等 AUTO-MAS 空下来再卸载一次。',
               mbError, MB_OK);
      RaiseException('AUTO-MAS settings could not be put back; nothing was removed');
    end;
  // The data folder holds his records (.env with the push keys, state, logs). Kept
  // unless he says to delete it; a silent uninstall keeps it.
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
    if MsgBox('要不要把中继的数据也删掉？（C:\ProgramData\ark-relay：推送设置、记录、日志）',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{commonappdata}\ark-relay'), True, True, True);
end;
