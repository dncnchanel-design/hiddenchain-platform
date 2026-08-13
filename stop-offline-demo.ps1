$ErrorActionPreference = "SilentlyContinue"

foreach ($port in @(5173, 8000)) {
    Get-NetTCPConnection -State Listen -LocalPort $port | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force
    }
}

Write-Host "HiddenChain offline demo has stopped."
