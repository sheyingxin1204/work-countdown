$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $projectDir "work_countdown.py"

$pythonCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
}

if (-not $pythonCommand) {
    throw "Python was not found in PATH. Install Python first, or add it to PATH."
}

Start-Process -FilePath $pythonCommand.Source -ArgumentList "`"$scriptPath`"" -WorkingDirectory $projectDir -WindowStyle Hidden
