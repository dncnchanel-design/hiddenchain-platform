$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $root "runtime\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-ListenPort {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-HttpOk {
    param([string]$Url, [int]$Attempts = 30)
    for ($i = 0; $i -lt $Attempts; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return $true }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Test-PythonRuntime {
    param([string]$Candidate)
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate)) {
        return $false
    }
    & $Candidate -c "import ssl, fastapi, uvicorn" 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

$pythonCandidates = @(
    (Join-Path $root "backend\.venv\Scripts\python.exe"),
    (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$python = $pythonCandidates | Where-Object { Test-PythonRuntime $_ } | Select-Object -First 1
if (-not $python) {
    throw "No healthy Python runtime with FastAPI and uvicorn was found. Repair backend\.venv or install Python on PATH."
}

if (-not (Test-ListenPort 8000)) {
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory (Join-Path $root "backend") `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "backend.out.log") `
        -RedirectStandardError (Join-Path $logDir "backend.err.log") | Out-Null
}

$nodeCandidates = @(
    (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"),
    (Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
) | Where-Object { $_ -and (Test-Path $_) }
$node = $nodeCandidates | Select-Object -First 1
if (-not $node) {
    throw "Node.js was not found. Install Node.js 22 or run the project from Codex."
}

$vite = Join-Path $root "frontend\node_modules\vite\bin\vite.js"
if (-not (Test-Path $vite)) {
    throw "Frontend dependencies are missing. Run pnpm install in the frontend directory."
}

if (-not (Test-ListenPort 5173)) {
    Start-Process -FilePath $node `
        -ArgumentList @($vite, "--port", "5173") `
        -WorkingDirectory (Join-Path $root "frontend") `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "frontend.out.log") `
        -RedirectStandardError (Join-Path $logDir "frontend.err.log") | Out-Null
}

if (-not (Wait-HttpOk "http://127.0.0.1:5173/api/health")) {
    throw "The local platform did not become healthy. Check runtime\logs."
}

$cloudflaredCandidates = @(
    "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    "C:\Program Files\cloudflared\cloudflared.exe",
    (Get-Command cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
) | Where-Object { $_ -and (Test-Path $_) }
$cloudflared = $cloudflaredCandidates | Select-Object -First 1
if (-not $cloudflared) {
    throw "cloudflared was not found. Install it with: winget install --id Cloudflare.cloudflared -e"
}

$tunnelLog = Join-Path $logDir "tunnel.err.log"
$publicUrl = $null
$existingTunnel = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "cloudflared.exe" -and $_.CommandLine -match "127\.0\.0\.1:5173"
} | Select-Object -First 1

if ($existingTunnel -and (Test-Path $tunnelLog)) {
    $publicUrl = Select-String -Path $tunnelLog -Pattern "https://[-a-z0-9]+\.trycloudflare\.com" -AllMatches |
        ForEach-Object { $_.Matches.Value } | Select-Object -First 1
    if ($publicUrl -and -not (Wait-HttpOk "$publicUrl/login" 3)) {
        Stop-Process -Id $existingTunnel.ProcessId -Force
        $publicUrl = $null
    }
}

if (-not $publicUrl) {
    Set-Content -Path $tunnelLog -Value "" -Encoding utf8
    Start-Process -FilePath $cloudflared `
        -ArgumentList @("tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:5173") `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "tunnel.out.log") `
        -RedirectStandardError $tunnelLog | Out-Null

    for ($i = 0; $i -lt 30 -and -not $publicUrl; $i++) {
        Start-Sleep -Seconds 1
        $publicUrl = Select-String -Path $tunnelLog -Pattern "https://[-a-z0-9]+\.trycloudflare\.com" -AllMatches -ErrorAction SilentlyContinue |
            ForEach-Object { $_.Matches.Value } | Select-Object -First 1
    }
}

if (-not $publicUrl -or -not (Wait-HttpOk "$publicUrl/login" 20)) {
    throw "The public tunnel did not become reachable. Check runtime\logs\tunnel.err.log."
}

$lanIp = Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown"
} | Sort-Object InterfaceMetric | Select-Object -First 1 -ExpandProperty IPAddress

$info = @(
    "PUBLIC_URL=$publicUrl/login",
    "LOCAL_URL=http://127.0.0.1:5173/login",
    "LAN_URL=http://${lanIp}:5173/login",
    "DEMO_USER=exchange",
    "DEMO_PASSWORD=exchange123",
    "STARTED_AT=$(Get-Date -Format s)"
)
$info | Set-Content -Path (Join-Path $root "runtime\public-url.txt") -Encoding utf8

Write-Host ""
Write-Host "HiddenChain competition demo is ready." -ForegroundColor Green
Write-Host "Public: $publicUrl/login" -ForegroundColor Cyan
Write-Host "LAN:    http://${lanIp}:5173/login"
Write-Host "User:   exchange"
Write-Host "Pass:   exchange123"
Write-Host ""
Write-Host "Keep this computer powered on and prevent sleep while the public link is in use."
