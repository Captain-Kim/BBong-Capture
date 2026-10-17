; BBong Capture 설치 파일 (Inno Setup 6)
#define AppName "BBong Capture"
#define AppVer "1.0.0"

[Setup]
AppId={{B6A1C3E0-5B7D-4C58-9E0A-BB0A6C0A9701}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=Captain-Kim
AppPublisherURL=https://github.com/Captain-Kim/BBong-Capture
DefaultDirName={autopf}\BBongCapture
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=BBongCapture-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\BBongCapture.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; Flags: unchecked

[Files]
Source: "..\dist\BBongCapture\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\BBongCapture.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\BBongCapture.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BBongCapture.exe"; Description: "BBong Capture 지금 실행"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c reg delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v BBongCapture /f"; Flags: runhidden; RunOnceId: "RmAutostart"
