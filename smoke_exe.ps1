$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $projectDir "dist"
$exePath = Get-ChildItem -LiteralPath $distDir -Filter "*.exe" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $exePath) {
    throw "dist\BanClock executable was not found."
}

$process = Start-Process -FilePath $exePath -WorkingDirectory $projectDir -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 4
$running = -not $process.HasExited
if ($running) {
    Stop-Process -Id $process.Id -Force
    Start-Sleep -Milliseconds 500
    Get-Process | Where-Object { $_.Path -eq $exePath } | Stop-Process -Force -ErrorAction SilentlyContinue
}
if (-not $running -and $process.ExitCode -ne 0) {
    throw "Packaged executable exited with code $($process.ExitCode)."
}
Write-Host "Packaged smoke test passed. Running after 4s: $running"
