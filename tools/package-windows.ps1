#requires -Version 5.1

<#[
Create the Windows Docker Compose delivery archive.

Only runtime source, deployment configuration, tests, synthetic fixtures and
the operational manuals are copied. Secrets, databases, caches, logs, build
outputs and review artifacts are intentionally excluded.
]#>
[CmdletBinding()]
param(
    [string]$Version = "0.2.0"
)

$ErrorActionPreference = "Stop"
if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$') {
    throw "Version must contain only letters, digits, dots, underscores, or hyphens."
}
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseRoot = Join-Path $root "release"
$packageName = "hiddenchain-platform-windows-v$Version"
$staging = Join-Path $releaseRoot $packageName
$zip = Join-Path $releaseRoot "$packageName.zip"
$checksum = Join-Path $releaseRoot "$packageName.sha256"

$rootFull = [System.IO.Path]::GetFullPath($root).TrimEnd("\")
$releaseFull = [System.IO.Path]::GetFullPath($releaseRoot).TrimEnd("\")
if (-not $releaseFull.StartsWith($rootFull + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Release path escaped the project root."
}
foreach ($targetPath in @($staging, $zip, $checksum)) {
    $targetFull = [System.IO.Path]::GetFullPath($targetPath)
    if (-not $targetFull.StartsWith($releaseFull + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Release target escaped the release directory."
    }
}

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
foreach ($path in @($staging, $zip, $checksum)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
New-Item -ItemType Directory -Force -Path $staging | Out-Null

function Copy-ReleaseFile([string]$RelativePath) {
    $source = Join-Path $root $RelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Missing release file: $RelativePath"
    }
    $target = Join-Path $staging $RelativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $source -Destination $target -Force
}

function Copy-ReleaseTree([string]$RelativePath) {
    $source = Join-Path $root $RelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Missing release directory: $RelativePath"
    }
    $sourceFull = [System.IO.Path]::GetFullPath($source).TrimEnd("\")
    $skipNames = @(".git", ".venv", "node_modules", "dist", "frontend_dist", "build", "runtime", "__pycache__", ".pytest_cache", ".hypothesis")
    $secretExtensions = @(".pem", ".key", ".p12", ".pfx", ".ppk", ".jks", ".keystore", ".der")
    $secretNames = @("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
    Get-ChildItem -LiteralPath $source -Recurse -File -Force | ForEach-Object {
        $relative = $_.FullName.Substring($sourceFull.Length).TrimStart("\")
        $parts = $relative -split "\\"
        if (($parts | Where-Object { $_ -in $skipNames }).Count -gt 0) { return }
        if ($_.Name -match '^\.env(?:\..+)?$' -or $_.Name -match '\.env$') { return }
        if ($_.Name -match '\.(?:db|sqlite|sqlite3)(?:-.+)?$') { return }
        if ($_.Extension.ToLowerInvariant() -in $secretExtensions) { return }
        if ($_.Name.ToLowerInvariant() -in $secretNames) { return }
        if ($_.Extension -in @(".pyc", ".log", ".db", ".sqlite", ".tsbuildinfo")) { return }
        Copy-ReleaseFile (Join-Path $RelativePath $relative)
    }
}

$rootFiles = @(
    ".dockerignore", ".env.example", ".gitattributes", ".gitignore", "Dockerfile",
    "README.md", "RELEASE_MANIFEST.md", "JUDGE_DEPLOYMENT.md", "JUDGE_DEPLOYMENT.tex",
    "SOURCE_CODE_GUIDE.md", "docker-compose.yml", "render.yaml",
    "docker-compose.production.yml", "production.env.example", "install-windows.ps1", "pytest.ini"
)
foreach ($file in $rootFiles) { Copy-ReleaseFile $file }

$subFiles = @(
    "backend\Dockerfile", "backend\pytest.ini", "backend\requirements.txt",
    "connector\Dockerfile", "connector\requirements.txt",
    "frontend\.dockerignore", "frontend\Dockerfile", "frontend\eslint.config.js", "frontend\index.html",
    "frontend\nginx.conf", "frontend\package.json", "frontend\pnpm-lock.yaml",
    "frontend\pnpm-workspace.yaml", "frontend\postcss.config.js", "frontend\tailwind.config.js",
    "frontend\tsconfig.app.json", "frontend\tsconfig.json", "frontend\tsconfig.node.json",
    "frontend\vite.config.ts", "tools\package-windows.ps1"
)
foreach ($file in $subFiles) { Copy-ReleaseFile $file }

$workflowRoot = Join-Path $root ".github\workflows"
if (-not (Test-Path -LiteralPath $workflowRoot -PathType Container)) {
    throw "Missing release directory: .github\workflows"
}
$workflowFiles = @(
    Get-ChildItem -LiteralPath $workflowRoot -File |
        Where-Object { $_.Extension.ToLowerInvariant() -in @(".yml", ".yaml") }
)
if ($workflowFiles.Count -eq 0) {
    throw "No GitHub workflow files found."
}
foreach ($workflow in $workflowFiles) {
    Copy-ReleaseFile (Join-Path ".github\workflows" $workflow.Name)
}

foreach ($tree in @(
    "backend\app", "backend\scripts", "backend\tests",
    "connector\app", "connector\tests", "frontend\src", "frontend\public",
    "frontend\scripts", "policy", "demo-data", "deploy"
)) {
    Copy-ReleaseTree $tree
}

foreach ($doc in @(
    "ARCHITECTURE.md", "ENVIRONMENT_MATRIX.md", "FISCO_BCOS_ANCHOR.md",
    "FULL_SETTLEMENT_SIMULATION_RUNBOOK.md", "PRODUCTION_DEPLOYMENT.md",
    "PRODUCTION_AGENT_PROVISIONING.example.json", "PRODUCTION_READINESS.md",
    "ROLE_ROUTE_MATRIX.md", "SETTLEMENT_WORKFLOW.md",
    "SOURCE_CODE_GUIDE.md", "TRUSTED_EXECUTION.md", "TRUSTED_EXECUTION_MODEL.md",
    "TRUSTED_EXECUTION_RUNBOOK.md", "WHITE_LABEL_GUIDE.md", "WINDOWS_DEPLOYMENT.md"
)) {
    Copy-ReleaseFile (Join-Path "docs" $doc)
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $staging,
    $zip,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false
)

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash.ToLowerInvariant()
$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($checksum, "$hash  $packageName.zip", $utf8)

$fileCount = @(Get-ChildItem -LiteralPath $staging -Recurse -File -Force).Count
$zipSize = (Get-Item -LiteralPath $zip).Length
Write-Output "Package: $zip"
Write-Output "Files: $fileCount"
Write-Output "Bytes: $zipSize"
Write-Output "SHA256: $hash"
