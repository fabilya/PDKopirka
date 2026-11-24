; ============================================================================
; PDKopirka - Inno Setup Script
; Совместимость: Inno Setup 5.5+ / 6.x
;
; Две сборки из одного скрипта:
;   ISCC PDKopirka.iss                                  -> полный установщик (со встроенным LO)
;   ISCC /DNoLO /DOutputSuffix=_Update PDKopirka.iss    -> облегчённый пакет обновления (без LO)
; ============================================================================

#define MyAppName "PDKopirka"
#define MyAppVersion "3.2.6"
#define MyAppPublisher "PDKopirka"
#define MyAppExeName "PDKopirka.exe"
#define MyAppURL "https://github.com/fabilya/PDKopirka"

; Встроенный портативный LibreOffice 7.3.x включается по умолчанию.
; Облегчённый пакет обновления собирается с ключом /DNoLO: LibreOffice на
; машине уже стоит, второй раз его класть в установщик незачем.
#ifdef NoLO
  #define IncludeLO 0
#else
  #define IncludeLO 1
#endif

; Суффикс имени файла установщика: "" для полного, "_Update" для облечённого.
#ifndef OutputSuffix
  #define OutputSuffix ""
#endif

[Setup]
AppId={{8F4C8D7A-2D52-4A1A-9E6B-7A8B9C0D1E2F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}

; Всегда одна папка в профиле пользователя (без Program Files и без админа)
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
; no = не подставлять старый путь из Program Files, всегда DefaultDirName
UsePreviousAppDir=no

DisableDirPage=yes
DisableProgramGroupPage=yes

OutputDir=installer_output
OutputBaseFilename=PDKopirka_Setup_{#MyAppVersion}{#OutputSuffix}
SetupIconFile=logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

Compression=lzma2/ultra64
SolidCompression=yes

; Установка без прав администратора
PrivilegesRequired=lowest

MinVersion=6.1sp1

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные задачи:"; Flags: checkedonce

[Files]
Source: "dist\PDKopirka\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "logo.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "version.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion skipifsourcedoesntexist
Source: "dist\PDKopirka\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\PDKopirka\*.dll"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "dist\PDKopirka\*.pyd"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; Встроенный портативный LibreOffice 7.3.x (готовится tools\fetch_libreoffice.ps1).
; В облегчённый пакет обновления не попадает: он уже установлен на машине.
#if IncludeLO
Source: "vendor\libreoffice\*"; DestDir: "{app}\libreoffice"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
#endif

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
function IsWordInstalled(): Boolean;
begin
  { COM-регистрация Word.Application есть только у установленного Word }
  Result := RegKeyExists(HKEY_CLASSES_ROOT, 'Word.Application\CLSID');
end;

function HasBundledConverter(): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\libreoffice\program\soffice.exe')) or
            FileExists(ExpandConstant('{app}\libreoffice\program\soffice.com'));
end;

function ConverterMemo(): String;
begin
  if IsWordInstalled() then
    Result := 'Конвертер Word → PDF: Microsoft Word (эталонная вёрстка)'
  else if HasBundledConverter() then
    Result := 'Конвертер Word → PDF: встроенный LibreOffice 7.3.7 (запасной вариант)'
  else
    Result := 'Конвертер Word → PDF: не найден';
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := ConverterMemo() + NewLine + NewLine;
  if MemoDirInfo <> '' then
    Result := Result + MemoDirInfo + NewLine + NewLine;
  if MemoTasksInfo <> '' then
    Result := Result + MemoTasksInfo;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Msg: String;
begin
  if CurStep = ssPostInstall then
  begin
    if (not IsWordInstalled()) and (not HasBundledConverter()) then
    begin
      Msg := 'Конвертер Word → PDF не найден.' + #13#10 + #13#10 +
             'Установщик не содержит встроенный LibreOffice, а Microsoft Word на этом ' +
             'компьютере не установлен.' + #13#10 + #13#10 +
             'Конвертация Word → PDF будет недоступна, остальные функции программы ' +
             'работают как обычно.' + #13#10 + #13#10 +
             'Чтобы включить конвертацию, установите Microsoft Word или переустановите ' +
             'программу полным установщиком (со встроенным LibreOffice 7.3.7).';
      MsgBox(Msg, mbInformation, MB_OK);
    end;
  end;
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if CheckForMutexes('PDKopirka_Mutex') then
  begin
    if WizardSilent() then
    begin
      Exec('taskkill.exe', '/F /IM PDKopirka.exe', '', SW_HIDE,
           ewWaitUntilTerminated, ResultCode);
      Sleep(1000);
    end
    else
    begin
      if MsgBox('PDKopirka сейчас запущена.' + #13#10 + #13#10 +
                'Закрыть программу и продолжить установку?',
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        Exec('taskkill.exe', '/F /IM PDKopirka.exe', '', SW_HIDE,
             ewWaitUntilTerminated, ResultCode);
        Sleep(1000);
      end
      else
        Result := False;
    end;
  end;
end;
