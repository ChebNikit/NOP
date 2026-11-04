param([Parameter(Mandatory = $true)][string]$Root)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($Root)
$Tools = Join-Path $Root '.build-tools'
$Installer = Join-Path $Tools 'innosetup-7.1.1-x64.exe'
$InnoHome = Join-Path $Tools 'InnoSetup-7.1.1'
$Iscc = Join-Path $InnoHome 'ISCC.exe'
$Evidence = Get-Content -Raw -LiteralPath (Join-Path $Root 'bootstrap\inno-source.json') | ConvertFrom-Json
try {
    $Actual = ''
    if (Test-Path -LiteralPath $Installer -PathType Leaf) { $Actual = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant() }
    if ($Actual -cne $Evidence.sha256) {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $Partial = $Installer + '.part'
        for ($Attempt = 1; $Attempt -le 3; $Attempt++) {
            try {
                Write-Host "Restoring pinned Inno Setup compiler installer ($Attempt/3)..."
                Invoke-WebRequest -UseBasicParsing -Uri $Evidence.url -OutFile $Partial -TimeoutSec 600
                if ((Get-FileHash -LiteralPath $Partial -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Evidence.sha256) { throw 'Inno Setup installer SHA-256 mismatch.' }
                Move-Item -LiteralPath $Partial -Destination $Installer -Force
                break
            } catch {
                Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
                if ($Attempt -eq 3) { throw }
                Start-Sleep -Seconds (2 * $Attempt)
            }
        }
    }
    if (-not (Test-Path -LiteralPath $Iscc -PathType Leaf)) {
        Write-Host 'Preparing the bundled Inno compiler in the private build workspace...'
        $Arguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CURRENTUSER /PORTABLE=1 /NOICONS /TASKS="" /DIR="' + $InnoHome + '"'
        $Process = Start-Process -FilePath $Installer -ArgumentList $Arguments -PassThru
        if (-not $Process.WaitForExit(300000)) { $Process.Kill(); throw 'Inno compiler preparation timed out after 5 minutes.' }
        if ($Process.ExitCode -ne 0) { throw ('Inno compiler installer exit: ' + $Process.ExitCode) }
    }
    if (-not (Test-Path -LiteralPath $Iscc -PathType Leaf)) { throw "ISCC.exe is missing: $Iscc" }
    # Compile the real wizard/Pascal code before downloading/extracting large SDKs.
    # This isolated check has a separate name and output folder and cannot be promoted.
    Write-Host 'Checking the installer script before assembly; release versions are required only for the final installer.'
    & $Iscc '/DNOP_BUILDKIT_PREFLIGHT=1' (Join-Path $Root 'NOP_installer.iss')
    if ($LASTEXITCODE -ne 0) { throw 'The installer compiler rejected NOP_installer.iss; see the build log.' }
    Write-Host "Private Inno compiler and installer script checked: $Iscc"
} catch {
    Write-Host ('ERROR preparing Inno Setup: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
exit 0
