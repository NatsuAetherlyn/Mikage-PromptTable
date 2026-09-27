; ============================================================================
;  Mikage PromptTable — installer script (Inno Setup 6)
;
;  Build:  "ISCC.exe" installer\MikagePromptTable.iss
;  Output: dist\MikagePromptTable-Setup-<version>.exe
;
;  Installs the app, creates Start Menu + optional desktop shortcuts, and calls
;  the app's own --register switch so Windows Search / uTools / ZTools can find
;  it. User data lives in <install dir>\data and is PRESERVED on upgrade and
;  (by default) kept on uninstall.
; ============================================================================

#define AppName        "Mikage PromptTable"
#define AppExeBase     "MikagePromptTable"
#define AppVersion     "1.0.1"
#define AppPublisher   "Mikage PromptTable"
#define AppExeName     "MikagePromptTable.exe"
#define AppDescription "AI 画廊与提示词注释工作台"
#define SourceRoot     ".."

[Setup]
AppId={{8F3A6C21-7E4B-4D92-9A15-3C8E5B7D4F60}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppComments={#AppDescription}
DefaultDirName={autopf}\{#AppExeBase}
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir={#SourceRoot}\dist
OutputBaseFilename={#AppExeBase}-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; per-user install: no admin prompt, and the app's HKCU registration works
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
AllowNoIcons=yes
MinVersion=10.0
SetupIconFile={#SourceRoot}\src\assets\app.ico
LicenseFile={#SourceRoot}\LICENSE

[Languages]
Name: "chinese"; MessagesFile: "compiler:Default.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"
Name: "register";    Description: "注册到 Windows 搜索 / 启动器 (uTools、ZTools 等)"; GroupDescription: "附加任务:"

[Files]
; the single-file executable
Source: "{#SourceRoot}\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; bundled icon used for shortcuts and as the window icon
Source: "{#SourceRoot}\src\assets\app.ico";    DestDir: "{app}\assets"; Flags: ignoreversion
Source: "{#SourceRoot}\src\assets\app_32.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "{#SourceRoot}\src\assets\app_128.png"; DestDir: "{app}\assets"; Flags: ignoreversion
; documentation
Source: "{#SourceRoot}\README.md";           DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "{#SourceRoot}\SHELL-INTEGRATION.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; NOTE: the shortcut points at the app icon; the app re-creates its own
; Start-Menu entry via --register when that task is selected.
Name: "{group}\{#AppName}";         Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\assets\app.ico"; Comment: "{#AppDescription}"
Name: "{userdesktop}\{#AppName}";   Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\assets\app.ico"; Comment: "{#AppDescription}"; Tasks: desktopicon

[Run]
; register with the shell (Start Menu / Search / launchers) through the app itself
Filename: "{app}\{#AppExeName}"; Parameters: "--register"; Flags: runhidden waituntilterminated; Tasks: register
; offer to launch after install
Filename: "{app}\{#AppExeName}"; Description: "立即运行 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; clean up the Start Menu entry and the App Paths key
Filename: "{app}\{#AppExeName}"; Parameters: "--unregister"; Flags: runhidden waituntilterminated; RunOnceId: "UnregisterShell"

[UninstallDelete]
; remove only build caches; <app>\data is intentionally left behind
Type: filesandordirs; Name: "{app}\build"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
{ ---------------------------------------------------------------- helpers }

function AppDataDir(): String;
begin
  Result := ExpandConstant('{app}\data');
end;

{ Ask before wiping user data, and keep it by default. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  HasData: Boolean;
  Answer: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    HasData := DirExists(AppDataDir());
    if HasData then
    begin
      Answer := MsgBox(
        '是否同时删除数据文件夹？' + #13#10#13#10 +
        '其中包含你的注释记录、模型库缓存等。' + #13#10 +
        ExpandConstant('{app}\data') + #13#10#13#10 +
        '选择「否」将保留这些数据，重新安装后可以继续使用。',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
      if Answer = IDYES then
        DelTree(AppDataDir(), True, True, True);
    end;
  end;
end;

{ Show where the data folder is kept, so users know what to back up. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  DataDir: String;
begin
  if CurStep = ssPostInstall then
  begin
    DataDir := AppDataDir();
    if not DirExists(DataDir) then
      CreateDir(DataDir);
  end;
end;
