param(
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $root "runtime\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-ListenPort {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-HttpOk {
    param([string]$Url)
    for ($i = 0; $i -lt 30; $i++) {
        try {
            if ((Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) {
                return $true
            }
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
    throw "Node.js was not found. Install Node.js 22 before running the offline demo."
}

$vite = Join-Path $root "frontend\node_modules\vite\bin\vite.js"
if (-not (Test-Path $vite)) {
    throw "Frontend dependencies are missing. Run pnpm install in the frontend directory."
}

if (-not (Test-ListenPort 5173)) {
    Start-Process -FilePath $node `
        -ArgumentList @($vite, "--host", "127.0.0.1", "--port", "5173") `
        -WorkingDirectory (Join-Path $root "frontend") `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "frontend.out.log") `
        -RedirectStandardError (Join-Path $logDir "frontend.err.log") | Out-Null
}

$url = "http://127.0.0.1:5173/login"
if (-not (Wait-HttpOk "http://127.0.0.1:5173/api/health")) {
    throw "The offline platform did not become healthy. Check runtime\logs."
}

Write-Host ""
Write-Host "HiddenChain offline demo is ready." -ForegroundColor Green
Write-Host "Open: $url" -ForegroundColor Cyan
Write-Host "User: exchange"
Write-Host "Pass: exchange123"
Write-Host "No public server or internet connection is required after dependencies are installed."

if ($OpenBrowser) {
    Start-Process $url
}
