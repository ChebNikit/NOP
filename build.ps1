param()
$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath($PSScriptRoot)
$LogRoot = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$Lock = $null
$Code = 1
try {
    $Lock = [System.IO.File]::Open((Join-Path $Root '.build.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    $Build = [int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
    if ($Build -lt 17763) { throw 'This Qt 6 build requires Windows 10 1809 / build 17763 or newer.' }
    if ($PSVersionTable.PSVersion.Major -lt 5) { throw 'Windows PowerShell 5.1 or newer is required.' }
    Start-Transcript -Path (Join-Path $LogRoot ('bootstrap-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')) | Out-Null
    Set-Location -LiteralPath $Root
    Remove-Item Env:\PYTHONHOME, Env:\PYTHONPATH -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONUTF8 = '1'
    & (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'prepare_build_python.ps1') -Root $Root
    if ($LASTEXITCODE -ne 0) { throw 'Private Python preparation failed; see bootstrap log.' }
    & (Join-Path $Root '.build-python\python.exe') -I -X utf8 (Join-Path $Root 'build.py')
    $Code = $LASTEXITCODE
} catch {
    Write-Host ('BUILD FAILED: ' + $_.Exception.Message) -ForegroundColor Red
} finally {
    try { Stop-Transcript | Out-Null } catch {}
    if ($null -ne $Lock) { $Lock.Dispose() }
}
exit $Code
