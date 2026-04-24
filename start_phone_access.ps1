$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$RuntimeDir = Join-Path $RepoRoot ".runtime"
$LogDir = Join-Path $RuntimeDir "logs"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Read-DotEnv {
    param([string]$Path)
    $map = @{}
    if (!(Test-Path $Path)) { return $map }
    foreach ($line in Get-Content $Path) {
        $trim = $line.Trim()
        if (-not $trim -or $trim.StartsWith("#")) { continue }
        $parts = $trim -split "=", 2
        if ($parts.Count -eq 2) {
            $map[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
    return $map
}

function Stop-CloudflaredManaged {
    param([string]$Pattern)
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -match '^cloudflared(\.exe)?$' -and
            $_.CommandLine -and
            $_.CommandLine -like "*$Pattern*"
        } |
        ForEach-Object {
            try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
        }
}

function Start-CloudflaredManaged {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [string]$Pattern,
        [string]$LogPrefix
    )

    Stop-CloudflaredManaged -Pattern $Pattern

    $stdoutLog = Join-Path $LogDir "$LogPrefix.out.log"
    $stderrLog = Join-Path $LogDir "$LogPrefix.err.log"
    if (Test-Path $stdoutLog) { Remove-Item $stdoutLog -Force }
    if (Test-Path $stderrLog) { Remove-Item $stderrLog -Force }

    $proc = Start-Process `
        -FilePath "C:\Program Files (x86)\cloudflared\cloudflared.exe" `
        -ArgumentList $Arguments `
        -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden `
        -PassThru

    Set-Content -Path (Join-Path $RuntimeDir "$Name.pid") -Value $proc.Id
    Write-Host "$Name tunnel started (PID $($proc.Id))" -ForegroundColor Green
}

$envMap = Read-DotEnv -Path (Join-Path $RepoRoot ".env")
$bridgeToken = $envMap["CLOUDFLARE_TUNNEL_BRIDGE_TOKEN"]
$uiToken = $envMap["CLOUDFLARE_TUNNEL_UI_TOKEN"]
$publicBridge = $envMap["CLOUDFLARE_PUBLIC_BRIDGE_URL"]
$publicUi = $envMap["CLOUDFLARE_PUBLIC_UI_URL"]

if ($bridgeToken) {
    Start-CloudflaredManaged `
        -Name "cloudflare-bridge" `
        -Pattern "--token $bridgeToken" `
        -LogPrefix "cloudflared-permanent-bridge" `
        -Arguments @("tunnel", "run", "--token", $bridgeToken)
    Write-Host "Bridge tunnel mode: permanent" -ForegroundColor Cyan
    if ($publicBridge) { Write-Host "Bridge URL: $publicBridge" -ForegroundColor Cyan }
} else {
    Start-CloudflaredManaged `
        -Name "cloudflare-bridge" `
        -Pattern "--url http://127.0.0.1:5050" `
        -LogPrefix "cloudflared-quick-bridge" `
        -Arguments @("tunnel", "--url", "http://127.0.0.1:5050")
    Write-Host "Bridge tunnel mode: quick" -ForegroundColor Yellow
}

if ($uiToken) {
    Start-CloudflaredManaged `
        -Name "cloudflare-ui" `
        -Pattern "--token $uiToken" `
        -LogPrefix "cloudflared-permanent-ui" `
        -Arguments @("tunnel", "run", "--token", $uiToken)
    Write-Host "UI tunnel mode: permanent" -ForegroundColor Cyan
    if ($publicUi) { Write-Host "UI URL: $publicUi" -ForegroundColor Cyan }
} else {
    Start-CloudflaredManaged `
        -Name "cloudflare-ui" `
        -Pattern "--url http://127.0.0.1:8080" `
        -LogPrefix "cloudflared-quick-ui" `
        -Arguments @("tunnel", "--url", "http://127.0.0.1:8080")
    Write-Host "UI tunnel mode: quick" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Logs folder: $LogDir" -ForegroundColor DarkCyan
Write-Host "If tokens are empty, Cloudflare quick tunnel URLs will appear inside the *.err.log files." -ForegroundColor DarkYellow
