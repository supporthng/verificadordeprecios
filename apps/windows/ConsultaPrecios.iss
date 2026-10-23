; Instalador de "Consulta de Precios" para Windows (verificador tipo quiosco).
; Se instala para el usuario actual (no pide administrador) y arranca al iniciar sesión.
#define MyAppName "Consulta de Precios"
#define MyAppVersion "1.1.0"
#define MyAppExeName "ConsultaPrecios.exe"
[Setup]
AppId={{B8E7C3F2-5A41-4C9E-9F0D-3C6A1E2B7D45}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=supporthng
DefaultDirName={localappdata}\Programs\ConsultaPrecios
DefaultGroupName=Consulta de Precios
DisableProgramGroupPage=yes
OutputDir=..\..\dist_instalador
OutputBaseFilename=Instalador_Consulta_de_Precios
SetupIconFile=icono.ico
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=force
RestartApplications=no
[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
[Tasks]
Name: "inicio"; Description: "Abrir automáticamente al iniciar Windows (recomendado para el verificador)"
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"
[Files]
Source: "dist\ConsultaPrecios\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Consulta de Precios"; Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\Consulta de Precios"; Filename: "{app}\{#MyAppExeName}"; Tasks: escritorio
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ConsultaPrecios"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: inicio
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Consulta de Precios ahora"; Flags: postinstall nowait skipifsilent
; Actualización automática (instalación silenciosa desde la app): volver a abrirla al terminar.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: WizardSilent
