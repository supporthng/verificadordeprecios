param([Parameter(Mandatory=$true)][string]$ExePath)
$ErrorActionPreference = 'Stop'
$taskName = 'ConsultaPreciosConectorLAN'
$target = [System.IO.Path]::GetFullPath($ExePath)
try {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Disable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    }
    $deadline = (Get-Date).AddSeconds(30)
    do {
        $procs = @(Get-CimInstance Win32_Process -Filter "Name='ConectorConsultaPrecios.exe'" | Where-Object {
            $_.ExecutablePath -and [string]::Equals($_.ExecutablePath,$target,[StringComparison]::OrdinalIgnoreCase)
        })
        foreach ($p in $procs) {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 800
    } while ($procs.Count -gt 0 -and (Get-Date) -lt $deadline)
    $remaining = @(Get-CimInstance Win32_Process -Filter "Name='ConectorConsultaPrecios.exe'" | Where-Object {
        $_.ExecutablePath -and [string]::Equals($_.ExecutablePath,$target,[StringComparison]::OrdinalIgnoreCase)
    })
    if ($remaining.Count -gt 0) { throw 'El conector anterior sigue activo.' }
    $listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        throw 'El puerto 8765 sigue ocupado. No se reemplazara ni arrancara otro conector.'
    }
    exit 0
} catch {
    Write-Error $_
    exit 1
}
