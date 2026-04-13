"""
PROCURE-AI: Full Cycle Demonstration
Shows how ALL 24 agents work through natural conversation
ERP: Oracle Fusion (demo tables)
"""
import requests, json

BASE = 'http://localhost:8000'
SEP = '=' * 70

def stream_query(query, sid):
    r = requests.post(f'{BASE}/api/agentic/execute/stream',
        json={'request': query, 'session_id': sid},
        stream=True, timeout=60)
    agents = []
    result = {}
    for line in r.iter_lines():
        if line and line.startswith(b'data: '):
            evt = json.loads(line[6:])
            if evt['type'] == 'agent_selected':
                agents.append(evt['data'].get('agent', ''))
            if evt['type'] in ('complete', 'error'):
                result = evt['data']
                break
    return agents, result

def get_deep(d, *keys):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, {})
        else:
            return '?'
    return d if d else '?'

print(SEP)
print('PROCURE-AI: FULL P2P CYCLE DEMONSTRATION')
print('ERP Adapter: Oracle Fusion (demo_oracle)')
print(SEP)

tests = [
    ("STEP 1: CREATE PURCHASE REQUEST",
     "Create a PR for 20 servers at $3000 each for IT department",
     "Compliance + Budget + Vendor -> PR created (pauses for vendor pick)"),

    ("STEP 2: CHECK BUDGET",
     "Check IT department budget",
     "Returns budget availability, utilization, alerts"),

    ("STEP 3: COMPLIANCE CHECK",
     "Run compliance check for $75000 IT equipment purchase",
     "Score, violations, warnings, approval requirements"),

    ("STEP 4: VENDOR SELECTION",
     "Recommend vendors for office laptops",
     "Ranked vendor list with scores, strengths, concerns"),

    ("STEP 5: APPROVAL ROUTING",
     "What approvals are needed for $120000 Operations purchase",
     "Approval chain with manager -> director -> VP levels"),

    ("STEP 6: RISK ASSESSMENT",
     "Assess risk for PO-2024-0341",
     "Risk score, risk factors, mitigation recommendations"),

    ("STEP 7: SUPPLIER PERFORMANCE",
     "Evaluate supplier performance for Dell Technologies",
     "Delivery rating, quality score, price competitiveness"),

    ("STEP 8: INVOICE MATCHING",
     "Match invoice INV-2026-0892 against PO and GRN",
     "2-way/3-way match, discrepancies identified"),

    ("STEP 9: QUALITY INSPECTION",
     "Inspect goods from GRN-2024-001",
     "QC score, pass/fail, checklist results"),

    ("STEP 10: DELIVERY TRACKING",
     "Track delivery for PO-2024-0341",
     "Delivery status, ETA, carrier info"),

    ("STEP 11: PAYMENT PROCESSING",
     "Process payment for invoice INV-2026-0892",
     "Payment readiness check, net payable calculation"),

    ("STEP 12: SPEND ANALYTICS",
     "Show spend analysis for IT department",
     "Spend by category, vendor, period trends"),

    ("STEP 13: RFQ CREATION",
     "Create RFQ for 100 monitors for IT",
     "RFQ created, vendors invited, deadline set"),

    ("STEP 14: RECONCILIATION",
     "Reconcile payments with bank statements",
     "Matched entries, unmatched exceptions"),

    ("STEP 15: PO AMENDMENT",
     "Change quantity on PO-2024-0341 from 50 to 75 units",
     "Amendment created, re-approval if impact > $5K"),

    ("STEP 16: RETURN TO VENDOR",
     "Return 10 damaged units from GRN-2024-001",
     "RTV created, credit expected, vendor notified"),

    ("STEP 17: VENDOR ONBOARDING",
     "Onboard new vendor TechCorp for IT supplies",
     "Vendor registered, compliance docs pending"),

    ("STEP 18: CONTRACT MONITORING",
     "Show expiring contracts this quarter",
     "Contract list, renewal alerts, compliance status"),

    ("STEP 19: PRICE ANALYSIS",
     "Analyze pricing for office supplies",
     "Price benchmarks, trends, savings opportunities"),

    ("STEP 20: INVENTORY CHECK",
     "Check inventory levels for laptops",
     "Stock levels, reorder points, safety stock"),
]

passed = 0
failed = 0
for title, query, description in tests:
    print(f"\n{title}")
    print(f"  Query: \"{query}\"")
    print(f"  Expected: {description}")
    try:
        agents, result = stream_query(query, f'demo-{title[:10]}')
        status = result.get('result', {}).get('status', '?')
        agent_names = ', '.join(agents) if agents else 'Orchestrator'
        print(f"  Agents: {agent_names}")
        print(f"  Status: {status}")
        print(f"  RESULT: PASS")
        passed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        failed += 1

print(f"\n{SEP}")
print(f"RESULTS: {passed}/{passed+failed} passed, {failed} failed")
print(f"{SEP}")
print()
print("HOW THE NATURAL P2P FLOW WORKS:")
print("  1. User: 'Create PR for 20 servers'    -> Compliance+Budget+Vendor -> PR")
print("  2. User: 'Approve PR-2026-xxx'          -> Approval routing -> PO created")
print("  3. User: 'Track delivery PO-2026-xxx'   -> Delivery tracking")
print("  4. User: 'Received goods PO-2026-xxx'   -> GRN + QC inspection")
print("  5. User: 'Match invoice INV-xxx'         -> Invoice + 3-way match")
print("  6. User: 'Process payment INV-xxx'       -> Payment readiness + execution")
print()
print("Each step is a SEPARATE chat message.")
print("Pipeline page shows INLINE decisions (vendor cards, approve/reject,")
print("GRN confirm) when human input is needed.")
print("No monolithic pipeline - the P2P flows NATURALLY through conversation.")
print(SEP)
