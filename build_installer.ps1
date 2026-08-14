$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$exePath = Join-Path $projectDir "dist\班时钟.exe"
$scriptPath = Join-Path $projectDir "installer.iss"

if (-not (Test-Path -LiteralPath $exePath)) {
    throw "未找到 dist\班时钟.exe，请先运行 build_exe.ps1。"
}

$isccCandidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

if (-not $isccCandidates) {
    throw "未找到 Inno Setup 6 的 ISCC.exe，请安装 Inno Setup 后重试。"
}

Push-Location $projectDir
try {
    & $isccCandidates[0] $scriptPath
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup 构建失败。"
    }
    Write-Host "安装器已生成到 $projectDir\installer"
} finally {
    Pop-Location
}
