# NOP build kit - stage 0 (ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less files as ANSI).
# Provisions a PRIVATE Python 3.13 inside .build\python (official NuGet package of the Python release team,
# Authenticode-verified) and then hands over to build\build_kit.py. Nothing global is installed or modified.
param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $KitArgs)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$Kit    = Split-Path -Parent $PSScriptRoot
$Work   = Join-Path $Kit '.build'
$Cache  = Join-Path $Kit 'cache'
$PyDir  = Join-Path $Work 'python'
$PyExe  = Join-Path $PyDir 'python.exe'
New-Item -ItemType Directory -Force -Path $Work, $Cache | Out-Null

function Fail([string] $Message) {
    Write-Host ''
    Write-Host ('BUILD FAILED: ' + $Message) -ForegroundColor Red
    exit 1
}

if ([Environment]::OSVersion.Version.Build -lt 17763) { Fail 'Windows 10 1809 (build 17763) or newer is required.' }
if (-not [Environment]::Is64BitOperatingSystem) { Fail 'A 64-bit Windows is required.' }

if (-not (Test-Path -LiteralPath $PyExe)) {
    Write-Host '== Provisioning private Python 3.13 =='
    try {
        $Index = Invoke-RestMethod -UseBasicParsing -Uri 'https://api.nuget.org/v3-flatcontainer/python/index.json'
    } catch {
        Fail ('Cannot reach nuget.org (' + $_.Exception.Message + '). Check the internet connection/proxy, or copy a Python 3.13 x64 folder (with python.exe) to .build\python manually.')
    }
    $Version = $Index.versions | Where-Object { $_ -match '^3\.13\.\d+$' } | Sort-Object { [version]$_ } | Select-Object -Last 1
    if (-not $Version) { Fail 'No stable Python 3.13 release was found on NuGet.' }
    Write-Host ('   Python ' + $Version)
    $Package = Join-Path $Cache ('python.' + $Version + '.nupkg')
    if (-not (Test-Path -LiteralPath $Package)) {
        $Url = 'https://api.nuget.org/v3-flatcontainer/python/' + $Version + '/python.' + $Version + '.nupkg'
        try { Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile ($Package + '.part') } catch { Fail ('Download failed: ' + $_.Exception.Message) }
        Move-Item -LiteralPath ($Package + '.part') -Destination $Package
    }
    $Temp = Join-Path $Work 'python-unpack'
    if (Test-Path -LiteralPath $Temp) { Remove-Item -LiteralPath $Temp -Recurse -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($Package, $Temp)
    $Tools = Join-Path $Temp 'tools'
    if (-not (Test-Path -LiteralPath (Join-Path $Tools 'python.exe'))) { Fail 'The Python package has an unexpected layout (tools\python.exe is missing).' }
    $Signature = Get-AuthenticodeSignature -LiteralPath (Join-Path $Tools 'python.exe')
    if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        Remove-Item -LiteralPath $Temp -Recurse -Force
        Fail 'python.exe is not signed by the Python Software Foundation. The package was rejected.'
    }
    if (Test-Path -LiteralPath $PyDir) { Remove-Item -LiteralPath $PyDir -Recurse -Force }
    Move-Item -LiteralPath $Tools -Destination $PyDir
    Remove-Item -LiteralPath $Temp -Recurse -Force
}

& $PyExe -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 13) else 1)"
if ($LASTEXITCODE -ne 0) { Fail 'The private Python is not version 3.13. Delete the .build\python folder and run again.' }

& $PyExe -m pip --version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '== Installing pip from the interpreter''s bundled wheel =='
    & $PyExe -m ensurepip --default-pip
    if ($LASTEXITCODE -ne 0) { Fail 'ensurepip failed.' }
}

Write-Host '== Starting the NOP build =='
& $PyExe (Join-Path $PSScriptRoot 'build_kit.py') @KitArgs
exit $LASTEXITCODE
