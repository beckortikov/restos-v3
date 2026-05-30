; RestOS POS — Inno Setup script
; Собирается в CI после PyInstaller. Берёт всё из apps/pos/dist/RestOS-POS/
; и пакует в один setup.exe с мастером установки.
;
; Параметры передаются через /D:
;   iscc /DAppVersion=1.0.0 installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

#define AppName "RestOS POS"
#define AppPublisher "RestOS"
#define AppURL "https://github.com/beckortikov/restos-v3"
#define AppExeName "RestOS-POS.exe"

[Setup]
AppId={{B7C8E1F2-3A45-4D6E-8F90-1234567890AB}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\RestOS-POS
DefaultGroupName=RestOS POS
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=RestOS-POS-Setup-{#AppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Поддержка тихой установки для in-app updater'а: /SILENT /VERYSILENT /NORESTART
CloseApplications=force
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Все содержимое pyinstaller dist/RestOS-POS — это и есть приложение
Source: "dist\RestOS-POS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Чистим runtime cache, но НЕ трогаем %APPDATA%/RestOS/license.json
; чтобы при переустановке/апгрейде сохранить активацию.
Type: filesandordirs; Name: "{app}\__pycache__"
