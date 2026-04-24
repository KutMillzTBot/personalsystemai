$ErrorActionPreference = "SilentlyContinue"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match '^cloudflared(\.exe)?$' -and
        $_.CommandLine -and
        (
            $_.CommandLine -like "*127.0.0.1:5050*" -or
            $_.CommandLine -like "*127.0.0.1:8080*" -or
            $_.CommandLine -like "*cloudflared-permanent-bridge*" -or
            $_.CommandLine -like "*cloudflared-permanent-ui*" -or
            $_.CommandLine -like "*cloudflared-quick-bridge*" -or
            $_.CommandLine -like "*cloudflared-quick-ui*"
        )
    } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
    }

Write-Host "Cloudflare phone-access tunnels stopped." -ForegroundColor Yellow
