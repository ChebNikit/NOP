param(
    [Parameter(Mandatory = $true)][string]$Root
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($PSVersionTable.PSVersion.Major -lt 6) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}

$Root = [System.IO.Path]::GetFullPath($Root)
$Tools = Join-Path $Root '.build-tools'
$PythonHome = Join-Path $Root '.build-python'
$PythonExe = Join-Path $PythonHome 'python.exe'
$Marker = Join-Path $PythonHome 'NOP_NUGET_RUNTIME.txt'
$PythonVersion = '3.13.17'
$PackageName = 'python.' + $PythonVersion + '.nupkg'
$PackagePath = Join-Path $Tools $PackageName
$HashPath = Join-Path $Tools ($PackageName + '.sha512')
$ExtractDir = Join-Path $Tools 'python-nuget-extracted'
$PackageTools = Join-Path $ExtractDir 'tools'
$PackageUrl = 'https://api.nuget.org/v3-flatcontainer/python/' + $PythonVersion + '/' + $PackageName
$HashUrl = $PackageUrl + '.sha512'

New-Item -ItemType Directory -Path $Tools -Force | Out-Null

function Invoke-DownloadWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Destination,
        [long]$MinimumBytes = 1,
        [int]$Attempts = 3
    )
    $Partial = $Destination + '.download-part'
    for ($Attempt = 1; $Attempt -le $Attempts; $Attempt++) {
        try {
            Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
            Write-Host ("Download attempt {0}/{1}: {2}" -f $Attempt, $Attempts, $Uri)
            if ($PSVersionTable.PSVersion.Major -lt 6) {
                Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Partial -TimeoutSec 900
            } else {
                Invoke-WebRequest -Uri $Uri -OutFile $Partial -TimeoutSec 900
            }
            if (-not (Test-Path -LiteralPath $Partial) -or (Get-Item -LiteralPath $Partial).Length -lt $MinimumBytes) {
                throw ("Downloaded file is missing or too small (minimum {0} bytes)." -f $MinimumBytes)
            }
            Move-Item -LiteralPath $Partial -Destination $Destination -Force
            return
        } catch {
            $Message = $_.Exception.Message
            Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
            if ($Attempt -ge $Attempts) {
                throw ("Download failed after {0} attempts: {1}. Last error: {2}" -f $Attempts, $Uri, $Message)
            }
            Write-Host ("Download failed: {0}. Retrying shortly..." -f $Message) -ForegroundColor Yellow
            Start-Sleep -Seconds ([Math]::Min(10, 2 * $Attempt))
        }
    }
}

function Invoke-RestMethodWithRetry {
    param([Parameter(Mandatory = $true)][string]$Uri, [int]$Attempts = 3)
    for ($Attempt = 1; $Attempt -le $Attempts; $Attempt++) {
        try {
            if ($PSVersionTable.PSVersion.Major -lt 6) {
                return Invoke-RestMethod -UseBasicParsing -Uri $Uri -TimeoutSec 60
            } else {
                return Invoke-RestMethod -Uri $Uri -TimeoutSec 60
            }
        } catch {
            $Message = $_.Exception.Message
            if ($Attempt -ge $Attempts) {
                throw ("Request failed after {0} attempts: {1}. Last error: {2}" -f $Attempts, $Uri, $Message)
            }
            Write-Host ("Metadata request failed: {0}. Retrying..." -f $Message) -ForegroundColor Yellow
            Start-Sleep -Seconds ([Math]::Min(8, 2 * $Attempt))
        }
    }
}

function Test-PrivatePython {
    if (-not (Test-Path -LiteralPath $PythonExe) -or -not (Test-Path -LiteralPath $Marker)) { return $false }
    try {
        $null = & $PythonExe -c "import sys,struct; sys.exit(0 if sys.version_info[:3] == (3,13,17) and struct.calcsize('P') == 8 else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

try {
    if (-not (Test-PrivatePython)) {
        if (Test-Path -LiteralPath $PythonHome) {
            Write-Host 'Removing the old/incomplete private Python directory; no system Python installer will be run...'
            Remove-Item -LiteralPath $PythonHome -Recurse -Force
        }
        if (Test-Path -LiteralPath $ExtractDir) {
            Remove-Item -LiteralPath $ExtractDir -Recurse -Force
        }

        if (Test-Path -LiteralPath $PackagePath) {
            if ((Get-Item -LiteralPath $PackagePath).Length -lt 10000000) {
                Write-Host 'Cached NuGet package is incomplete; removing it before a clean download...' -ForegroundColor Yellow
                Remove-Item -LiteralPath $PackagePath -Force
            }
        }
        if (-not (Test-Path -LiteralPath $PackagePath)) {
            Write-Host "Downloading official Python $PythonVersion NuGet build package..."
            Invoke-DownloadWithRetry -Uri $PackageUrl -Destination $PackagePath -MinimumBytes 10000000 -Attempts 3
        }
        if (-not (Test-Path -LiteralPath $PackagePath) -or (Get-Item -LiteralPath $PackagePath).Length -lt 10000000) {
            throw "Python NuGet package is still missing or too small after download retries: $PackagePath"
        }
        # NuGet's flat-container .sha512 sidecar can briefly return HTTP 404 for a
        # newly published package even while the .nupkg itself is downloadable.
        # Validate any cached sidecar before trusting it, then fall back to the
        # official NuGet v3 registration -> catalog metadata, which publishes the
        # packageHash/packageHashAlgorithm fields for the same package version.
        $ExpectedHash = 'DmZ5KLtPGVc8bNiPZRM7LgeyQ6XHFvM1tWqma7nsb4IyglbSLDop4joCdqxcam14YhH+q1JIkK0eVmKRlsaynA==' # pinned from the official NuGet catalog; no metadata request needed
        if (-not $ExpectedHash -and (Test-Path -LiteralPath $HashPath)) {
            $CachedHash = [System.IO.File]::ReadAllText($HashPath).Trim()
            if ($CachedHash -match '^[A-Za-z0-9+/]{80,88}={0,2}$') {
                $ExpectedHash = $CachedHash
            } else {
                Remove-Item -LiteralPath $HashPath -Force -ErrorAction SilentlyContinue
            }
        }

        if (-not $ExpectedHash) {
            Write-Host 'Downloading the package SHA-512 checksum from the official NuGet feed...'
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $HashUrl -OutFile $HashPath -TimeoutSec 60
                if (-not $ExpectedHash -and (Test-Path -LiteralPath $HashPath)) {
                    $SidecarHash = [System.IO.File]::ReadAllText($HashPath).Trim()
                    if ($SidecarHash -match '^[A-Za-z0-9+/]{80,88}={0,2}$') {
                        $ExpectedHash = $SidecarHash
                    }
                }
            } catch {
                Write-Host ('NuGet .sha512 sidecar unavailable: ' + $_.Exception.Message) -ForegroundColor Yellow
            }
        }

        if (-not $ExpectedHash) {
            Write-Host 'Fallback: retrieving the package hash from official NuGet v3 registration/catalog metadata...'
            try {
                $RegistrationUrl = 'https://api.nuget.org/v3/registration5-gz-semver2/python/' + $PythonVersion + '.json'
                $Registration = Invoke-RestMethodWithRetry -Uri $RegistrationUrl
                $CatalogEntry = $null
                $CatalogRef = $Registration.catalogEntry
                if ($CatalogRef -is [string]) {
                    $CatalogEntry = Invoke-RestMethodWithRetry -Uri $CatalogRef
                } elseif ($null -ne $CatalogRef) {
                    # Some NuGet registration responses embed catalogEntry metadata
                    # directly; others return its catalog URL.
                    $CatalogEntry = $CatalogRef
                }
                if (-not $CatalogEntry -or -not $CatalogEntry.packageHash) {
                    # Last fallback: locate this exact version in the official
                    # registration index, whose page may embed the metadata.
                    $RegistrationIndex = Invoke-RestMethodWithRetry -Uri 'https://api.nuget.org/v3/registration5-gz-semver2/python/index.json'
                    foreach ($RegistrationPage in @($RegistrationIndex.items)) {
                        $PageData = $RegistrationPage
                        if (-not $PageData.items -and $PageData.'@id') {
                            $PageData = Invoke-RestMethodWithRetry -Uri ([string]$PageData.'@id')
                        }
                        foreach ($RegistrationLeaf in @($PageData.items)) {
                            if ([string]$RegistrationLeaf.catalogEntry.version -eq $PythonVersion) {
                                $LeafCatalog = $RegistrationLeaf.catalogEntry
                                if ($LeafCatalog -is [string]) {
                                    $CatalogEntry = Invoke-RestMethodWithRetry -Uri $LeafCatalog
                                } else {
                                    $CatalogEntry = $LeafCatalog
                                }
                                break
                            }
                        }
                        if ($CatalogEntry -and $CatalogEntry.packageHash) { break }
                    }
                }
                if (-not $CatalogEntry -or -not $CatalogEntry.packageHash) {
                    throw 'NuGet registration/catalog metadata did not include the package hash for the requested version.'
                }
                $HashAlgorithm = [string]$CatalogEntry.packageHashAlgorithm
                $CatalogHash = [string]$CatalogEntry.packageHash
                if ($HashAlgorithm -and $HashAlgorithm.ToUpperInvariant() -ne 'SHA512') {
                    throw ('Unexpected NuGet package hash algorithm: ' + $HashAlgorithm)
                }
                if ($CatalogHash -notmatch '^[A-Za-z0-9+/]{80,88}={0,2}$') {
                    throw 'NuGet catalog response did not contain a valid SHA-512 packageHash.'
                }
                $ExpectedHash = $CatalogHash
                [System.IO.File]::WriteAllText($HashPath, $ExpectedHash + "`r`n", [System.Text.Encoding]::ASCII)
                Write-Host 'Package SHA-512 obtained from the official NuGet catalog.' -ForegroundColor Green
            } catch {
                throw ('Could not obtain the official NuGet SHA-512 checksum from either endpoint. ' + $_.Exception.Message)
            }
        }

        $Sha = [System.Security.Cryptography.SHA512]::Create()
        try {
            $PackageBytes = [System.IO.File]::ReadAllBytes($PackagePath)
            $ActualHash = [Convert]::ToBase64String($Sha.ComputeHash($PackageBytes))
        } finally {
            $Sha.Dispose()
        }
        if ($ActualHash -cne $ExpectedHash) {
            Write-Host 'Cached/downloaded NuGet package failed SHA-512 verification. Re-downloading once...' -ForegroundColor Yellow
            Remove-Item -LiteralPath $PackagePath -Force -ErrorAction SilentlyContinue
            Invoke-DownloadWithRetry -Uri $PackageUrl -Destination $PackagePath -MinimumBytes 10000000 -Attempts 3
            $Sha = [System.Security.Cryptography.SHA512]::Create()
            try {
                $PackageBytes = [System.IO.File]::ReadAllBytes($PackagePath)
                $ActualHash = [Convert]::ToBase64String($Sha.ComputeHash($PackageBytes))
            } finally {
                $Sha.Dispose()
            }
            if ($ActualHash -cne $ExpectedHash) {
                Remove-Item -LiteralPath $PackagePath -Force -ErrorAction SilentlyContinue
                Remove-Item -LiteralPath $HashPath -Force -ErrorAction SilentlyContinue
                throw 'Python NuGet package SHA-512 mismatch after automatic re-download. The file was deleted to avoid using a damaged or untrusted package.'
            }
        }
        Write-Host 'NuGet package SHA-512 verified.' -ForegroundColor Green

        # A .nupkg is a ZIP archive, but Windows PowerShell Expand-Archive rejects
        # it solely because its extension is not .zip. Extract by content with
        # .NET ZipFile instead; do not rename/copy the 14+ MB package.
        try {
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            New-Item -ItemType Directory -Path $ExtractDir -Force | Out-Null
            $ZipCheck = [System.IO.Compression.ZipFile]::OpenRead($PackagePath)
            try {
                if ($ZipCheck.Entries.Count -eq 0) { throw 'The NuGet archive contains no entries.' }
                $PythonEntry = $ZipCheck.Entries | Where-Object { $_.FullName -ieq 'tools/python.exe' } | Select-Object -First 1
                if (-not $PythonEntry) { throw 'The official NuGet archive does not contain tools/python.exe.' }
            } finally {
                $ZipCheck.Dispose()
            }
            [System.IO.Compression.ZipFile]::ExtractToDirectory($PackagePath, $ExtractDir)
        } catch {
            throw ('SHA-512 verified, but extracting the official NuGet ZIP failed. ' + $_.Exception.Message)
        }
        if (-not (Test-Path -LiteralPath (Join-Path $PackageTools 'python.exe'))) {
            throw 'The verified Python NuGet package does not contain tools\python.exe.'
        }

        New-Item -ItemType Directory -Path $PythonHome -Force | Out-Null
        Copy-Item -Path (Join-Path $PackageTools '*') -Destination $PythonHome -Recurse -Force
        if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'python.exe was not found after extracting the official NuGet package.' }

        # Some Python packages ship a restrictive _pth file. If present, add site-packages
        # and enable site initialization; otherwise keep NuGet's standard search paths.
        $PthFiles = @(Get-ChildItem -LiteralPath $PythonHome -File -Filter '*._pth' -ErrorAction SilentlyContinue)
        foreach ($Pth in $PthFiles) {
            $PthText = [System.IO.File]::ReadAllText($Pth.FullName)
            $PthText = [regex]::Replace($PthText, '(?m)^[ \t]*#[ \t]*import[ \t]+site[ \t]*$', 'import site')
            if ($PthText -notmatch '(?m)^[ \t]*Lib[\\/]site-packages[ \t]*$') {
                $PthText = [regex]::Replace($PthText, '(?m)^\.[ \t]*$', ".`r`nLib\site-packages")
            }
            if ($PthText -notmatch '(?m)^[ \t]*import[ \t]+site[ \t]*$') {
                $PthText = $PthText.TrimEnd() + "`r`nimport site`r`n"
            }
            [System.IO.File]::WriteAllText($Pth.FullName, $PthText, [System.Text.Encoding]::ASCII)
        }

        & $PythonExe -c "import sys,struct,sysconfig; print('Private Python:',sys.version.split()[0]); print('Executable:',sys.executable); print('Architecture:',struct.calcsize('P')*8,'bit'); print('Package path:',sysconfig.get_path('purelib')); sys.exit(0 if sys.version_info[:3] == (3,13,17) and struct.calcsize('P') == 8 else 1)"
        if ($LASTEXITCODE -ne 0) { throw 'The extracted Python NuGet runtime failed its version/architecture check.' }
        Set-Content -LiteralPath $Marker -Value @(
            'NOP private build runtime',
            ('Python ' + $PythonVersion + ' x64 NuGet build package'),
            ('Package: ' + $PackageUrl),
            ('Checksum: ' + $HashUrl)
        ) -Encoding ASCII
    } else {
        Write-Host 'A valid private Python 3.13 x64 NuGet runtime already exists; reusing it.' -ForegroundColor Green
    }

    $SecurePipBootstrap = Join-Path $Root 'bootstrap_secure_pip.py'
    if (-not (Test-Path -LiteralPath $SecurePipBootstrap -PathType Leaf)) {
        throw 'Missing bootstrap_secure_pip.py. Extract the complete updated BuildKit.'
    }
    Write-Host 'Installing pip 26.2.2 from a pre-pinned wheel; no network access is delegated to the old pip...'
    & $PythonExe -I $SecurePipBootstrap
    if ($LASTEXITCODE -ne 0) { throw 'Hash-pinned pip bootstrap failed.' }
    & $PythonExe -I -c "import pip,sys;print('Pinned pip:',pip.__version__);sys.exit(0 if pip.__version__ == '26.2.2' else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'The private Python runtime does not contain the required pinned pip 26.2.2.' }
    Write-Host "Private Python is ready: $PythonExe" -ForegroundColor Green
} catch {
    Write-Host ''
    Write-Host ('ERROR preparing private Python: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
