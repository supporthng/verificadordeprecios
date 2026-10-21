# Ejecutar como administrador en el equipo donde esta instalado el conector.
# Solo descarga versiones publicadas en GitHub Releases del repositorio indicado.
[CmdletBinding()]
param(
    [string]$Repositorio = 'supporthng/verificadordeprecios',
    [string]$Exe = 'C:\Program Files\ConsultaPreciosConector\ConectorConsultaPrecios.exe',
    [string]$Tarea = 'ConsultaPreciosConectorLAN'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Abre PowerShell como administrador y vuelve a ejecutar este archivo.'
}
if ($Repositorio -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'Repositorio no valido.' }
if (-not (Test-Path -LiteralPath $Exe)) { throw "No se encontro el conector: $Exe" }

$api = "https://api.github.com/repos/$Repositorio/releases/latest"
$headers = @{ 'User-Agent' = 'ConsultaPrecios-Updater'; 'Accept' = 'application/vnd.github+json' }
$release = Invoke-RestMethod -Uri $api -Headers $headers -TimeoutSec 30
if ($release.draft -or $release.prerelease -or $release.tag_name -notmatch '^conector-v\d+\.\d+\.\d+$') {
    throw 'La ultima publicacion no es una version valida del conector.'
}
$zipAsset = @($release.assets | Where-Object name -eq 'Conector_Actualizacion_Windows.zip')
$hashAsset = @($release.assets | Where-Object name -eq 'Conector_Actualizacion_Windows.sha256')
if ($zipAsset.Count -ne 1 -or $hashAsset.Count -ne 1) { throw 'Faltan archivos de actualizacion en GitHub Releases.' }

Write-Host "Version disponible: $($release.tag_name)"
$confirm = Read-Host 'Escribe SI para descargar e instalar esta version'
if ($confirm -cne 'SI') { Write-Host 'Cancelado, no se modifico nada.'; return }

$work = Join-Path $env:TEMP ('ConsultaPreciosUpdate-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work -Force | Out-Null
$zip = Join-Path $work 'update.zip'
$sha = Join-Path $work 'update.sha256'
$expanded = Join-Path $work 'extraido'
$backup = Join-Path $work 'ConectorConsultaPrecios.exe.bak'
$stopped = $false
$replaced = $false
try {
    Invoke-WebRequest -Uri $zipAsset[0].browser_download_url -OutFile $zip -TimeoutSec 120
    Invoke-WebRequest -Uri $hashAsset[0].browser_download_url -OutFile $sha -TimeoutSec 30
    $expected = (Get-Content -LiteralPath $sha -Raw).Trim().ToLowerInvariant()
    if ($expected -notmatch '^[a-f0-9]{64}$') { throw 'Archivo SHA256 no valido.' }
    $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw 'La descarga no coincide con SHA256; se cancelo la actualizacion.' }
    Expand-Archive -LiteralPath $zip -DestinationPath $expanded -Force
    $candidate = Join-Path $expanded 'ConectorConsultaPrecios.exe'
    if (-not (Test-Path -LiteralPath $candidate)) { throw 'El paquete no contiene el ejecutable esperado.' }
    if ((Get-Item -LiteralPath $candidate).Length -lt 100000) { throw 'El ejecutable descargado parece incompleto.' }

    Copy-Item -LiteralPath $Exe -Destination $backup -Force
    & schtasks.exe /End /TN $Tarea 2>$null | Out-Null
    Get-Process -Name 'ConectorConsultaPrecios' -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 3
    $stopped = $true
    Copy-Item -LiteralPath $candidate -Destination $Exe -Force
    $replaced = $true
    & schtasks.exe /Run /TN $Tarea | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar la tarea del conector.' }
    Start-Sleep -Seconds 5
    $running = Get-Process -Name 'ConectorConsultaPrecios' -ErrorAction SilentlyContinue
    if (-not $running) { throw 'El proceso no arranco despues de la actualizacion.' }
    Write-Host "Actualizacion $($release.tag_name) aplicada. Configuracion y credenciales conservadas."
}
catch {
    Write-Warning "Actualizacion fallida: $($_.Exception.Message)"
    if ($stopped -and (Test-Path -LiteralPath $backup)) {
        Get-Process -Name 'ConectorConsultaPrecios' -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 2
        Copy-Item -LiteralPath $backup -Destination $Exe -Force
        & schtasks.exe /Run /TN $Tarea | Out-Null
        Write-Warning 'Se restauro el ejecutable anterior.'
    }
    throw
}
finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
