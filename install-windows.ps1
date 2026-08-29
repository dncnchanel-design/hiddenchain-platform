#requires -Version 5.1

<#[
Windows Docker Compose installer for HiddenChain.

Demo mode creates a local-only environment file with fresh random signing
values, builds all service images, and starts the synthetic-data demo.
Production mode never generates or overwrites secrets; it requires a
manually prepared .env.production file.
]#>
[CmdletBinding()]
param(
    [ValidateSet("Demo", "Production")]
    [string]$Mode = "Demo",

    [ValidateSet("None", "DirectDomain", "Cloudflare")]
    [string]$Profile = "None",

    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$modeName = $Mode.ToLowerInvariant()
$projectName = "hiddenchain-windows"
$composeFile = if ($modeName -eq "demo") { "docker-compose.yml" } else { "docker-compose.production.yml" }
$composePath = Join-Path $root $composeFile

function Fail([string]$Message) {
    throw $Message
}

function New-RandomBase64([int]$Length) {
    $bytes = New-Object "System.Byte[]" $Length
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes)
}

function Ensure-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail "未找到 docker。请先安装并启动 Docker Desktop。"
    }
    try {
        $dockerInfo = @(& docker info 2>&1)
        $dockerExit = $LASTEXITCODE
    } catch {
        $dockerExit = 1
    }
    if ($dockerExit -ne 0) {
        Fail "Docker 引擎未运行。请启动 Docker Desktop，并确认使用 WSL 2 后端。"
    }
    try {
        $composeVersion = @(& docker compose version 2>&1)
        $composeExit = $LASTEXITCODE
    } catch {
        $composeExit = 1
    }
    if ($composeExit -ne 0) {
        Fail "未找到 Docker Compose Plugin。请更新 Docker Desktop。"
    }
}

function Ensure-DemoEnv([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        return
    }
    $runtimeDir = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $lines = @(
        "JWT_SECRET=$(New-RandomBase64 48)",
        "SIGNING_SECRET=$(New-RandomBase64 48)",
        "PLATFORM_SIGNING_PRIVATE_KEY=$(New-RandomBase64 32)",
        "ELECTRICITY_CONNECTOR_SIGNING_PRIVATE_KEY=$(New-RandomBase64 32)",
        "COAL_CONNECTOR_SIGNING_PRIVATE_KEY=$(New-RandomBase64 32)",
        "HEAT_CONNECTOR_SIGNING_PRIVATE_KEY=$(New-RandomBase64 32)",
        "GAS_CONNECTOR_SIGNING_PRIVATE_KEY=$(New-RandomBase64 32)",
        "OIL_CONNECTOR_SIGNING_PRIVATE_KEY=$(New-RandomBase64 32)",
        "ELECTRICITY_RETAILER_CONNECTOR_SIGNING_PRIVATE_KEY=$(New-RandomBase64 32)",
        "ELECTRICITY_EXCHANGE_CONNECTOR_SIGNING_PRIVATE_KEY=$(New-RandomBase64 32)"
    )
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, ($lines -join [Environment]::NewLine), $utf8)
    Write-Host "已生成本地演示密钥：$Path" -ForegroundColor DarkGray
}

function Get-DeploymentSetting([string]$Path, [string]$Name) {
    $processValue = [Environment]::GetEnvironmentVariable(
        $Name,
        [EnvironmentVariableTarget]::Process
    )
    if ($null -ne $processValue) {
        return $processValue.Trim()
    }
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith("#")) {
            continue
        }
        $parts = $line -split "=", 2
        if ($parts.Count -ne 2 -or $parts[0].Trim() -ne $Name) {
            continue
        }
        $value = $parts[1].Trim()
        if (
            $value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        return $value.Trim()
    }
    return ""
}

function Require-ProfileSetting(
    [string]$Path,
    [string]$Name,
    [string]$ProfileName
) {
    $value = Get-DeploymentSetting $Path $Name
    $placeholder = $value -match '^replace[-_]' -or (
        $Name -eq "PUBLIC_DOMAIN" -and
        ($value -match '(^|\.)example\.(com|net|org)$' -or $value -match '^(localhost|127\.0\.0\.1)$')
    )
    if ([string]::IsNullOrWhiteSpace($value) -or $placeholder) {
        Fail "$ProfileName 模式需要在 .env.production 中设置有效的 $Name。"
    }
}

Ensure-Docker

if (-not (Test-Path -LiteralPath $composePath)) {
    Fail "找不到 Compose 文件：$composePath"
}

if ($modeName -eq "demo") {
    if ($Profile -ne "None") {
        Fail "Demo 模式不使用 Compose profile；请省略 -Profile。"
    }
    $envFile = Join-Path $root "runtime\windows-demo.env"
    Ensure-DemoEnv $envFile
} else {
    $envFile = Join-Path $root ".env.production"
    if (-not (Test-Path -LiteralPath $envFile)) {
        Fail "未找到 .env.production。请复制 production.env.example，填写生产配置后重试。"
    }
}

if ($Profile -eq "DirectDomain") {
    Require-ProfileSetting $envFile "PUBLIC_DOMAIN" "DirectDomain"
} elseif ($Profile -eq "Cloudflare") {
    Require-ProfileSetting $envFile "CLOUDFLARE_TUNNEL_TOKEN" "Cloudflare"
}

$composeOptions = @(
    "--project-directory", $root,
    "--project-name", $projectName,
    "--env-file", $envFile,
    "-f", $composePath
)
if ($Profile -ne "None") {
    $composeOptions = @("--profile", $Profile.ToLowerInvariant().Replace("directdomain", "direct-domain")) + $composeOptions
}

function Invoke-Compose([string[]]$Arguments) {
    & docker compose @composeOptions @Arguments
    if ($LASTEXITCODE -ne 0) {
        Fail "Docker Compose 执行失败（退出码 $LASTEXITCODE）。"
    }
}

Write-Host "检查 Compose 配置..." -ForegroundColor Cyan
Invoke-Compose @("config") | Out-Null

if ($NoStart) {
    Write-Host "仅构建镜像..." -ForegroundColor Cyan
    Invoke-Compose @("build")
    Write-Host "镜像构建完成。未启动服务。" -ForegroundColor Green
    exit 0
}

Write-Host "构建并启动系统主体..." -ForegroundColor Cyan
Invoke-Compose @("up", "-d", "--build", "--remove-orphans")

$healthUrl = if ($modeName -eq "demo") {
    "http://127.0.0.1:5173/api/health"
} else {
    "http://127.0.0.1:8080/api/health"
}

$healthy = $false
for ($attempt = 1; $attempt -le 60; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $healthy) {
    Write-Host "服务已启动但健康检查未通过；最近日志如下：" -ForegroundColor Yellow
    Invoke-Compose @("ps")
    Invoke-Compose @("logs", "--tail=80")
    Fail "健康检查失败：$healthUrl"
}

Write-Host ""
Write-Host "隐链明算 Windows 部署完成。" -ForegroundColor Green
if ($modeName -eq "demo") {
    Write-Host "访问地址：http://127.0.0.1:5173/login" -ForegroundColor Cyan
    Write-Host "演示账户：exchange / exchange123" -ForegroundColor Cyan
    Write-Host "仅限本地合成数据演示，不得作为生产配置。" -ForegroundColor Yellow
} else {
    Write-Host "本机地址：http://127.0.0.1:8080/login" -ForegroundColor Cyan
    Write-Host "当前 profile：$Profile" -ForegroundColor DarkGray
}
