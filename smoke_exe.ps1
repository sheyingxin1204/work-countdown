$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$exePath = Join-Path $projectDir "dist\班时钟.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "未找到 dist\班时钟.exe。"
}

$process = Start-Process -FilePath $exePath -WorkingDirectory $projectDir -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 4
$running = -not $process.HasExited
if ($running) {
    Stop-Process -Id $process.Id -Force
}
if (-not $running -and $process.ExitCode -ne 0) {
    throw "打包后的 EXE 退出码为 $($process.ExitCode)。"
}
Write-Host "Packaged smoke test passed. Running after 4s: $running"
