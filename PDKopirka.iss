; ============================================================================
; PDKopirka — Inno Setup Script
; ============================================================================
; ВАЖНО: AppId НИКОГДА не меняйте между версиями!
; Только AppVersion обновляйте при каждом релизе.
; ============================================================================

#define MyAppName "PDKopirka"
#define MyAppVersion "1.0.3"
#define MyAppPublisher "PDKopirka"
#define MyAppExeName "PDKopirka.exe"
#define MyAppURL "https://github.com/fabilya/PDKopirka"

[Setup]
; ВАЖНО: Этот AppId должен быть ОДИНАКОВЫМ во всех версиях!
; Именно он говорит Windows что это ТА ЖЕ программа.
; Никогда не меняйте эту строку!
AppId={{8F4C8D7A-2D52-4A1A-9E6B-7A8B9C0D1E2F}

AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}

; Папка установки — БЕЗ версии в имени!
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}

; Не спрашивать папку и группу — ставим молча в ту же папку
DisableDirPage=yes
DisableProgramGroupPage=yes

; Имя выходного файла установщика
OutputDir=installer_output
OutputBaseFilename=PDKopirka_Setup_{#MyAppVersion}

; Иконка установщика (если существует в текущей папке)
SetupIconFile=logo.ico

; Иконка в "Установка и удаление программ"
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; Сжатие
Compression=lzma2/ultra64
SolidCompression=yes

; Права администратора (для Program Files)
PrivilegesRequired=admin

; Автоматически закрыть программу перед обновлением БЕЗ ДИАЛОГА
CloseApplications=yes
CloseApplicationsFilter=*.exe

; Перезапустить программу после обновления
RestartApplications=yes

; ПОЛНОСТЬЮ ТИХИЙ РЕЖИМ - не показывать ничего при установке
ShowLanguageDialog=no
ShowTasksTreeLines=no
AlwaysShowComponentsList=no

; Минимальная версия Windows
MinVersion=10.0

; Архитектура
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible


[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"


[Tasks]
; Галочка "Создать ярлык на рабочем столе"
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные задачи:"; Flags: checkedonce


[Files]
; Копируем ВСЕ файлы из папки dist/PDKopirka (относительный путь)
; ignoreversion — всегда перезаписывать (важно для обновлений!)
Source: "dist\PDKopirka\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "logo.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\PDKopirka\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; Если есть другие файлы в корне сборки (dll, pyd и т.д.)
Source: "dist\PDKopirka\*.dll"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "dist\PDKopirka\*.pyd"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist


[Icons]
; Ярлык на рабочем столе (только если пользователь поставил галочку)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon

; Ярлык в меню Пуск
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"

; Ярлык удаления в меню Пуск
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"


[Run]
; Запустить программу после установки (галочка)
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent


[InstallDelete]
; Удаляем старые файлы _internal перед обновлением
; чтобы не накапливался мусор от предыдущих версий
Type: filesandordirs; Name: "{app}\_internal"


[Code]
// Если программа запущена — предложить закрыть (БЕЗ ДИАЛОГА при /SILENT)
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  
  // Проверяем, запущена ли программа
  if CheckForMutexes('{#MyAppName}_Mutex') then
  begin
    // При тихой установке закрываем автоматически без диалога
    if WizardSilent() then
    begin
      Exec('taskkill.exe', '/F /IM {#MyAppExeName}', '',
           SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Sleep(1000);
    end
    else
    begin
      // При обычной установке спрашиваем
      if MsgBox('{#MyAppName} сейчас запущена.'#13#10#13#10 +
                'Закрыть программу и продолжить установку?',
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        Exec('taskkill.exe', '/F /IM {#MyAppExeName}', '',
             SW_HIDE, ewWaitUntilTerminated, ResultCode);
        Sleep(1000);
      end
      else
      begin
        Result := False;
      end;
    end;
  end;
end;
