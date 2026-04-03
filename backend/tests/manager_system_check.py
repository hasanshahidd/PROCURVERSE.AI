"""
Manager View - Complete System Check
Shows what a project manager would see in the system
"""
import os
import sys
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv()

print("\n" + "="*80)
print("PROJECT MANAGER VIEW - COMPLETE SYSTEM CHECK")
print("="*80)

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor(cursor_factory=RealDictCursor)

# 1. RECENT PR WORKFLOWS (What PRs are in the system)
print("\n📋 1. RECENT PR WORKFLOWS IN SYSTEM:")
print("-" * 80)
cur.execute("""
    SELECT 
        pr_number,
        department,
        requester_name,
        total_amount,
        current_approval_level,
        workflow_status,
        created_at
    FROM pr_approval_workflows
    ORDER BY created_at DESC
    LIMIT 5
""")
workflows = cur.fetchall()
if workflows:
    for w in workflows:
        print(f"\n  PR: {w['pr_number']}")
        print(f"  Requester: {w['requester_name']} ({w['department']})")
        print(f"  Amount: ${w['total_amount']:,.2f}")
        print(f"  Current Level: {w['current_approval_level']}")
        print(f"  Status: {w['workflow_status']}")
        print(f"  Created: {w['created_at']}")
else:
    print("  📭 No workflows found")

# 2. PENDING APPROVALS FOR MIKE MANAGER
print("\n\n🔔 2. MY PENDING APPROVALS (Mike Manager):")
print("-" * 80)
cur.execute("""
    SELECT 
        s.pr_number,
        s.approval_level,
        s.status,
        w.department,
        w.total_amount,
        w.requester_name
    FROM pr_approval_steps s
    JOIN pr_approval_workflows w ON s.pr_number = w.pr_number
    WHERE s.approver_email = 'mike.manager@company.com'
      AND s.status = 'pending'
    ORDER BY w.created_at DESC
""")
pending = cur.fetchall()
if pending:
    for p in pending:
        print(f"\n  ✋ PR: {p['pr_number']}")
        print(f"     Requester: {p['requester_name']} ({p['department']})")
        print(f"     Amount: ${p['total_amount']:,.2f}")
        print(f"     My Level: {p['approval_level']} (Manager)")
        print(f"     🔴 STATUS: WAITING FOR MY APPROVAL")
else:
    print("  ✅ No pending approvals - inbox clear!")

# 3. MY APPROVAL STATISTICS  
print("\n\n📊 3. MY APPROVAL STATISTICS:")
print("-" * 80)
cur.execute("""
    SELECT 
        status,
        COUNT(*) as count,
        SUM(w.total_amount) as total_value
    FROM pr_approval_steps s
    JOIN pr_approval_workflows w ON s.pr_number = w.pr_number
    WHERE s.approver_email = 'mike.manager@company.com'
    GROUP BY status
""")
stats = cur.fetchall()
if stats:
    for stat in stats:
        print(f"  {stat['status'].upper()}: {stat['count']} items (${stat['total_value']:,.2f})")

# 4. APPROVAL CHAIN CONFIGURATION
print("\n\n🔗 4. APPROVAL CHAIN (How PRs flow):")
print("-" * 80)
cur.execute("""
    SELECT DISTINCT
        department,
        approval_level,
        approver_name,
        budget_threshold
    FROM approval_chains
    WHERE department = 'IT'
    ORDER BY approval_level
""")
chain = cur.fetchall()
if chain:
    print("\n  Example: IT Department PR Flow")
    for c in chain:
        level_name = ["", "Manager", "Director", "VP/CFO"][c['approval_level']]
        print(f"    Level {c['approval_level']} → {level_name}: {c['approver_name']} (${c['budget_threshold']:,.0f})")
else:
    print("  ⚠️ No approval chains configured")

# 5. AGENTIC SYSTEM STATUS
print("\n\n🤖 5. AGENTIC SYSTEM (AI Agents Working):")
print("-" * 80)
cur.execute("""
    SELECT 
        agent_name,
        COUNT(*) as actions,
        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
        AVG(execution_time_ms) as avg_time_ms
    FROM agent_actions
    WHERE created_at > NOW() - INTERVAL '7 days'
    GROUP BY agent_name
    ORDER BY actions DESC
    LIMIT 5
""")
agents = cur.fetchall()
if agents:
    print(f"\n  {'Agent':<30} {'Actions':<10} {'Success':<10} {'Avg Time'}")
    print(f"  {'-'*65}")
    for agent in agents:
        success_rate = (agent['successful'] / agent['actions'] * 100) if agent['actions'] > 0 else 0
        print(f"  {agent['agent_name']:<30} {agent['actions']:<10} "
              f"{success_rate:>6.1f}% {agent['avg_time_ms']:>10.0f}ms")
else:
    print("  📭 No recent agent activity")

cur.close()
conn.close()

print("\n" + "="*80)
print("\n💡 WHAT YOU CAN DO AS PROJECT MANAGER:")
print("\n  1. Submit new PR → POST /api/agentic/execute")
print("     Request: 'Create PR for Dell Server, $17K IT'")
print("\n  2. View your approvals → Frontend: /my-approvals")
print("     Shows items waiting for YOUR action")
print("\n  3. Track workflow progress → Frontend: /approval-workflows")
print("     See ALL company PRs and their approval status")
print("\n  4. Monitor agent actions → Frontend: /agent-dashboard")
print("     See AI agents working (budget checks, risk assessment, etc)")
print("\n" + "="*80 + "\n")
