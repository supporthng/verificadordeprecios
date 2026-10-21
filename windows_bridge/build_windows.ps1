$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
py -3 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --name ConectorConsultaPrecios --collect-all uvicorn --collect-all fastapi --collect-all multipart --hidden-import=pyodbc --hidden-import=uvicorn.logging --hidden-import=uvicorn.loops.auto --hidden-import=uvicorn.protocols.http.auto --hidden-import=uvicorn.protocols.websockets.auto --hidden-import=uvicorn.lifespan.on entry.py
# Impide publicar un EXE que no incluya el modulo SQL requerido.
& ".\.venv\Scripts\python.exe" -c "import pyodbc; print('pyodbc disponible:', pyodbc.version)"
if ($LASTEXITCODE -ne 0) { throw 'Falta pyodbc: no se puede compilar el conector SQL' }
Write-Host "EXE creado: $PSScriptRoot\dist\ConectorConsultaPrecios.exe"

& ".\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name ConfigurarConector configurar.py
