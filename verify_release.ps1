$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectDir
try {
    python -m py_compile work_countdown.py work_core.py holiday_sync.py work_stats.py app_updates.py
    if ($LASTEXITCODE -ne 0) { throw "Python compile check failed." }

    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Unit tests failed." }

    & (Join-Path $projectDir "test_update_helper.ps1")

    ruff check work_core.py holiday_sync.py work_stats.py app_updates.py work_countdown.py tests
    if ($LASTEXITCODE -ne 0) { throw "Ruff check failed." }

    mypy work_core.py holiday_sync.py work_stats.py app_updates.py
    if ($LASTEXITCODE -ne 0) { throw "Mypy check failed." }

    if (Test-Path -LiteralPath "dist") {
        .\smoke_exe.ps1
    }
    if (Test-Path -LiteralPath "dist\SHA256SUMS.txt") {
        $hashLines = Get-Content -LiteralPath "dist\SHA256SUMS.txt" | Where-Object { $_ -match "^([0-9a-fA-F]{64})\s+(.+)$" }
        foreach ($line in $hashLines) {
            $parts = $line -split "\s+", 2
            $asset = Join-Path "dist" $parts[1]
            if (-not (Test-Path -LiteralPath $asset)) {
                $asset = Join-Path "installer" $parts[1]
            }
            if (-not (Test-Path -LiteralPath $asset)) { throw "Checksum asset missing: $($parts[1])" }
            $actual = (Get-FileHash -LiteralPath $asset -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $parts[0].ToLowerInvariant()) { throw "Checksum mismatch: $asset" }
        }
    }

    Write-Host "Release verification passed."
} finally {
    Pop-Location
}
