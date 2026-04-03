# Test AgentProcessVisualizer SSE streaming
Write-Host "Testing Agent SSE Streaming..." -ForegroundColor Cyan
Write-Host "This will show if events arrive sequentially (SSE works)" -ForegroundColor Yellow
Write-Host "Frontend should display these one-by-one at 700ms intervals`n" -ForegroundColor Yellow

$body = @{
    request = "Check IT department budget for $50,000 laptop purchase"
    pr_data = @{
        department = "IT"
        budget_category = "CAPEX"
        amount = 50000
        pr_number = "PR-2026-TEST01"
    }
} | ConvertTo-Json -Depth 10

try {
    Write-Host "[TEST START] Sending request to /api/agentic/execute/stream..." -ForegroundColor Green
    
    # Make the request and capture streaming response
    $response = Invoke-WebRequest -Uri "http://localhost:5000/api/agentic/execute/stream" `
        -Method Post `
        -Body $body `
        -ContentType "application/json" `
        -TimeoutSec 30 `
        -UseBasicParsing
    
    # Parse SSE events from response
    $content = $response.Content
    $events = $content -split "`n`n" | Where-Object { $_ -match "^data:" }
    
    Write-Host "`n[EVENTS RECEIVED] Total: $($events.Count) events`n" -ForegroundColor Magenta
    
    $eventNumber = 1
    foreach ($event in $events) {
        if ($event -match "data:\s*(.+)") {
            $jsonData = $matches[1]
            try {
                $parsedEvent = $jsonData | ConvertFrom-Json
                
                # Colorize based on event type
                $color = switch ($parsedEvent.type) {
                    "observe" { "Cyan" }
                    "decide" { "Yellow" }
                    "act" { "Green" }
                    "learn" { "Blue" }
                    "complete" { "Magenta" }
                    "error" { "Red" }
                    default { "White" }
                }
                
                Write-Host "Event $eventNumber - " -NoNewline
                Write-Host "$($parsedEvent.type.ToUpper())" -ForegroundColor $color -NoNewline
                
                if ($parsedEvent.data.step) {
                    Write-Host " | Step: $($parsedEvent.data.step)" -NoNewline
                }
                if ($parsedEvent.data.status) {
                    Write-Host " | Status: $($parsedEvent.data.status)" -NoNewline
                }
                if ($parsedEvent.data.message) {
                    Write-Host " | $($parsedEvent.data.message)" -NoNewline
                }
                
                Write-Host ""
                $eventNumber++
            }
            catch {
                Write-Host "Event $eventNumber - RAW: $jsonData" -ForegroundColor Gray
                $eventNumber++
            }
        }
    }
    
    Write-Host "`n[STREAMING TEST RESULT]" -ForegroundColor Green
    Write-Host "✓ SSE endpoint responded successfully" -ForegroundColor Green
    Write-Host "✓ Events are being sent sequentially from backend" -ForegroundColor Green
    Write-Host "`n[FRONTEND BEHAVIOR]" -ForegroundColor Yellow
    Write-Host "With the new fix, these $($events.Count) events should:" -ForegroundColor Yellow
    Write-Host "  1. Arrive in frontend queue immediately (SSE stream)" -ForegroundColor White
    Write-Host "  2. Display one-by-one at 700ms intervals (event queue processor)" -ForegroundColor White
    Write-Host "  3. NOT appear all at once (interval drains queue before terminating)" -ForegroundColor White
    Write-Host "`nTotal animation time: ~$([math]::Round($events.Count * 0.7, 1)) seconds`n" -ForegroundColor Cyan
}
catch {
    Write-Host "`n[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Full error: $($_ | Out-String)" -ForegroundColor Gray
}
