$ErrorActionPreference = "Stop"

$desktopDir = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopDir "班时钟.lnk"

if (Test-Path $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath
    Write-Host "已删除桌面快捷方式："
    Write-Host $shortcutPath
} else {
    Write-Host "未找到桌面快捷方式："
    Write-Host $shortcutPath
}
