$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("ban-clock-update-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDir | Out-Null
try {
    $target = Join-Path $tempDir "fake.exe"
    $package = Join-Path $tempDir "package.exe"
    $backup = Join-Path $tempDir "fake.exe.previous"
    Set-Content -LiteralPath $target -Value "old" -Encoding ASCII
    Set-Content -LiteralPath $package -Value "not an executable" -Encoding ASCII

    $helperError = $null
    try {
        & (Join-Path $projectDir "update_helper.ps1") `
            -Target $target -Package $package -ProcessId 999999 -Backup $backup
    } catch {
        $helperError = $_
    }
    if (-not $helperError) {
        throw "The helper unexpectedly accepted an invalid executable."
    }
    if ((Get-Content -LiteralPath $target -Raw).Trim() -ne "old") {
        throw "Rollback did not restore the original target."
    }
    Write-Host "Update-helper rollback test passed."
} finally {
    Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

