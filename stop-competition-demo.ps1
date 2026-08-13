$ErrorActionPreference = "SilentlyContinue"

$ports = @(5173, 8000)
foreach ($port in $ports) {
    Get-NetTCPConnection -State Listen -LocalPort $port | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force
    }
}

Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "cloudflared.exe" -and $_.CommandLine -match "127\.0\.0\.1:5173"
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
}

Write-Host "HiddenChain competition demo has stopped."

