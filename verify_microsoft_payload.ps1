param([Parameter(Mandatory=$true)][string]$Payload)
$ErrorActionPreference = 'Stop'
try {
    $Signature = Get-AuthenticodeSignature -LiteralPath $Payload
    if ($Signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw 'Visual C++ Redistributable has no valid Authenticode signature.'
    }
    if (-not $Signature.SignerCertificate -or $Signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        throw 'The runtime installer is not signed by Microsoft Corporation.'
    }
    $Info = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($Payload)
    Write-Output ('{0}.{1}.{2}.{3}' -f $Info.FileMajorPart,$Info.FileMinorPart,$Info.FileBuildPart,$Info.FilePrivatePart)
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
