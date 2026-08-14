param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Package,
    [Parameter(Mandatory = $true)][int]$ProcessId,
    [Parameter(Mandatory = $true)][string]$Backup
)

$ErrorActionPreference = "Stop"

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { break }
    Start-Sleep -Milliseconds 500
}

if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
    throw "The old BanClock process did not exit in time."
}

$hadTarget = Test-Path -LiteralPath $Target
if ($hadTarget) {
    Copy-Item -LiteralPath $Target -Destination $Backup -Force
}

try {
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            Move-Item -LiteralPath $Package -Destination $Target -Force
            break
        } catch {
            if ($attempt -eq 19) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
    Start-Process -FilePath $Target -WorkingDirectory (Split-Path -Parent $Target)
} catch {
    if ($hadTarget -and (Test-Path -LiteralPath $Backup)) {
        Copy-Item -LiteralPath $Backup -Destination $Target -Force
    }
    throw
}
