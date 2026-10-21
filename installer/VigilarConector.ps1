param([Parameter(Mandatory=$true)][string]$ExePath)
$ErrorActionPreference = 'Stop'
$taskName = 'ConsultaPreciosConectorLAN'
$healthy = $false
try {
    $h = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 5
    $healthy = ($h.ok -eq $true -and $null -ne $h.worker_age_seconds -and [double]$h.worker_age_seconds -lt 90)
} catch { $healthy = $false }
if ($healthy) { exit 0 }
# Reiniciar SOLO procesos que pertenecen a esta instalacion; nunca otro servidor en el puerto.
$target = [System.IO.Path]::GetFullPath($ExePath)
$procs = @(Get-CimInstance Win32_Process -Filter "Name='ConectorConsultaPrecios.exe'" | Where-Object {
    $_.ExecutablePath -and [string]::Equals($_.ExecutablePath,$target,[StringComparison]::OrdinalIgnoreCase)
})
foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
$occupied = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
if ($occupied.Count -gt 0) { exit 1 }
Start-ScheduledTask -TaskName $taskName
