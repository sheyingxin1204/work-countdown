#define MyAppName "班时钟"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "sheyingxin1204"
#define MyAppURL "https://github.com/sheyingxin1204/work-countdown"
#define MyAppExeName "班时钟.exe"

[Setup]
AppId={{3F0EF6E8-7E3B-4D68-BD5A-7A3E6E2B3C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\BanClock
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=BanClock-Setup-{#MyAppVersion}
SetupIconFile=assets\ban-clock.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："
Name: "startupicon"; Description: "登录 Windows 时自动启动"; GroupDescription: "附加快捷方式："

[Files]
Source: "dist\班时钟.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "update_helper.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动{#MyAppName}"; Flags: nowait postinstall skipifsilent
