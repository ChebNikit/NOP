; NOP Minimal: quiet graphite surfaces, native dark controls and compact copy.
#ifdef NOP_BUILDKIT_PREFLIGHT
; Compile-time labels only. The preflight executable cannot install anything.
#define PythonVersion "PREFLIGHT"
#define QtVersion "PREFLIGHT"
#define PyQtVersion "PREFLIGHT"
#define YtDlpVersion "PREFLIGHT"
#define NumPyVersion "PREFLIGHT"
#define PillowVersion "PREFLIGHT"
#define MutagenVersion "PREFLIGHT"
#define MuPDFVersion "PREFLIGHT"
#define FfmpegVersion "PREFLIGHT"
#define DenoVersion "PREFLIGHT"
#define APOVersion "PREFLIGHT"
#define VCVersion "0.0.0.0"
#else
; Release compilation must fail until assemble_bundle.py writes real versions.
#include "installer_versions.iss"
#endif
#define AppName "NOP — NikOmniPlayer"
#define AppVersion "1.0"
#define AppExeName "NOP.exe"

[Setup]
AppId={{A85FE438-C355-4A09-894F-867FA04C7B0E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=CheNik
DefaultDirName={localappdata}\Programs\NOP
DefaultGroupName=NOP
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
#ifdef NOP_BUILDKIT_PREFLIGHT
OutputDir=.build-tools\inno-preflight
OutputBaseFilename=compiler-check
#else
OutputDir=release\staging\win10
OutputBaseFilename=NOP_Setup
#endif
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern dark includetitlebar hidebevels
WizardBackColor=#24262a
WizardImageFile=installer-art\wizard.png
WizardImageBackColor=#24262a
WizardSmallImageFile=
WizardSizePercent=110,110
WizardResizable=yes
SetupIconFile=assets\nop.ico
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
VersionInfoCompany=CheNik
VersionInfoDescription=NOP NikOmniPlayer Setup
VersionInfoProductName={#AppName}
VersionInfoProductVersion=1.0.0.0
VersionInfoVersion=1.0.0.0

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
DialogFontName=Segoe UI
DialogFontSize=10
WelcomeLabel1=Установка NOP
WelcomeLabel2=Видео, музыка и работа с медиафайлами.%n%nВыберите папку — мастер установит плеер и необходимые компоненты. Python и библиотеки уже в комплекте.
FinishedHeadingLabel=Всё готово
FinishedLabel=NOP установлен. Можно запускать плеер.
ButtonBack=&Назад
ButtonNext=&Далее
ButtonInstall=&Установить
ButtonFinish=&Готово

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked

[Files]
#ifdef NOP_BUILDKIT_PREFLIGHT
Source: ".build-tools\7zip-full-26.05\7z.exe"; DestDir: "{app}"; DestName: "NOP.exe"; Flags: ignoreversion
#else
Source: "dist\NOP\NOP.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\NOP\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\NOP\ffmpeg.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\NOP\ffprobe.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\NOP\deno.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\NOP\mpv\*"; DestDir: "{app}\mpv"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\NOP\converters\*"; DestDir: "{app}\converters"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\NOP\source\*"; DestDir: "{app}\source"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\NOP\CHECK_INSTALLED.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\NOP\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\NOP\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\NOP\*.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\NOP\*.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "runtime_deps\installers\vc_redist.x64.exe"; Flags: dontcopy
Source: "runtime_deps\installers\EqualizerAPO-x64-1.4.2.exe"; Flags: dontcopy

#endif

[Icons]
Name: "{autoprograms}\NOP — NikOmniPlayer"; Filename: "{app}\NOP.exe"; WorkingDir: "{app}"; IconFilename: "{app}\NOP.exe"; AppUserModelID: "CheNik.NikOmniPlayer"
Name: "{autodesktop}\NOP — NikOmniPlayer"; Filename: "{app}\NOP.exe"; WorkingDir: "{app}"; IconFilename: "{app}\NOP.exe"; Tasks: desktopicon; AppUserModelID: "CheNik.NikOmniPlayer"

[Run]
Filename: "{app}\NOP.exe"; Description: "Запустить NOP"; Flags: postinstall nowait skipifsilent

[Code]
var
  DependenciesPage: TWizardPage;
  DependenciesMemo: TNewMemo;
  DetailsButton: TNewButton;
  MediaHeading, MediaNote, APOHeading: TNewStaticText;
  APONote: TNewStaticText;
  RuntimeNote: TNewStaticText;
  APOMessage: String;
  FinishedMessageAdded: Boolean;

#ifdef NOP_BUILDKIT_PREFLIGHT
function InitializeSetup(): Boolean;
begin
  MsgBox('Compiler check only. Run build_windows.bat to create NOP_Setup.exe.', mbInformation, MB_OK);
  Result := False;
end;
#endif

function EqualizerAPOInstalled(): Boolean;
var
  Folder: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM64, 'SOFTWARE\EqualizerAPO', 'InstallPath', Folder) then
    Result := FileExists(AddBackslash(Folder) + 'EqualizerAPO.dll');
  if not Result then
    Result := FileExists(ExpandConstant('{commonpf64}\EqualizerAPO\EqualizerAPO.dll'));
end;

function VersionPart(var Value: String): Integer;
var
  P: Integer;
  Part: String;
begin
  P := Pos('.', Value);
  if P > 0 then begin
    Part := Copy(Value, 1, P - 1);
    Delete(Value, 1, P);
  end else begin
    Part := Value;
    Value := '';
  end;
  Result := StrToIntDef(Part, 0);
end;

function VersionAtLeast(Current, Required: String): Boolean;
var
  I, A, B: Integer;
begin
  if (Length(Current) > 0) and ((Current[1] = 'v') or (Current[1] = 'V')) then
    Delete(Current, 1, 1);
  Result := True;
  for I := 1 to 4 do begin
    A := VersionPart(Current);
    B := VersionPart(Required);
    if A <> B then begin
      Result := A > B;
      Exit;
    end;
  end;
end;

function VisualCNeeded(): Boolean;
var
  Installed: Cardinal;
  Version: String;
begin
  Result := True;
  if RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) then begin
    if Installed = 1 then begin
      if RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Version', Version) then
        Result := not VersionAtLeast(Version, '{#VCVersion}');
    end;
  end;
end;

function SetupDependencies(): String;
begin
  Result := 'Встроено в NOP' + #13#10 + #13#10 +
    'Python {#PythonVersion} — встроенная среда приложения' + #13#10 +
    'PyQt6 {#PyQtVersion} / Qt {#QtVersion} — интерфейс и мультимедиа' + #13#10 +
    'NumPy {#NumPyVersion} — обработка аудио и изображения' + #13#10 +
    'yt-dlp {#YtDlpVersion} + EJS — загрузка медиа' + #13#10 +
    '{#FfmpegVersion}' + #13#10 + 'FFprobe — сведения о файлах' + #13#10 +
    '{#DenoVersion}' + #13#10 + 'libmpv LGPL x64 — видеодвижок' + #13#10 +
    'Pillow {#PillowVersion}, Mutagen {#MutagenVersion}, PyMuPDF {#MuPDFVersion}' + #13#10 + #13#10;
  if EqualizerAPOInstalled() then
    Result := Result + 'Equalizer APO уже установлен — сохраним текущую установку' + #13#10
  else
    Result := Result + 'Equalizer APO {#APOVersion} — установится автоматически для звука других программ' + #13#10;
  Result := Result + #13#10;
  if VisualCNeeded() then
    Result := Result + 'Microsoft Visual C++ Runtime {#VCVersion} — установится при подтверждении Windows.'
  else
    Result := Result + 'Microsoft Visual C++ Runtime — уже есть подходящая версия.';
end;

{ Use measured text heights instead of fixed rectangles so the summary wraps at DPI. }
function AddSummaryText(const Text: String; IsHeading: Boolean): TNewStaticText;
begin
  Result := TNewStaticText.Create(WizardForm);
  Result.Parent := DependenciesPage.Surface;
  Result.AutoSize := False;
  Result.WordWrap := True;
  Result.ShowAccelChar := False;
  Result.SetBounds(0, 0, DependenciesPage.SurfaceWidth, ScaleY(16));
  Result.Anchors := [akLeft, akTop, akRight];
  if IsHeading then Result.Font.Style := [fsBold];
  Result.Caption := Text;
  Result.AdjustHeight;
end;

procedure RefreshDependencySummary();
begin
  if EqualizerAPOInstalled() then
    APONote.Caption := 'Equalizer APO уже установлен. Его настройки сохранятся.'
  else
    APONote.Caption := 'Equalizer APO установится для звука других программ. В его мастере выберите свои наушники или колонки.';
  if VisualCNeeded() or not EqualizerAPOInstalled() then
    RuntimeNote.Caption := 'Для установки компонентов Windows может запросить права администратора.'
  else
    RuntimeNote.Caption := 'Необходимые системные компоненты уже установлены.';
  MediaHeading.AdjustHeight;
  MediaNote.Top := MediaHeading.Top + MediaHeading.Height + ScaleY(6);
  MediaNote.AdjustHeight;
  APOHeading.Top := MediaNote.Top + MediaNote.Height + ScaleY(20);
  APOHeading.AdjustHeight;
  APONote.Top := APOHeading.Top + APOHeading.Height + ScaleY(6);
  APONote.AdjustHeight;
  RuntimeNote.Top := APONote.Top + APONote.Height + ScaleY(16);
  RuntimeNote.AdjustHeight;
end;

procedure ToggleDependencyDetails(Sender: TObject);
var
  ShowDetails: Boolean;
begin
  ShowDetails := not DependenciesMemo.Visible;
  MediaHeading.Visible := not ShowDetails;
  MediaNote.Visible := not ShowDetails;
  APOHeading.Visible := not ShowDetails;
  APONote.Visible := not ShowDetails;
  RuntimeNote.Visible := not ShowDetails;
  DependenciesMemo.Visible := ShowDetails;
  if ShowDetails then begin
    DependenciesMemo.Text := SetupDependencies();
    DetailsButton.Caption := 'Кратко';
  end else
    DetailsButton.Caption := 'Версии компонентов';
end;

procedure InitializeWizard();
begin
  WizardForm.Caption := 'Установка NOP';
  WizardForm.WelcomeLabel1.Font.Size := 20;
  WizardForm.WelcomeLabel1.Font.Style := [];
  WizardForm.FinishedHeadingLabel.Font.Size := 20;
  WizardForm.FinishedHeadingLabel.Font.Style := [];
  WizardForm.PageNameLabel.Font.Style := [];
  DependenciesPage := CreateCustomPage(wpSelectDir, 'Всё необходимое в комплекте', 'Плеер и компоненты для работы с медиа');
  MediaHeading := AddSummaryText('NOP и медиабиблиотеки', True);
  MediaNote := AddSummaryText('Плеер, mpv, FFmpeg и движки конвертации включены. Python и библиотеки отдельно не нужны.', False);
  APOHeading := AddSummaryText('Системный эквалайзер', True);
  APONote := AddSummaryText('', False);
  RuntimeNote := AddSummaryText('', False);
  DetailsButton := TNewButton.Create(WizardForm);
  DetailsButton.Parent := DependenciesPage.Surface;
  DetailsButton.SetBounds(0, DependenciesPage.SurfaceHeight - ScaleY(28), ScaleX(176), ScaleY(28));
  DetailsButton.Anchors := [akLeft, akBottom];
  DetailsButton.Caption := 'Версии компонентов';
  DetailsButton.OnClick := @ToggleDependencyDetails;
  DependenciesMemo := TNewMemo.Create(WizardForm);
  DependenciesMemo.Parent := DependenciesPage.Surface;
  DependenciesMemo.SetBounds(0, 0, DependenciesPage.SurfaceWidth, DetailsButton.Top - ScaleY(12));
  DependenciesMemo.Anchors := [akLeft, akTop, akRight, akBottom];
  DependenciesMemo.ReadOnly := True;
  DependenciesMemo.WordWrap := True;
  DependenciesMemo.ScrollBars := ssVertical;
  DependenciesMemo.BorderStyle := bsNone;
  DependenciesMemo.Visible := False;
  RefreshDependencySummary();
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = DependenciesPage.ID then begin
    RefreshDependencySummary();
    DependenciesMemo.Text := SetupDependencies();
  end;
  if (CurPageID = wpFinished) and (APOMessage <> '') and not FinishedMessageAdded then begin
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10 + #13#10 + APOMessage;
    FinishedMessageAdded := True;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine + 'NOP и медиабиблиотеки — всё необходимое в комплекте.';
  if EqualizerAPOInstalled() then
    Result := Result + NewLine + 'Equalizer APO — уже установлен, настройки сохранятся.'
  else
    Result := Result + NewLine + 'Equalizer APO — установится автоматически.';
  if VisualCNeeded() then
    Result := Result + NewLine + 'Microsoft Visual C++ — установится при необходимости.';
  if MemoTasksInfo <> '' then
    Result := Result + NewLine + NewLine + MemoTasksInfo;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  Started: Boolean;
begin
  Result := '';
  if WizardSilent() and not EqualizerAPOInstalled() then begin
    Result := 'Для первой установки Equalizer APO запустите установщик NOP в обычном режиме: в мастере APO нужно выбрать устройство звука.';
    Exit;
  end;
  if not VisualCNeeded() then Exit;
  ExitCode := 0;
  ExtractTemporaryFile('vc_redist.x64.exe');
  WizardForm.StatusLabel.Caption := 'Установка необходимой среды Microsoft Visual C++...';
  if IsAdminInstallMode() then
    Started := Exec(ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart', '', SW_HIDE, ewWaitUntilTerminated, ExitCode)
  else
    Started := ShellExec('runas', ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart', '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if not Started then begin
    Result := 'Не удалось установить Microsoft Visual C++. Подтвердите запрос Windows на права администратора и повторите установку.';
    Exit;
  end;
  if ExitCode = 3010 then NeedsRestart := True;
  if (ExitCode <> 0) and (ExitCode <> 3010) and (ExitCode <> 1638) then
    Result := 'Установка Microsoft Visual C++ завершилась с кодом ' + IntToStr(ExitCode) + '. NOP пока не установлен.';
  { ShellExec can report successful elevation without proving the prerequisite was installed. }
  if (Result = '') and VisualCNeeded() then
    Result := 'Подходящая версия Microsoft Visual C++ пока не обнаружена. Завершите её установку и запустите мастер NOP повторно.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  Started: Boolean;
begin
  if CurStep <> ssPostInstall then Exit;
  if EqualizerAPOInstalled() then begin
    APOMessage := 'Equalizer APO уже установлен. Его настройки сохранены.';
    Exit;
  end;
  WizardForm.StatusLabel.Caption := 'Equalizer APO: выберите устройство звука в открывшемся мастере...';
  ExitCode := 0;
  ExtractTemporaryFile('EqualizerAPO-x64-1.4.2.exe');
  if IsAdminInstallMode() then
    Started := Exec(ExpandConstant('{tmp}\EqualizerAPO-x64-1.4.2.exe'), '', '', SW_SHOWNORMAL, ewWaitUntilTerminated, ExitCode)
  else
    Started := ShellExec('runas', ExpandConstant('{tmp}\EqualizerAPO-x64-1.4.2.exe'), '', '', SW_SHOWNORMAL, ewWaitUntilTerminated, ExitCode);
  if Started and ((ExitCode = 0) or (ExitCode = 3010)) and EqualizerAPOInstalled() then
    APOMessage := 'Equalizer APO установлен. Если его мастер попросил перезагрузку, выполните её перед использованием системного эквалайзера.'
  else
    APOMessage := 'NOP установлен, но установка Equalizer APO не завершена. Запустите установщик NOP снова и завершите мастер APO. Эквалайзер внутри NOP доступен.';
end;
