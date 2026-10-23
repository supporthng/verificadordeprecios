$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
py -3 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
# Carpeta (onedir): pywebview + pythonnet funcionan mejor así que en un solo .exe.
& ".\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name ConsultaPrecios `
    --icon icono.ico --collect-all webview --collect-all clr_loader --hidden-import clr kiosco.py
if (-not (Test-Path ".\dist\ConsultaPrecios\ConsultaPrecios.exe")) { throw "No se generó ConsultaPrecios.exe" }
Write-Host "App creada: $PSScriptRoot\dist\ConsultaPrecios"
