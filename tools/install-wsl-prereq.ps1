$ErrorActionPreference = 'Stop'
$log = Join-Path $env:TEMP 'hiddenchain-wsl-install.log'
Start-Transcript -Path $log -Force | Out-Null
try {
    Write-Host 'Enabling Windows Subsystem for Linux...'
    & dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 3010) { throw "WSL optional feature failed with exit code $LASTEXITCODE" }

    Write-Host 'Enabling Virtual Machine Platform...'
    & dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 3010) { throw "Virtual Machine Platform failed with exit code $LASTEXITCODE" }

    $msi = Join-Path $env:TEMP 'wsl_update_x64.msi'
    Write-Host 'Downloading the Microsoft WSL2 kernel package...'
    Invoke-WebRequest -Uri 'https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi' -OutFile $msi

    Write-Host 'Installing the Microsoft WSL2 kernel package...'
    $installer = Start-Process -FilePath 'msiexec.exe' -ArgumentList @('/i', $msi, '/qn', '/norestart') -Wait -PassThru
    if ($installer.ExitCode -ne 0 -and $installer.ExitCode -ne 3010) { throw "WSL2 kernel installer failed with exit code $($installer.ExitCode)" }

    Write-Host 'Setting WSL2 as the default version...'
    & wsl.exe --set-default-version 2
    if ($LASTEXITCODE -ne 0) { Write-Warning "wsl --set-default-version returned exit code $LASTEXITCODE; this may resolve after restart." }

    Write-Host 'WSL prerequisites installed. A Windows restart is required.'
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
finally {
    Stop-Transcript | Out-Null
}
