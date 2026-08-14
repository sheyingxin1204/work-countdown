$ErrorActionPreference = "Stop"

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "班时钟.lnk"

if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath
    Write-Host "Removed startup shortcut:"
    Write-Host $shortcutPath
} else {
    Write-Host "Startup shortcut was not found:"
    Write-Host $shortcutPath
}
