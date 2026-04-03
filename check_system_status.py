"""Check complete system status - Odoo + Database + Agent Actions"""

from backend.services.odoo_client import get_odoo_client
import psycopg2
from psycopg2.extras import RealDictCursor

# ==========  ODOO STATUS ==========
print('=' * 80)
print('🔍 ODOO SYSTEM STATUS')
print('=' * 80)

odoo = get_odoo_client()

# Purchase orders
pos = odoo.get_purchase_orders(limit=200)
print(f'\n📦 PURCHASE ORDERS: {len(pos)} total')
states = {}
for po in pos:
    state = po.get('state', 'unknown')
    states[state] = states.get(state, 0) + 1
for state, count in sorted(states.items()):
    print(f'   {state}: {count}')

# Vendors
vendors = odoo.get_vendors(limit=100)
print(f'\n🏢 VENDORS: {len(vendors)} total')
for v in vendors[:10]:
    print(f'   - {v.get("name")} (ID: {v.get("id")})')

# Products
products = odoo.get_products(limit=100)
print(f'\n📊 PRODUCTS: {len(products)} total')

print('\n' + '=' * 80)
print('🗄️  AGENTIC SYSTEM DATABASE STATUS')
print('=' * 80)

# Database stats
conn = psycopg2.connect('postgresql://postgres:YourStr0ng!Pass@localhost:5433/odoo_procurement_demo')
cur = conn.cursor(cursor_factory=RealDictCursor)

# Approval chains
cur.execute('SELECT COUNT(*) as count FROM approval_chains')
print(f'\n📋 Approval Chains: {cur.fetchone()["count"]}')

# Budget tracking
cur.execute('SELECT department, budget_category, allocated_budget, spent_budget FROM budget_tracking ORDER BY department, budget_category')
budgets = cur.fetchall()
print(f'\n💰 Budget Tracking: {len(budgets)} records')
for b in budgets:
    spent_pct = (b['spent_budget'] / b['allocated_budget'] * 100) if b['allocated_budget'] > 0 else 0
    print(f'   {b["department"]:12s} {b["budget_category"]:6s}: ${b["spent_budget"]:>10,.0f} / ${b["allocated_budget"]:>10,.0f} ({spent_pct:.1f}%)')

# Agent actions
cur.execute('SELECT agent_name, COUNT(*) as count FROM agent_actions GROUP BY agent_name ORDER BY count DESC')
actions = cur.fetchall()
print(f'\n🤖 Agent Actions: {sum(a["count"] for a in actions)} total')
for a in actions[:10]:
    print(f'   {a["agent_name"]:30s}: {a["count"]:4d} actions')

# PR Workflows
cur.execute('SELECT workflow_status, COUNT(*) as count FROM pr_approval_workflows GROUP BY workflow_status')
workflows = cur.fetchall()
print(f'\n📝 PR Workflows: {sum(w["count"] for w in workflows)} total')
for w in workflows:
    print(f'   {w["workflow_status"]}: {w["count"]}')

# Workflows with Odoo PO
cur.execute('SELECT COUNT(*) as count FROM pr_approval_workflows WHERE odoo_po_id IS NOT NULL')
po_count = cur.fetchone()['count']
print(f'\n🔗 Workflows with Odoo PO: {po_count}')

# Recent workflows
cur.execute('''
    SELECT pr_number, department, total_amount, workflow_status, odoo_po_id, created_at 
    FROM pr_approval_workflows 
    ORDER BY created_at DESC 
    LIMIT 5
''')
recent = cur.fetchall()
print(f'\n📊 Recent Workflows:')
for r in recent:
    po_info = f' → PO {r["odoo_po_id"]}' if r['odoo_po_id'] else ''
    print(f'   {r["pr_number"]:20s} {r["department"]:12s} ${r["total_amount"]:>10,.0f} [{r["workflow_status"]}]{po_info}')

# Pending approvals
cur.execute('SELECT COUNT(*) as count FROM pending_approvals WHERE status = %s', ('pending',))
pending_count = cur.fetchone()['count']
print(f'\n⚠️  Pending Human Approvals: {pending_count}')

cur.close()
conn.close()

print('\n' + '=' * 80)
print('✅ SYSTEM STATUS COMPLETE')
print('=' * 80)
