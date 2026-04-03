# Quick test script for all agents
Write-Host "=== Testing Agentic Procurement System ===" -ForegroundColor Cyan
Write-Host "Date: $(Get-Date)" -ForegroundColor Gray
Write-Host ""

$baseUrl = "http://localhost:5000"
$testsPassed = 0
$testsFailed = 0

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Method = "GET",
        [string]$Body = $null
    )
    
    Write-Host "Testing: $Name" -ForegroundColor Yellow
    
    try {
        if ($Method -eq "POST") {
            $response = Invoke-RestMethod -Uri $Url -Method $Method -ContentType "application/json" -Body $Body -ErrorAction Stop
        } else {
            $response = Invoke-RestMethod -Uri $Url -Method $Method -ErrorAction Stop
        }
        
        Write-Host "  ✅ PASS" -ForegroundColor Green
        Write-Host "  Response: $($response | ConvertTo-Json -Compress -Depth 3)" -ForegroundColor Gray
        $script:testsPassed++
        return $true
    }
    catch {
        Write-Host "  ❌ FAIL: $($_.Exception.Message)" -ForegroundColor Red
        $script:testsFailed++
        return $false
    }
    finally {
        Write-Host ""
    }
}

# Test 1: Health Check
Test-Endpoint -Name "System Health" -Url "$baseUrl/api/health"

# Test 2: Agent Health
Test-Endpoint -Name "Agent Health" -Url "$baseUrl/api/agentic/health"

# Test 3: List Agents
Test-Endpoint -Name "List Agents (Should show 2)" -Url "$baseUrl/api/agentic/agents"

# Test 4: Agent Status
Test-Endpoint -Name "Agent Status" -Url "$baseUrl/api/agentic/status"

# Test 5: Budget - IT $50K CAPEX (Should APPROVE)
$budgetTest1 = @{
    request = "Check if IT has budget for purchase"
    pr_data = @{
        department = "IT"
        budget = 50000
        budget_category = "CAPEX"
    }
} | ConvertTo-Json

Test-Endpoint -Name "Budget: IT $50K CAPEX (APPROVE)" -Url "$baseUrl/api/agentic/budget/verify" -Method "POST" -Body $budgetTest1

# Test 6: Budget - Operations $5M CAPEX (Should REJECT)
$budgetTest2 = @{
    request = "Check if Operations can afford this"
    pr_data = @{
        department = "Operations"
        budget = 5000000
        budget_category = "CAPEX"
    }
} | ConvertTo-Json

Test-Endpoint -Name "Budget: Operations $5M CAPEX (REJECT)" -Url "$baseUrl/api/agentic/budget/verify" -Method "POST" -Body $budgetTest2

# Test 7: Approval - IT $5K (Manager only)
$approvalTest1 = @{
    request = "Route this low-value PR"
    pr_data = @{
        pr_number = "PR-TEST-001"
        department = "IT"
        budget = 5000
        requester = "Test User"
    }
} | ConvertTo-Json

Test-Endpoint -Name "Approval: IT $5K (Manager only)" -Url "$baseUrl/api/agentic/approval/route" -Method "POST" -Body $approvalTest1

# Test 8: Approval - Finance $100K (3 levels)
$approvalTest2 = @{
    request = "Route this high-value PR"
    pr_data = @{
        pr_number = "PR-TEST-002"
        department = "Finance"
        budget = 100000
        requester = "Test User"
    }
} | ConvertTo-Json

Test-Endpoint -Name "Approval: Finance $100K (3 levels)" -Url "$baseUrl/api/agentic/approval/route" -Method "POST" -Body $approvalTest2

# Test 9: Orchestrator - Budget Question
$orchTest1 = @{
    request = "Can IT afford 80K CAPEX?"
    pr_data = @{
        department = "IT"
        budget = 80000
        budget_category = "CAPEX"
    }
} | ConvertTo-Json

Test-Endpoint -Name "Orchestrator: Budget Question" -Url "$baseUrl/api/agentic/execute" -Method "POST" -Body $orchTest1

# Test 10: Orchestrator - Approval Question
$orchTest2 = @{
    request = "Who approves a 45K Finance purchase?"
    pr_data = @{
        pr_number = "PR-TEST-003"
        department = "Finance"
        budget = 45000
    }
} | ConvertTo-Json

Test-Endpoint -Name "Orchestrator: Approval Question" -Url "$baseUrl/api/agentic/execute" -Method "POST" -Body $orchTest2

# Summary
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Test Results Summary" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "✅ Passed: $testsPassed" -ForegroundColor Green
Write-Host "❌ Failed: $testsFailed" -ForegroundColor Red
Write-Host ""

if ($testsFailed -eq 0) {
    Write-Host "🎉 ALL TESTS PASSED!" -ForegroundColor Green
    Write-Host "Your agentic system is fully operational!" -ForegroundColor Green
} else {
    Write-Host "⚠️  Some tests failed. Check the logs above." -ForegroundColor Yellow
    Write-Host "Common issues:" -ForegroundColor Yellow
    Write-Host "  - Backend not running (run: uvicorn backend.main:app --reload)" -ForegroundColor Gray
    Write-Host "  - Database tables not created (run: python scripts/create_agent_tables.py)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "For detailed results, see: QUICK_TEST_QUERIES.md" -ForegroundColor Cyan
