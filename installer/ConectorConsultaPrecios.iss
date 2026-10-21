#define MyAppName "Conector Consulta de Precios"
#define MyAppVersion "1.2.0"
#define MyAppExeName "ConectorConsultaPrecios.exe"
[Setup]
AppId={{74A3D2A7-6D6F-43B7-91C7-01C4EFA67B12}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\ConsultaPreciosConector
DefaultGroupName=Consulta de Precios
OutputDir=..\dist_instalador
OutputBaseFilename=Instalador_Conector_Consulta_Precios
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
[Dirs]
Name: "{commonappdata}\ConsultaPrecios"; Permissions: admins-full
[Files]
Source: "..\windows_bridge\dist\ConectorConsultaPrecios.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\windows_bridge\dist\ConfigurarConector.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "bridge.env.example"; DestDir: "{commonappdata}\ConsultaPrecios"; DestName: "bridge.env"; Flags: onlyifdoesntexist
Source: "RegistrarInicioAutomatico.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "DetenerConector.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "VigilarConector.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "DetenerConector.ps1"; Flags: dontcopy
[Icons]
Name: "{group}\Configurar con asistente"; Filename: "{app}\ConfigurarConector.exe"
Name: "{group}\Configurar conexión"; Filename: "notepad.exe"; Parameters: """{commonappdata}\ConsultaPrecios\bridge.env"""
Name: "{group}\Abrir buscador local"; Filename: "http://127.0.0.1:8765/login"
[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\RegistrarInicioAutomatico.ps1"" -ExePath ""{app}\{#MyAppExeName}"""; Flags: runhidden waituntilterminated
Filename: "{app}\ConfigurarConector.exe"; Description: "Configurar contraseña y conexión ahora"; Flags: postinstall nowait skipifsilent
[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\RegistrarInicioAutomatico.ps1"" -Remove -ExePath ""{app}\{#MyAppExeName}"""; Flags: runhidden waituntilterminated

[Code]
function StopConnector(const ScriptPath: String): Boolean;
var
  ResultCode: Integer;
  Args: String;
begin
  Args := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ScriptPath +
    '" -ExePath "' + ExpandConstant('{app}\{#MyAppExeName}') + '"';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Args, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  TempScript: String;
begin
  if CurStep = ssInstall then
  begin
    ExtractTemporaryFile('DetenerConector.ps1');
    TempScript := ExpandConstant('{tmp}\DetenerConector.ps1');
    if not StopConnector(TempScript) then
      RaiseException('No se pudo detener el conector anterior. ' +
        'Comprueba los permisos de administrador y vuelve a ejecutar el instalador.');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopConnector(ExpandConstant('{app}\DetenerConector.ps1'));
end;
