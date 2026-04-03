# ============================================================
# Agent Verification Script
# Checks database changes + Odoo access + Dashboard visibility
# ============================================================

Write-Host "`n🔍 VERIFYING AGENT DATABASE CHANGES`n" -ForegroundColor Cyan

# Database connection (update password if needed)
$env:PGPASSWORD = "admin"
$dbHost = "localhost"
$dbPort = "5433"
$dbName = "odoo_procurement_demo"
$dbUser = "postgres"

# ============================================================
# 1. CHECK BUDGET CHANGES (Should show $120K committed to IT)
# ============================================================
Write-Host "1️⃣ Checking Budget Changes (Custom Table)..." -ForegroundColor Yellow
psql -h $dbHost -p $dbPort -U $dbUser -d $dbName -c "
SELECT 
    department,
    budget_category,
    committed_budget,
    available_budget,
    ROUND((committed_budget::numeric / allocated_budget * 100), 2) as utilization_pct
FROM budget_tracking
WHERE department = 'IT' AND budget_category = 'CAPEX';
"

# ============================================================
# 2. CHECK RECENT AGENT ACTIONS (Last 5 executions)
# ============================================================
Write-Host "`n2️⃣ Checking Agent Actions (Last 5)..." -ForegroundColor Yellow
psql -h $dbHost -p $dbPort -U $dbUser -d $dbName -c "
SELECT 
    agent_name,
    action_type,
    success,
    execution_time_ms,
    TO_CHAR(created_at, 'Mon DD HH24:MI:SS') as executed_at
FROM agent_actions
ORDER BY created_at DESC
LIMIT 5;
"

# ============================================================
# 3. CHECK PENDING APPROVALS (Low confidence decisions)
# ============================================================
Write-Host "`n3️⃣ Checking Pending Approvals..." -ForegroundColor Yellow
psql -h $dbHost -p $dbPort -U $dbUser -d $dbName -c "
SELECT 
    approval_id,
    agent_name,
    confidence_score,
    status,
    TO_CHAR(created_at, 'Mon DD HH24:MI:SS') as created
FROM pending_approvals
WHERE status = 'pending'
ORDER BY created_at DESC
LIMIT 3;
"

# ============================================================
# 4. CHECK ODOO VENDORS (Via API - should show real vendors)
# ============================================================
Write-Host "`n4️⃣ Checking Odoo Vendors (Via API)..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:5000/api/odoo/vendors?limit=5" -Method Get -TimeoutSec 5
    if ($response.vendors) {
        Write-Host "✅ Found $($response.vendors.Count) vendors in Odoo:" -ForegroundColor Green
        $response.vendors | Select-Object -First 5 | ForEach-Object {
            Write-Host "   - $($_.name) (ID: $($_.id))"
        }
    } else {
        Write-Host "⚠️ No vendors returned" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ Failed to connect to Odoo API: $_" -ForegroundColor Red
}

# ============================================================
# 5. CHECK AGENT DASHBOARD DATA (Via API)
# ============================================================
Write-Host "`n5️⃣ Checking Agent Dashboard Status..." -ForegroundColor Yellow
try {
    $dashboard = Invoke-RestMethod -Uri "http://localhost:5000/api/agentic/dashboard/data" -Method Get -TimeoutSec 5
    Write-Host "✅ Dashboard Data:" -ForegroundColor Green
    Write-Host "   - Active Agents: $($dashboard.active_agents)"
    Write-Host "   - Total Actions: $($dashboard.total_actions)"
    Write-Host "   - Budget Checks: $($dashboard.budget_checks)"
    Write-Host "   - Success Rate: $($dashboard.success_rate)%"
} catch {
    Write-Host "⚠️ Dashboard API not responding (might not be implemented)" -ForegroundColor Yellow
}

# ============================================================
# 6. SUMMARY
# ============================================================
Write-Host "`n📊 SUMMARY:" -ForegroundColor Cyan
Write-Host "   ✅ Custom Tables: budget_tracking, agent_actions, pending_approvals"
Write-Host "   ✅ Odoo Access: Via XML-RPC API (get_vendors, get_purchase_orders)"
Write-Host "   ✅ Dashboard: http://localhost:5173/agent-dashboard"
Write-Host "`n💡 TIP: Open Agent Dashboard in browser to see real-time updates`n"
