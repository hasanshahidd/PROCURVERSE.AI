"""Rebuild users, approval_rules, approval_chains with proper role-based hierarchy."""
import psycopg2

conn = psycopg2.connect('postgresql://postgres:YourStr0ng!Pass@127.0.0.1:5433/odoo_procurement_demo')
conn.autocommit = True
cur = conn.cursor()

# ── Check/add columns ──
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users'")
cols = [r[0] for r in cur.fetchall()]
if 'approval_limit' not in cols:
    cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS approval_limit NUMERIC DEFAULT 0')
if 'title' not in cols:
    cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS title TEXT')

# ══════════════════════════════════════════════════════════════
# 1. USERS — 16 roles matching the UI sidebar
# ══════════════════════════════════════════════════════════════
cur.execute('DELETE FROM users')

users = [
    # (username, full_name, email, role, department, manager_email, title, approval_limit)
    # ── Manager Level (approve up to 10K) ──
    ('ap_manager',      'AP Manager',           'ap.manager@procure.ai',          'manager',  'Accounts Payable', 'finance.director@procure.ai', 'Manager',  10000),
    ('finance_manager', 'Finance Manager',      'finance.manager@procure.ai',     'manager',  'Finance',          'finance.director@procure.ai', 'Manager',  10000),
    ('proc_manager',    'Procurement Manager',  'procurement.manager@procure.ai', 'manager',  'Procurement',      'proc.director@procure.ai',    'Manager',  10000),
    ('proc_manager2',   'Procurement Manager',  'procurement.manager2@procure.ai','manager',  'Procurement',      'proc.director@procure.ai',    'Manager',  10000),
    ('ops_manager',     'Operations Manager',   'ops.manager@procure.ai',         'manager',  'Operations',       'ops.director@procure.ai',     'Manager',  10000),
    ('mike_manager',    'Mike Manager',         'mike.manager@procure.ai',        'manager',  'IT',               'diana.director@procure.ai',   'Manager',  10000),

    # ── Director Level (approve up to 50K) ──
    ('finance_director','Finance Director',     'finance.director@procure.ai',    'director', 'Finance',          'cfo@procure.ai',              'Director', 50000),
    ('finance_head',    'Finance Head',         'finance.head@procure.ai',        'director', 'Finance',          'cfo@procure.ai',              'Director', 50000),
    ('proc_director',   'Procurement Director', 'proc.director@procure.ai',       'director', 'Procurement',      'cpo@procure.ai',              'Director', 50000),
    ('ops_director',    'Operations Director',  'ops.director@procure.ai',        'director', 'Operations',       'coo@procure.ai',              'Director', 50000),
    ('diana_director',  'Diana Director',       'diana.director@procure.ai',      'director', 'IT',               'coo@procure.ai',              'Director', 50000),

    # ── VP / C-Level (approve 250K+) ──
    ('cfo',             'CFO',                  'cfo@procure.ai',                 'vp_cfo',   'Finance',          None,                          'VP/CFO',   999999999),
    ('coo',             'COO',                  'coo@procure.ai',                 'vp_cfo',   'Operations',       None,                          'VP/CFO',   999999999),
    ('cpo',             'CPO',                  'cpo@procure.ai',                 'vp_cfo',   'Procurement',      None,                          'VP/CFO',   999999999),
    ('victor_vp',       'Victor VP',            'victor.vp@procure.ai',           'vp_cfo',   'IT',               None,                          'VP/CFO',   999999999),
    ('sys_admin',       'System Admin',         'admin@procure.ai',               'vp_cfo',   'IT',               None,                          'VP/CFO',   999999999),
]

for u in users:
    cur.execute(
        """INSERT INTO users (username, full_name, email, role, department, manager_email, title, approval_limit, is_active)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)""", u)
print(f"Inserted {len(users)} users")


# ══════════════════════════════════════════════════════════════
# 2. APPROVAL RULES — Document type + amount → who approves
# ══════════════════════════════════════════════════════════════
#
#   Document Type  |  Amount Range    | Level | Who Approves         | Role
#   ───────────────┼──────────────────┼───────┼──────────────────────┼─────────
#   PR             |  0 - 10K         | 1     | Dept Manager         | manager
#   PR             |  10K - 50K       | 2     | Dept Director        | director
#   PR             |  50K - 250K      | 3     | CPO                  | vp_cfo
#   PR             |  250K+           | 4     | CFO                  | vp_cfo
#   ───────────────┼──────────────────┼───────┼──────────────────────┼─────────
#   PO             |  0 - 10K         | 1     | Procurement Mgr      | manager
#   PO             |  10K - 50K       | 2     | Procurement Dir      | director
#   PO             |  50K - 250K      | 3     | CPO                  | vp_cfo
#   PO             |  250K+           | 4     | CFO                  | vp_cfo
#   ───────────────┼──────────────────┼───────┼──────────────────────┼─────────
#   INVOICE        |  0 - 10K         | 1     | AP Manager           | manager
#   INVOICE        |  10K - 50K       | 2     | Finance Director     | director
#   INVOICE        |  50K+            | 3     | CFO                  | vp_cfo
#   ───────────────┼──────────────────┼───────┼──────────────────────┼─────────
#   PAYMENT        |  0 - 10K         | 1     | Finance Manager      | manager
#   PAYMENT        |  10K - 50K       | 2     | Finance Director     | director
#   PAYMENT        |  50K - 250K      | 3     | Finance Head         | director
#   PAYMENT        |  250K+           | 4     | CFO                  | vp_cfo
#   ───────────────┼──────────────────┼───────┼──────────────────────┼─────────
#   CONTRACT       |  0 - 25K         | 1     | Procurement Mgr      | manager
#   CONTRACT       |  25K - 100K      | 2     | Procurement Dir      | director
#   CONTRACT       |  100K - 500K     | 3     | CPO                  | vp_cfo
#   CONTRACT       |  500K+           | 4     | CFO + COO            | vp_cfo
#   ───────────────┼──────────────────┼───────┼──────────────────────┼─────────
#   BUDGET         |  0 - 25K         | 1     | Finance Manager      | manager
#   BUDGET         |  25K - 100K      | 2     | Finance Director     | director
#   BUDGET         |  100K+           | 3     | CFO                  | vp_cfo
#   ───────────────┼──────────────────┼───────┼──────────────────────┼─────────
#   VENDOR_ONBOARD |  any             | 1     | Procurement Mgr      | manager
#   VENDOR_ONBOARD |  any             | 2     | Procurement Dir      | director
#
cur.execute('DELETE FROM approval_rules')

rules = [
    # (doc_type, min, max, level, approver_name, approver_role, approver_email, department, sla_h, escalate_h)

    # PR
    ('PR', 0, 10000, 1, 'Department Manager',  'manager',  None,                          None,              24, 48),
    ('PR', 10000, 50000, 2, 'Department Director', 'director', None,                       None,              24, 48),
    ('PR', 50000, 250000, 3, 'CPO',             'vp_cfo',   'cpo@procure.ai',              'Procurement',     48, 96),
    ('PR', 250000, 999999999, 4, 'CFO',         'vp_cfo',   'cfo@procure.ai',              'Finance',         48, 96),

    # PO
    ('PO', 0, 10000, 1, 'Procurement Manager', 'manager',  'procurement.manager@procure.ai','Procurement',   24, 48),
    ('PO', 10000, 50000, 2, 'Procurement Director', 'director', 'proc.director@procure.ai','Procurement',    24, 48),
    ('PO', 50000, 250000, 3, 'CPO',            'vp_cfo',   'cpo@procure.ai',               'Procurement',    48, 96),
    ('PO', 250000, 999999999, 4, 'CFO',        'vp_cfo',   'cfo@procure.ai',               'Finance',        48, 96),

    # INVOICE
    ('INVOICE', 0, 10000, 1, 'AP Manager',     'manager',  'ap.manager@procure.ai',        'Accounts Payable',24, 48),
    ('INVOICE', 10000, 50000, 2, 'Finance Director', 'director', 'finance.director@procure.ai','Finance',     24, 48),
    ('INVOICE', 50000, 999999999, 3, 'CFO',    'vp_cfo',   'cfo@procure.ai',               'Finance',        48, 96),

    # PAYMENT
    ('PAYMENT', 0, 10000, 1, 'Finance Manager', 'manager', 'finance.manager@procure.ai',   'Finance',        24, 48),
    ('PAYMENT', 10000, 50000, 2, 'Finance Director','director','finance.director@procure.ai','Finance',       24, 48),
    ('PAYMENT', 50000, 250000, 3, 'Finance Head','director','finance.head@procure.ai',      'Finance',        48, 96),
    ('PAYMENT', 250000, 999999999, 4, 'CFO',   'vp_cfo',   'cfo@procure.ai',               'Finance',        48, 96),

    # CONTRACT
    ('CONTRACT', 0, 25000, 1, 'Procurement Manager','manager',None,                        'Procurement',    24, 48),
    ('CONTRACT', 25000, 100000, 2, 'Procurement Director','director','proc.director@procure.ai','Procurement',48, 96),
    ('CONTRACT', 100000, 500000, 3, 'CPO',     'vp_cfo',   'cpo@procure.ai',               'Procurement',    48, 96),
    ('CONTRACT', 500000, 999999999, 4, 'CFO + COO','vp_cfo','cfo@procure.ai',              'Finance',        72, 120),

    # BUDGET
    ('BUDGET', 0, 25000, 1, 'Finance Manager', 'manager',  'finance.manager@procure.ai',   'Finance',        24, 48),
    ('BUDGET', 25000, 100000, 2, 'Finance Director','director','finance.director@procure.ai','Finance',       48, 96),
    ('BUDGET', 100000, 999999999, 3, 'CFO',    'vp_cfo',   'cfo@procure.ai',               'Finance',        48, 96),

    # VENDOR_ONBOARD
    ('VENDOR_ONBOARD', 0, 999999999, 1, 'Procurement Manager','manager',None,              'Procurement',    24, 48),
    ('VENDOR_ONBOARD', 0, 999999999, 2, 'Procurement Director','director','proc.director@procure.ai','Procurement',48, 96),
]

for r in rules:
    cur.execute(
        """INSERT INTO approval_rules (document_type, amount_min, amount_max, approval_level,
           approver_name, approver_role, approver_email, department, sla_hours, escalate_after, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')""", r)
print(f"Inserted {len(rules)} approval rules")


# ══════════════════════════════════════════════════════════════
# 3. APPROVAL CHAINS — Department-specific escalation paths
# ══════════════════════════════════════════════════════════════
cur.execute('DELETE FROM approval_chains')

chains = [
    # (department, threshold, level, email, name)

    # IT
    ('IT',              10000, 1, 'mike.manager@procure.ai',        'Mike Manager'),
    ('IT',              50000, 2, 'diana.director@procure.ai',      'Diana Director'),
    ('IT',             250000, 3, 'victor.vp@procure.ai',           'Victor VP'),

    # Finance
    ('Finance',         10000, 1, 'finance.manager@procure.ai',     'Finance Manager'),
    ('Finance',         50000, 2, 'finance.director@procure.ai',    'Finance Director'),
    ('Finance',        250000, 3, 'cfo@procure.ai',                 'CFO'),

    # Operations
    ('Operations',      10000, 1, 'ops.manager@procure.ai',         'Operations Manager'),
    ('Operations',      50000, 2, 'ops.director@procure.ai',        'Operations Director'),
    ('Operations',     250000, 3, 'coo@procure.ai',                 'COO'),

    # Procurement
    ('Procurement',     10000, 1, 'procurement.manager@procure.ai', 'Procurement Manager'),
    ('Procurement',     50000, 2, 'proc.director@procure.ai',       'Procurement Director'),
    ('Procurement',    250000, 3, 'cpo@procure.ai',                 'CPO'),

    # Accounts Payable
    ('Accounts Payable',10000, 1, 'ap.manager@procure.ai',          'AP Manager'),
    ('Accounts Payable',50000, 2, 'finance.director@procure.ai',    'Finance Director'),
    ('Accounts Payable',250000,3, 'cfo@procure.ai',                 'CFO'),
]

for c in chains:
    cur.execute(
        """INSERT INTO approval_chains (department, budget_threshold, approval_level,
           approver_email, approver_name, status)
           VALUES (%s, %s, %s, %s, %s, 'approved')""", c)
print(f"Inserted {len(chains)} approval chains")

conn.close()
print("\nDone! Approval hierarchy is set.")
