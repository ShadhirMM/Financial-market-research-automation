<#
.SYNOPSIS
    Registers a weekly Windows scheduled task that runs the market research pack.

.DESCRIPTION
    Runs `python -m market_research run` from the project folder, using the
    project's virtual environment. The task:
      - runs weekly (default Monday 06:00, local time),
      - starts as soon as possible if the PC was off at that time,
      - never starts a second copy while one is running,
      - is stopped if it runs longer than 1 hour.
    Exit codes from the collector: 0 = OK/WARNING, 1 = ALERT, 2 = fatal.
    Task Scheduler shows them under "Last Run Result" (0x0, 0x1, 0x2).

    Use -WhatIf to see what would be registered without changing anything.

.EXAMPLE
    .\Register-ResearchTask.ps1
.EXAMPLE
    .\Register-ResearchTask.ps1 -Day Friday -Time 18:30 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = 'Market Research Pack',
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$PythonExe,
    [ValidateSet('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')]
    [string]$Day = 'Monday',
    [ValidatePattern('^\d{2}:\d{2}$')]
    [string]$Time = '06:00'
)

$ErrorActionPreference = 'Stop'

if (-not $PythonExe) { $PythonExe = Join-Path $ProjectDir '.venv\Scripts\python.exe' }
if (-not (Test-Path $PythonExe)) {
    throw "Python not found at '$PythonExe'. Create the virtual environment first (docs/INSTALL.md, step 2) or pass -PythonExe."
}
if (-not (Test-Path (Join-Path $ProjectDir 'config\config.toml'))) {
    throw "config\config.toml not found under '$ProjectDir'."
}

# Pre-flight: the config must be valid before scheduling anything.
Push-Location $ProjectDir
try {
    & $PythonExe -m market_research check
    if ($LASTEXITCODE -ne 0) { throw "Pre-flight check failed (exit $LASTEXITCODE). Fix the config/.env first." }
}
finally { Pop-Location }

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument '-m market_research run' -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$description = "Downloads market data and writes reports\latest.xlsx. Logs: $ProjectDir\logs. Registered $(Get-Date -Format s)."

if ($PSCmdlet.ShouldProcess($TaskName, "Register weekly task ($Day $Time) running '$PythonExe -m market_research run'")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description $description -Force | Out-Null

    Write-Output "Registered '$TaskName': next run $((Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime)"
    Write-Output "Test it now with:  Start-ScheduledTask -TaskName '$TaskName'"
    Write-Output "Remove it with:    .\Unregister-ResearchTask.ps1"
}
