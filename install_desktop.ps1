$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$exePath = Join-Path $projectDir "dist\班时钟.exe"
$scriptPath = Join-Path $projectDir "work_countdown.py"
$desktopDir = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopDir "班时钟.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.WorkingDirectory = $projectDir
$shortcut.WindowStyle = 7
$shortcut.Description = "班时钟桌面倒计时"

if (Test-Path $exePath) {
    $shortcut.TargetPath = $exePath
    $shortcut.Arguments = ""
} else {
    $pythonCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    }
    if (-not $pythonCommand) {
        throw "dist\班时钟.exe 未找到，且 PATH 中没有 Python。请先构建 EXE 或安装 Python。"
    }
    $shortcut.TargetPath = $pythonCommand.Source
    $shortcut.Arguments = '"' + $scriptPath + '"'
}

$shortcut.Save()
Write-Host "已创建桌面快捷方式："
Write-Host $shortcutPath
