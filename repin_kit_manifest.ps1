# Re-pins SHA-256 hashes in kit-manifest.json for files you changed on purpose
# (for example NOP_1.0.py). Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File .\repin_kit_manifest.ps1
$ErrorActionPreference = 'Stop'
$root = (Get-Location).Path
$mp = Join-Path $root 'kit-manifest.json'
if (-not (Test-Path -LiteralPath $mp)) { throw 'kit-manifest.json not found. Run this from the repository root.' }
$enc = New-Object System.Text.UTF8Encoding($false)
$text = [System.IO.File]::ReadAllText($mp, $enc)
$files = ($text | ConvertFrom-Json).files
$changed = 0
$missing = 0
foreach ($prop in $files.PSObject.Properties) {
    $rel = $prop.Name
    $path = Join-Path $root ($rel -replace '/', '\')
    if (-not (Test-Path -LiteralPath $path)) { Write-Host "MISSING: $rel"; $missing++; continue }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $prop.Value) {
        $oldEntry = '"' + $rel + '": "' + $prop.Value + '"'
        $newEntry = '"' + $rel + '": "' + $hash + '"'
        if (-not $text.Contains($oldEntry)) { throw "Cannot find the manifest entry for $rel" }
        $text = $text.Replace($oldEntry, $newEntry)
        Write-Host "re-pinned: $rel"
        $changed++
    }
}
if ($changed -gt 0) { [System.IO.File]::WriteAllText($mp, $text, $enc) }
Write-Host "Done. Re-pinned: $changed, missing: $missing"
