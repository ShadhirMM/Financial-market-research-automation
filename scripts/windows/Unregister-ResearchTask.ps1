<#
.SYNOPSIS
    Removes the market research pack scheduled task (rollback for Register-ResearchTask.ps1).
#>
[CmdletBinding(SupportsShouldProcess)]
param([string]$TaskName = 'Market Research Pack')

$ErrorActionPreference = 'Stop'
if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    Write-Output "Task '$TaskName' is not registered; nothing to do."
    return
}
if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister scheduled task')) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed '$TaskName'. Reports, logs and data are left in place."
}
