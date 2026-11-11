#Requires -Version 5.1
<#
.SYNOPSIS
Audit or safely clean local Claude data on Windows (Python 3.10+ required).
.EXAMPLE
.\claude_cleanup_windows.ps1 -Audit
.EXAMPLE
.\claude_cleanup_windows.ps1
#>
[CmdletBinding()]
param([switch]$Audit)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') {
    Write-Error 'This entry point requires native Windows.' -ErrorAction Continue
    exit 2
}

$cleanupScript = Join-Path $PSScriptRoot 'claude_cleanup_windows.py'
$cleanupPython = $null
$cleanupPrefix = @()
foreach ($candidate in @('py.exe', 'python.exe', 'python3.exe')) {
    $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) { continue }
    # Ignore Windows Store aliases, which may open a store window instead of Python.
    if ($command.Source -like '*\Microsoft\WindowsApps\*') { continue }
    $candidatePrefix = @()
    if ($candidate -eq 'py.exe') { $candidatePrefix = @('-3') }
    try {
        & $command.Source @candidatePrefix -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
    } catch { continue }
    if ($LASTEXITCODE -eq 0) {
        $cleanupPython = $command.Source
        $cleanupPrefix = $candidatePrefix
        break
    }
}
if (-not $cleanupPython) {
    Write-Error 'Python 3.10+ was not found. Install Python, then rerun this script.' -ErrorAction Continue
    exit 2
}

$cleanupArguments = @('-B', '-X', 'utf8', $cleanupScript)
if ($Audit) { $cleanupArguments += '--audit' }
& $cleanupPython @cleanupPrefix @cleanupArguments
exit $LASTEXITCODE
