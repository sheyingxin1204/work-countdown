$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectDir
try {
    $exePath = Join-Path $projectDir "dist\班时钟.exe"
    if (Test-Path $exePath) {
        $running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -eq $exePath }
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

    Write-Host "Built: $projectDir\dist\班时钟.exe"
}
finally {
    Pop-Location
}
