$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $projectDir "work_countdown.py"
$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Work Countdown.lnk"

$pythonCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
}

if (-not $pythonCommand) {
    throw "Python was not found in PATH. Install Python first, or add it to PATH."
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonCommand.Source
$shortcut.Arguments = "`"$scriptPath`""
$shortcut.WorkingDirectory = $projectDir
$shortcut.WindowStyle = 7
$shortcut.Description = "Work Countdown desktop widget"
$shortcut.Save()

Write-Host "Installed startup shortcut:"
Write-Host $shortcutPath
