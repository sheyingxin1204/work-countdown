$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $projectDir "dist"
$scriptPath = Join-Path $projectDir "installer.iss"
$exePath = Get-ChildItem -LiteralPath $distDir -Filter "*.exe" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName

if (-not $exePath) {
    throw "No EXE was found in dist. Run build_exe.ps1 first."
}

$isccCandidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$isccCandidates = @($isccCandidates)

if (-not $isccCandidates) {
    throw "Inno Setup 6 ISCC.exe was not found."
}

Push-Location $projectDir
try {
    & $isccCandidates[0] $scriptPath
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed."
    }
    Write-Host "Installer generated in $projectDir\installer"
} finally {
    Pop-Location
}
