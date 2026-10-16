param([string]$ExePath)
$ErrorActionPreference = 'Stop'
$taskName = 'ConsultaPreciosConectorLAN'
try {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Disable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    }
    $target = [System.IO.Path]::GetFullPath($ExePath)
    $deadline = (Get-Date).AddSeconds(25)
    do {
        $matching = @(Get-CimInstance Win32_Process -Filter "Name = 'ConectorConsultaPrecios.exe'" -ErrorAction Stop | Where-Object {
            $_.ExecutablePath -and [string]::Equals($_.ExecutablePath, $target, [StringComparison]::OrdinalIgnoreCase)
        })
        if ($matching.Count -eq 0) { break }
        foreach ($proc in $matching) {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 700
    } while ((Get-Date) -lt $deadline)
    if ($matching.Count -gt 0) {
        throw "El conector sigue ejecutandose. Cierra el programa y reintenta."
    }
    exit 0
} catch {
    Write-Error $_
    exit 1
}
