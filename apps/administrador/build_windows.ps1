$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
py -3 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
# Cliente de Firebird (fbclient.dll): lo baja GitHub Actions a .\firebird; si está, va dentro de la app.
$extra = @()
if (Test-Path ".\firebird\fbclient.dll") { $extra += @("--add-data", "firebird;firebird") } else { Write-Warning "Sin cliente de Firebird: la app no podrá conectar Firebird." }
# Carpeta (onedir): pywebview + pythonnet funcionan mejor así. Incluye el conector, los motores y la ventana.
& ".\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name PrezioAdministrador `
    --icon prezio.ico --paths ..\..\conector `
    --hidden-import prezio_conector --hidden-import motores --hidden-import red --hidden-import cifrado `
    --hidden-import pyodbc --hidden-import pymysql --hidden-import pg8000.dbapi --collect-submodules firebird `
    --add-data "interfaz.html;." --collect-all webview --collect-all clr_loader --hidden-import clr @extra administrador.py
if (-not (Test-Path ".\dist\PrezioAdministrador\PrezioAdministrador.exe")) { throw "No se generó PrezioAdministrador.exe" }
& ".\.venv\Scripts\python.exe" -c "import pyodbc, pymysql, pg8000.dbapi, firebird.driver; print('motores listos', pyodbc.version, pymysql.__version__)"
Write-Host "App creada: $PSScriptRoot\dist\PrezioAdministrador"
