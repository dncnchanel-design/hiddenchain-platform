$ErrorActionPreference = 'Stop'
$log = Join-Path $env:TEMP 'hiddenchain-wsl-main-install.log'
Start-Transcript -Path $log -Force | Out-Null
try {
    $msi = Join-Path $env:TEMP 'wsl-2.7.3-x64.msi'
    $url = 'https://github.com/microsoft/WSL/releases/download/2.7.3/wsl.2.7.3.0.x64.msi'

    if (-not (Test-Path -LiteralPath $msi) -or (Get-Item -LiteralPath $msi).Length -lt 200MB) {
        Write-Host 'Downloading/resuming the official Microsoft WSL package...'
        $curl = (Get-Command curl.exe -ErrorAction SilentlyContinue).Source
        if (-not $curl) { throw 'curl.exe is not available on this Windows installation' }
        & $curl '-L' '--fail' '--retry' '20' '--retry-delay' '3' '--retry-all-errors' '--continue-at' '-' '--output' $msi $url
        if ($LASTEXITCODE -ne 0) { throw "WSL package download failed with exit code $LASTEXITCODE" }
    }

    $size = (Get-Item -LiteralPath $msi).Length
    if ($size -lt 200MB) { throw "WSL package download is incomplete: $size bytes" }

    Write-Host 'Installing the official Microsoft WSL package...'
    $installer = Start-Process -FilePath 'msiexec.exe' -ArgumentList @('/i', $msi, '/passive', '/norestart') -Wait -PassThru
    if ($installer.ExitCode -ne 0 -and $installer.ExitCode -ne 3010) { throw "WSL package installer failed with exit code $($installer.ExitCode)" }

    Write-Host 'Setting WSL2 as the default version...'
    & wsl.exe --set-default-version 2
    if ($LASTEXITCODE -ne 0) { Write-Warning "wsl --set-default-version returned exit code $LASTEXITCODE; restart may be required." }

    Write-Host 'WSL main package installed. A restart may be required before Docker Desktop can start.'
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
finally {
    Stop-Transcript | Out-Null
}
