; Instalador de Prezio Administrador (la app de cada negocio: panel + conector de bases de datos) para Windows.
; Pide administrador una vez: instala para todos, prepara la carpeta de configuración y deja que el conector
; arranque solo al encender (tarea de Windows «Prezio Conector», que se activa desde el programa).
#define MyAppName "Prezio Administrador"
#ifndef MyAppVersion
  #define MyAppVersion "2.0.0"
#endif
#define MyAppExeName "PrezioAdministrador.exe"
[Setup]
AppId={{9C41E7B2-3D58-4A6F-B0E1-7F2A5D8C6B13}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Prezio
DefaultDirName={autopf}\Prezio Administrador
DefaultGroupName=Prezio
DisableProgramGroupPage=yes
OutputDir=..\..\dist_instalador
OutputBaseFilename=Instalador_Prezio_Administrador
SetupIconFile=prezio.ico
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=force
[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"
[Dirs]
; La ventana (usuario) y el envío automático (SYSTEM) escriben la misma configuración y el registro.
Name: "{commonappdata}\Prezio"; Permissions: users-modify
[Files]
Source: "dist\PrezioAdministrador\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Prezio Administrador"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Prezio Administrador"; Filename: "{app}\{#MyAppExeName}"; Tasks: escritorio
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Prezio Administrador"; Flags: postinstall nowait skipifsilent runasoriginaluser
; Actualización automática (instalación silenciosa):
;  · desde la ventana: volver a abrir la app para la persona que la estaba usando;
;  · desde la copia automática (/SERVICIO, como SYSTEM): no abrir ventanas, solo volver a arrancar la tarea.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait runasoriginaluser; Check: WizardSilent and not DesdeServicio
Filename: "schtasks.exe"; Parameters: "/Run /TN ""Prezio Conector"""; Flags: runhidden; Check: WizardSilent and TareaInstalada
[UninstallRun]
; Al desinstalar, quitar el arranque automático del conector.
Filename: "schtasks.exe"; Parameters: "/Delete /F /TN ""Prezio Conector"""; Flags: runhidden; RunOnceId: "QuitarTarea"

[Code]
function DesdeServicio(): Boolean;
begin
  Result := Pos('/SERVICIO', UpperCase(GetCmdTail)) > 0;
end;

function TareaInstalada(): Boolean;
var
  Codigo: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\schtasks.exe'), '/Query /TN "Prezio Conector"', '', SW_HIDE, ewWaitUntilTerminated, Codigo) and (Codigo = 0);
end;
