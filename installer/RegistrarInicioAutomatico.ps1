param([Parameter(Mandatory=$true)][string]$ExePath,[switch]$Remove)
$ErrorActionPreference = 'Stop'
$taskName = 'ConsultaPreciosConectorLAN'
$watchName = 'ConsultaPreciosConectorVigilancia'
if ($Remove) {
    foreach ($name in @($watchName,$taskName)) {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    }
    exit 0
}
$action = New-ScheduledTaskAction -Execute $ExePath
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
$watchScript = Join-Path (Split-Path $ExePath) 'VigilarConector.ps1'
$watchAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -ExePath "{1}"' -f $watchScript,$ExePath)
$watchTrigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 1)
$watchSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 45) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $watchName -Action $watchAction -Trigger $watchTrigger -Principal $principal -Settings $watchSettings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 5
$health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 5
if (-not $health.ok) { throw 'El conector no respondio al iniciar.' }
