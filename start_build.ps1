param()
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$SourceRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$Workspace = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'NOPBK\R12'
if ($env:NOP_BUILD_WORKSPACE) { $Workspace = [IO.Path]::GetFullPath($env:NOP_BUILD_WORKSPACE) }
if ($Workspace.Length -gt 110) { throw 'NOP_BUILD_WORKSPACE must be a short local path (at most 110 characters).' }
$NativeSystem = Join-Path $env:SystemRoot 'System32'
if (-not [Environment]::Is64BitProcess -and [Environment]::Is64BitOperatingSystem) { $NativeSystem = Join-Path $env:SystemRoot 'Sysnative' }
$PowerShellExe = Join-Path $NativeSystem 'WindowsPowerShell\v1.0\powershell.exe'
$Robocopy = Join-Path $NativeSystem 'robocopy.exe'
$Lock = $null
$Code = 1
function Copy-Tree([string]$From, [string]$To, [string[]]$Options) {
    if (-not (Test-Path -LiteralPath $From -PathType Container)) { return }
    New-Item -ItemType Directory -Path $To -Force | Out-Null
    $CopyArgs = @($From, $To, '/E', '/COPY:DAT', '/DCOPY:T', '/R:1', '/W:1', '/XJ', '/NFL', '/NDL', '/NP', '/NJH', '/NJS') + $Options
    & $Robocopy @CopyArgs
    if ($LASTEXITCODE -ge 8) { throw "File copy failed (robocopy $LASTEXITCODE): $From -> $To" }
}
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    if ($PSVersionTable.PSVersion -lt [version]'5.1') { throw 'Windows PowerShell 5.1 is required.' }
    if (-not (Test-Path -LiteralPath $Robocopy)) { throw "Windows robocopy is missing: $Robocopy" }
    if ($Workspace.StartsWith('\\')) { throw 'The build workspace must be on a local drive.' }
    if ($Workspace.TrimEnd('\').StartsWith($SourceRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'The build workspace must not be inside the source folder.' }
    New-Item -ItemType Directory -Path $Workspace -Force | Out-Null
    $Lock = [IO.File]::Open((Join-Path $Workspace '.workspace.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    Write-Host "NOP R12.2 Compact. Persistent build workspace: $Workspace"
    if ($SourceRoot.TrimEnd('\') -ne $Workspace.TrimEnd('\')) {
        $Excluded = @('.build-python', 'runtime_deps', 'build', 'dist', 'release', 'logs', '.build-tools\converter-downloads', '.build-tools\media-downloads') | ForEach-Object { Join-Path $SourceRoot $_ }
        Copy-Tree $SourceRoot $Workspace (@('/IS', '/IT', '/XD') + $Excluded + @('/XF', '.build.lock', '.workspace.lock', 'converter-sources.lock.json'))
        foreach ($RelativeCache in @('.build-tools\converter-downloads', '.build-tools\media-downloads')) {
            Copy-Tree (Join-Path $SourceRoot $RelativeCache) (Join-Path $Workspace $RelativeCache) @('/XC', '/XN', '/XO')
        }
        Copy-Tree (Join-Path $SourceRoot 'runtime_deps\installers') (Join-Path $Workspace 'runtime_deps\installers') @('/IS', '/IT')
        # Import already downloaded R11/R12 payloads without replacing current files.
        # Only this kit, its siblings and their direct BuildKit children are inspected.
        $Candidates = New-Object 'System.Collections.Generic.List[string]'
        $Candidates.Add($SourceRoot)
        $Parent = Split-Path -Parent $SourceRoot
        $Grandparent = Split-Path -Parent $Parent
        foreach ($Base in @($Parent, $Grandparent) | Select-Object -Unique) {
            foreach ($Dir in @(Get-ChildItem -LiteralPath $Base -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'NOP*' -and -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) } | Select-Object -First 30)) {
                $Candidates.Add($Dir.FullName)
                foreach ($Child in @(Get-ChildItem -LiteralPath $Dir.FullName -Directory -Filter 'NOP_BuildKit*' -ErrorAction SilentlyContinue | Select-Object -First 10)) { $Candidates.Add($Child.FullName) }
            }
        }
        foreach ($Candidate in @($Candidates | Select-Object -Unique)) {
            if ($Candidate.TrimEnd('\') -eq $Workspace.TrimEnd('\')) { continue }
            # Optional SDK ZIPs may have been extracted to separate sibling folders.
            # Their inner NOP_BuildKit folder contains cache data, without build scripts.
            Copy-Tree (Join-Path $Candidate '.build-tools\converter-downloads') (Join-Path $Workspace '.build-tools\converter-downloads') @('/XC', '/XN', '/XO')
            if (-not (Test-Path -LiteralPath (Join-Path $Candidate 'prepare_runtime.py'))) { continue }
            foreach ($Relative in @('.build-python', 'runtime_deps', '.build-tools\converter-downloads', '.build-tools\media-downloads', '.build-tools\downloads')) {
                Copy-Tree (Join-Path $Candidate $Relative) (Join-Path $Workspace $Relative) @('/XC', '/XN', '/XO')
            }
            # Older kits also cache archives directly under .build-tools.
            $OldTools = Join-Path $Candidate '.build-tools'
            if (Test-Path -LiteralPath $OldTools) {
                & $Robocopy $OldTools (Join-Path $Workspace '.build-tools') '*.zip' '*.7z' '*.nupkg' '*.sha512' '*.exe' '/XC' '/XN' '/XO' '/R:1' '/W:1' '/NFL' '/NDL' '/NP' '/NJH' '/NJS'
                if ($LASTEXITCODE -ge 8) { throw "Cannot import cached downloads from $OldTools" }
            }
        }
    }
    $env:NOP_OUTPUT_ROOT = $SourceRoot
    & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Workspace 'build.ps1')
    $Code = $LASTEXITCODE
    if ($Code -eq 0 -and $SourceRoot.TrimEnd('\') -ne $Workspace.TrimEnd('\')) {
        Copy-Tree (Join-Path $Workspace 'release') (Join-Path $SourceRoot 'release') @('/XD', (Join-Path $Workspace 'release\staging'))
    }
} catch {
    $Code = 1
    Write-Host ('BUILD FAILED: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host "Retained workspace and caches: $Workspace"
} finally {
    if (Test-Path -LiteralPath (Join-Path $Workspace 'logs')) {
        try { if ($SourceRoot.TrimEnd('\') -ne $Workspace.TrimEnd('\')) { Copy-Tree (Join-Path $Workspace 'logs') (Join-Path $SourceRoot 'logs') @() } } catch { Write-Host ('Logs remain in ' + (Join-Path $Workspace 'logs')) }
    }
    if ($null -ne $Lock) { $Lock.Dispose() }
}
exit $Code
