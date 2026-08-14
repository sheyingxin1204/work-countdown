$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectDir
try {
    $existingExe = Get-ChildItem -LiteralPath (Join-Path $projectDir "dist") -Filter "*.exe" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($existingExe) {
        $running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -eq $existingExe.FullName }
        if ($running) {
            throw "Please close the existing Ban Clock.exe before building."
        }
    }

    $pyinstaller = python -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('PyInstaller') else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed. Run: python -m pip install -r requirements-build.txt"
    }

    python -m PyInstaller --clean --noconfirm ban_clock.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    # Keep an ASCII-named copy for GitHub Release assets and update discovery;
    # the installer still packages the Chinese display name below.
    $localizedExe = Get-ChildItem -LiteralPath (Join-Path $projectDir "dist") -Filter "*.exe" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    $releaseExe = Join-Path $projectDir "dist\BanClock.exe"
    if (-not $localizedExe) {
        throw "PyInstaller did not produce an EXE in dist."
    }
    Copy-Item -LiteralPath $localizedExe -Destination $releaseExe -Force

    Write-Host "Built: $localizedExe"
}
finally {
    Pop-Location
}
