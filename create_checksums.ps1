$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $projectDir "dist"
$outputPath = Join-Path $distDir "SHA256SUMS.txt"
$assets = Get-ChildItem -LiteralPath $distDir -Filter "*.exe" -File | Sort-Object Name
if (-not $assets) {
    throw "No EXE assets were found in dist."
}

$lines = foreach ($asset in $assets) {
    $hash = (Get-FileHash -LiteralPath $asset.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($asset.Name)"
}
$lines | Set-Content -LiteralPath $outputPath -Encoding ASCII
Write-Host "Wrote $outputPath"
