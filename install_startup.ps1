$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $projectDir "work_countdown.py"
$exePath = Join-Path $projectDir "dist\班时钟.exe"
$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "班时钟.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.Arguments = ""

if (Test-Path $exePath) {
    $shortcut.TargetPath = $exePath
} else {
    $pythonCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    }

    if (-not $pythonCommand) {
        throw "Ban Clock.exe was not found, and Python was not found in PATH."
    }

    $shortcut.TargetPath = $pythonCommand.Source
    $shortcut.Arguments = '"' + $scriptPath + '"'
}

$shortcut.WorkingDirectory = $projectDir
$shortcut.WindowStyle = 7
$shortcut.Description = "Ban Clock desktop countdown"
$shortcut.Save()

Write-Host "Installed startup shortcut:"
Write-Host $shortcutPath
