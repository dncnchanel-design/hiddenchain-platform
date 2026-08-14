param(
    [string]$BaseUrl = "http://127.0.0.1:5173",
    [double]$DurationHours = 4,
    [int]$IntervalSeconds = 30
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "runtime\performance"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$startedAt = Get-Date
$endsAt = $startedAt.AddHours($DurationHours)
$stamp = $startedAt.ToString("yyyyMMdd-HHmmss")
$eventsPath = Join-Path $logDir "soak-$stamp.jsonl"
$summaryPath = Join-Path $logDir "soak-$stamp-summary.json"
$headers = @{ "Cache-Control" = "no-cache" }
$total = 0
$passed = 0
$failed = 0
$maxLatency = 0
$failureMessages = [System.Collections.Generic.List[string]]::new()

function Invoke-Probe {
    param(
        [string]$Name,
        [string]$Uri,
        [string]$Method = "GET",
        [hashtable]$RequestHeaders = $headers,
        [object]$Body = $null
    )

    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $request = @{
            Uri = $Uri
            Method = $Method
            Headers = $RequestHeaders
            TimeoutSec = 15
            UseBasicParsing = $true
        }
        if ($null -ne $Body) {
            $request.ContentType = "application/json"
            $request.Body = ($Body | ConvertTo-Json -Depth 8 -Compress)
        }
        $response = Invoke-WebRequest @request
        $watch.Stop()
        return [pscustomobject]@{
            name = $Name
            ok = $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
            status = [int]$response.StatusCode
            latency_ms = [int]$watch.ElapsedMilliseconds
            error = $null
        }
    } catch {
        $watch.Stop()
        return [pscustomobject]@{
            name = $Name
            ok = $false
            status = 0
            latency_ms = [int]$watch.ElapsedMilliseconds
            error = $_.Exception.Message
        }
    }
}

function Invoke-TrustedExecutionProbe {
    param(
        [string]$Uri,
        [hashtable]$RequestHeaders = $headers
    )

    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $payload = Invoke-RestMethod -Uri $Uri -Method Get -Headers $RequestHeaders -TimeoutSec 15
        $watch.Stop()
        $boundary = $payload.security_boundary
        $audit = $payload.audit
        $ok = $payload.controller -eq "TRUSTWORTHY_EXECUTION_CONTROLLER_V1" `
            -and $boundary.raw_data_transferred -eq $false `
            -and $boundary.raw_data_returned -eq $false `
            -and $boundary.anti_inference_checks -eq $true `
            -and $boundary.topology_coordinates_released -eq $false `
            -and $audit.asynchronous_blockchain_logging -eq $true `
            -and $audit.result_hash_required -eq $true
        return [pscustomobject]@{
            name = "api.trusted_execution.boundary"
            ok = $ok
            status = 200
            latency_ms = [int]$watch.ElapsedMilliseconds
            error = if ($ok) { $null } else { "trusted execution security boundary mismatch" }
        }
    } catch {
        $watch.Stop()
        return [pscustomobject]@{
            name = "api.trusted_execution.boundary"
            ok = $false
            status = 0
            latency_ms = [int]$watch.ElapsedMilliseconds
            error = $_.Exception.Message
        }
    }
}

Write-Host "Performance soak started: $startedAt -> $endsAt"
Write-Host "Events: $eventsPath"

while ((Get-Date) -lt $endsAt) {
    $cycleStarted = Get-Date
    $cycle = [System.Collections.Generic.List[object]]::new()
    $cycle.Add((Invoke-Probe "page.login" "$BaseUrl/login"))
    $cycle.Add((Invoke-Probe "api.health" "$BaseUrl/api/health"))

    try {
        $login = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -Headers $headers -ContentType "application/json" -Body (@{ username = "exchange"; password = "exchange123" } | ConvertTo-Json -Compress) -TimeoutSec 15
        $authHeaders = @{ Authorization = "Bearer $($login.access_token)"; "Cache-Control" = "no-cache" }
        $cycle.Add((Invoke-Probe "api.tasks" "$BaseUrl/api/settlement/tasks" -RequestHeaders $authHeaders))
        $cycle.Add((Invoke-Probe "api.privacy" "$BaseUrl/api/privacy/jobs" -RequestHeaders $authHeaders))
        $cycle.Add((Invoke-Probe "api.evidence" "$BaseUrl/api/chain/evidence?task_id=task-ready-demo" -RequestHeaders $authHeaders))
        $cycle.Add((Invoke-Probe "api.catalog" "$BaseUrl/api/data/catalog?trade_batch_no=TB-2026-07-DEMO" -RequestHeaders $authHeaders))
        $cycle.Add((Invoke-Probe "api.protocol" "$BaseUrl/api/data-space/protocol" -RequestHeaders $authHeaders))
        $cycle.Add((Invoke-TrustedExecutionProbe "$BaseUrl/api/trusted-execution/status" -RequestHeaders $authHeaders))
    } catch {
        $cycle.Add([pscustomobject]@{ name = "api.auth"; ok = $false; status = 0; latency_ms = 0; error = $_.Exception.Message })
    }

    $total += $cycle.Count
    $cyclePassed = @($cycle | Where-Object { $_.ok }).Count
    $passed += $cyclePassed
    $failed += $cycle.Count - $cyclePassed
    $cycle | ForEach-Object { if ($_.latency_ms -gt $maxLatency) { $maxLatency = $_.latency_ms } }
    $cycle | Where-Object { -not $_.ok } | ForEach-Object {
        $failure = if ($_.error) { $_.error } else { "HTTP $($_.status)" }
        $failureMessages.Add("$($_.name): $failure")
    }

    $event = [pscustomobject]@{
        at = $cycleStarted.ToString("o")
        duration_hours = $DurationHours
        checks = $cycle
        passed = $cyclePassed
        failed = $cycle.Count - $cyclePassed
    }
    ($event | ConvertTo-Json -Depth 8 -Compress) | Add-Content -Path $eventsPath -Encoding utf8
    Write-Host ("{0:u} checks {1}/{2}, max {3}ms" -f $cycleStarted, $cyclePassed, $cycle.Count, $maxLatency)

    $remaining = [int][Math]::Max(1, [Math]::Min($IntervalSeconds, ($endsAt - (Get-Date)).TotalSeconds))
    Start-Sleep -Seconds $remaining
}

$summary = [pscustomobject]@{
    started_at = $startedAt.ToString("o")
    ended_at = (Get-Date).ToString("o")
    duration_hours = $DurationHours
    interval_seconds = $IntervalSeconds
    total_checks = $total
    passed_checks = $passed
    failed_checks = $failed
    max_latency_ms = $maxLatency
    failures = $failureMessages
    events_file = $eventsPath
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -Path $summaryPath -Encoding utf8
Write-Host "Performance soak finished. Summary: $summaryPath"
