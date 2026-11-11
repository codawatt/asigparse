<#
.SYNOPSIS
Copy the OneOCR engine files from YOUR OWN installed Windows Snipping Tool into
backend/vendor/oneocr (gitignored). Nothing is downloaded; the files are not
redistributed with this repository.
#>
$ErrorActionPreference = 'Stop'
$package = Get-AppxPackage Microsoft.ScreenSketch
if (-not $package) { throw 'Snipping Tool (Microsoft.ScreenSketch) is not installed. Install/update it from Microsoft Store.' }
$source = Join-Path $package.InstallLocation 'SnippingTool'
$destination = Join-Path $PSScriptRoot '..\vendor\oneocr'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($name in 'oneocr.dll', 'oneocr.onemodel', 'onnxruntime.dll') {
    $file = Join-Path $source $name
    if (-not (Test-Path -LiteralPath $file)) { throw "$name not found in $source (Snipping Tool too old?)" }
    Copy-Item -LiteralPath $file -Destination $destination -Force
}
foreach ($dll in 'oneocr.dll', 'onnxruntime.dll') {
    $sig = Get-AuthenticodeSignature (Join-Path $destination $dll)
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike '*O=Microsoft Corporation*') {
        throw "$dll is not validly signed by Microsoft (status: $($sig.Status))"
    }
}
Set-Content -Path (Join-Path $destination 'SOURCE.txt') -Encoding utf8 -Value "Copied from Snipping Tool $($package.Version) ($($package.Architecture)) on $(Get-Date -Format s)"
Write-Host "OneOCR files copied from Snipping Tool $($package.Version) to $((Resolve-Path $destination).Path)"
