param(
    [string[]] $Path = @("dist\*.exe", "installer\BanClock-Setup-*.exe"),
    [string] $CertificatePath = $env:BAN_CLOCK_CERT,
    [string] $CertificatePassword = $env:BAN_CLOCK_CERT_PASSWORD,
    [string] $TimestampUrl = $(if ($env:BAN_CLOCK_TIMESTAMP_URL) { $env:BAN_CLOCK_TIMESTAMP_URL } else { "http://timestamp.digicert.com" })
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$resolvedAssets = @(
    foreach ($pattern in $Path) {
        $candidate = if ([System.IO.Path]::IsPathRooted($pattern)) { $pattern } else { Join-Path $projectDir $pattern }
        Get-ChildItem -Path $candidate -File -ErrorAction SilentlyContinue
    }
) | Sort-Object FullName -Unique

if (-not $resolvedAssets) {
    throw "No release EXE assets were found. Build the EXE and installer first."
}

if (-not $CertificatePath) {
    Write-Warning "BAN_CLOCK_CERT is not set; signing is prepared but skipped."
    Write-Host "Assets ready for signing: $($resolvedAssets.FullName -join ', ')"
    exit 0
}

if (-not (Test-Path -LiteralPath $CertificatePath)) {
    throw "Signing certificate was not found: $CertificatePath"
}

$signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $signtool) {
    $sdkRoots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "${env:ProgramFiles}\Windows Kits\10\bin"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $signtool = Get-ChildItem -Path $sdkRoots -Filter signtool.exe -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $signtool) {
    throw "signtool.exe was not found. Install the Windows SDK or add signtool.exe to PATH."
}

foreach ($asset in $resolvedAssets) {
    $arguments = @("sign", "/fd", "SHA256", "/f", $CertificatePath, "/tr", $TimestampUrl, "/td", "SHA256")
    if ($CertificatePassword) {
        $arguments += @("/p", $CertificatePassword)
    }
    $arguments += $asset.FullName
    & $signtool @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "signtool failed for $($asset.FullName)."
    }
}

Write-Host "Signed $($resolvedAssets.Count) release asset(s)."
