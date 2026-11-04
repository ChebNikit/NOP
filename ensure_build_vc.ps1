param([Parameter(Mandatory = $true)][string]$Root)
$ErrorActionPreference = 'Stop'
try {
    $Root = [System.IO.Path]::GetFullPath($Root)
    $Payload = Join-Path $Root 'runtime_deps\installers\vc_redist.x64.exe'
    $Required = & (Join-Path $Root '.build-python\python.exe') -I -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8'))['vc_redist']['version'])" (Join-Path $Root 'runtime_deps\component-manifest.json')
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read the verified VC runtime version.' }
    $Required = [version]($Required.Trim())
    $Installed = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64' -ErrorAction SilentlyContinue
    if ($Installed -and $Installed.Installed -eq 1 -and [version]($Installed.Version.TrimStart('v','V')) -ge $Required) { exit 0 }
    & (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'verify_microsoft_payload.ps1') -Payload $Payload
    if ($LASTEXITCODE -ne 0) { throw 'Microsoft signature verification failed.' }
    Write-Host 'Windows will request permission to install Microsoft Visual C++ Runtime for the build.'
    $Process = Start-Process -FilePath $Payload -ArgumentList '/install /quiet /norestart' -Verb RunAs -Wait -PassThru
    if ($Process.ExitCode -notin @(0, 3010, 1638)) { throw ('VC runtime installer exit: ' + $Process.ExitCode) }
    $Installed = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64' -ErrorAction Stop
    if ($Installed.Installed -ne 1 -or [version]($Installed.Version.TrimStart('v','V')) -lt $Required) { throw 'Required VC runtime was not detected after setup.' }
    if ($Process.ExitCode -eq 3010) { throw 'VC Runtime requires a restart. Restart Windows and run the BuildKit again; caches are retained.' }
    exit 0
} catch {
    Write-Host ('VC RUNTIME FAILED: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
