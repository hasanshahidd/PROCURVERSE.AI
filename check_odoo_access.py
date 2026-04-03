"""
Check Odoo Access - Verify PO features and available modules
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from backend.services.odoo_client import OdooClient

def check_odoo_connection():
    """Test Odoo connection"""
    print("=" * 80)
    print("ODOO CONNECTION TEST")
    print("=" * 80)
    
    try:
        client = OdooClient()
        print(f"✅ Connected to Odoo at {client.url}")
        print(f"   Database: {client.db}")
        print(f"   User ID: {client.uid}")
        return client
    except Exception as e:
        print(f"❌ Failed to connect to Odoo: {e}")
        return None

def check_purchase_order_access(client):
    """Check if we can access purchase.order model"""
    print("\n" + "=" * 80)
    print("PURCHASE ORDER ACCESS TEST")
    print("=" * 80)
    
    try:
        # Try to read purchase orders
        pos = client.execute_kw('purchase.order', 'search_read', 
                               [[]], 
                               {'limit': 1, 'fields': ['name', 'state', 'partner_id']})
        print(f"✅ Can READ purchase.order model")
        print(f"   Found {len(pos)} PO(s) in test query")
        if pos:
            print(f"   Sample: {pos[0]}")
        
        # Check if we can create (test permissions)
        print("\n📝 Testing CREATE permission...")
        # Don't actually create, just check access rights
        access = client.execute_kw('purchase.order', 'check_access_rights', 
                                   ['create'], 
                                   {'raise_exception': False})
        if access:
            print(f"✅ Can CREATE purchase orders")
        else:
            print(f"⚠️ Cannot CREATE purchase orders (permission denied)")
        
        # Check approve/confirm permission
        print("\n✔️ Testing CONFIRM/APPROVE permission...")
        write_access = client.execute_kw('purchase.order', 'check_access_rights', 
                                         ['write'], 
                                         {'raise_exception': False})
        if write_access:
            print(f"✅ Can WRITE/APPROVE purchase orders")
        else:
            print(f"⚠️ Cannot WRITE/APPROVE purchase orders")
        
        return True
        
    except Exception as e:
        print(f"❌ Cannot access purchase.order: {e}")
        return False

def check_installed_modules(client):
    """Check which procurement modules are installed"""
    print("\n" + "=" * 80)
    print("INSTALLED MODULES CHECK")
    print("=" * 80)
    
    modules_to_check = [
        'purchase',  # Purchase Management
        'purchase_requisition',  # Purchase Requisitions (Tenders)
        'purchase_stock',  # Purchase + Inventory integration
        'stock',  # Inventory Management
        'account',  # Accounting (for invoices)
    ]
    
    try:
        for module in modules_to_check:
            result = client.execute_kw('ir.module.module', 'search_read',
                                      [[('name', '=', module)]],
                                      {'fields': ['name', 'state']})
            if result:
                state = result[0]['state']
                status = "✅ INSTALLED" if state == 'installed' else f"❌ NOT INSTALLED ({state})"
                print(f"{module:25s} → {status}")
            else:
                print(f"{module:25s} → ❌ NOT FOUND")
        
        return True
    except Exception as e:
        print(f"❌ Failed to check modules: {e}")
        return False

def check_database_access():
    """Check PostgreSQL database access"""
    print("\n" + "=" * 80)
    print("DATABASE ACCESS TEST")
    print("=" * 80)
    
    try:
        import psycopg2
        from backend.services import hybrid_query
        
        conn = hybrid_query.get_custom_db_connection()
        cursor = conn.cursor()
        
        # Check our custom tables
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN (
                'approval_chains', 
                'budget_tracking', 
                'agent_actions',
                'pr_approval_workflows',
                'pr_approval_steps',
                'pending_approvals'
            )
            ORDER BY table_name
        """)
        
        tables = cursor.fetchall()
        print(f"✅ Connected to PostgreSQL database")
        print(f"   Found {len(tables)} custom tables:")
        for table in tables:
            print(f"      - {table[0]}")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def calculate_odoo_dependency():
    """Calculate what % of system depends on Odoo"""
    print("\n" + "=" * 80)
    print("ODOO DEPENDENCY ANALYSIS")
    print("=" * 80)
    
    components = {
        "Data Sources": {
            "Odoo ERP (vendors, products, POs)": 40,
            "Custom Tables (approvals, budget, agent logs)": 40,
            "AI/LLM (OpenAI for decisions)": 20
        },
        "Read Operations": {
            "Odoo reads (vendors, POs, products, inventory)": 60,
            "Database reads (approval chains, budgets, workflows)": 40
        },
        "Write Operations": {
            "Odoo writes (create PO, approve PO, update status)": 50,
            "Database writes (agent logs, approval steps, decisions)": 50
        },
        "Business Logic": {
            "AI Agents (decision making, scoring, routing)": 70,
            "Odoo API calls (data CRUD)": 30
        },
        "User Interface": {
            "Frontend displays (React, dashboard, approvals)": 80,
            "Odoo integration (minimal, backend-only)": 20
        }
    }
    
    total_weight = 0
    odoo_weight = 0
    
    print("\nComponent Breakdown:")
    print("-" * 80)
    
    for category, items in components.items():
        print(f"\n{category}:")
        category_sum = sum(items.values())
        category_odoo = sum(v for k, v in items.items() if 'odoo' in k.lower())
        
        for component, percentage in items.items():
            indicator = "🔵 ODOO" if 'odoo' in component.lower() else "🟢 CUSTOM"
            print(f"  {indicator:10s} {percentage:3d}% - {component}")
        
        print(f"  {'─'*70}")
        print(f"  {'':<10s} Odoo in this category: {category_odoo}/{category_sum} = {(category_odoo/category_sum)*100:.0f}%")
        
        total_weight += category_sum
        odoo_weight += category_odoo
    
    overall_percentage = (odoo_weight / total_weight) * 100
    
    print("\n" + "=" * 80)
    print("OVERALL ODOO DEPENDENCY")
    print("=" * 80)
    print(f"\n🔵 Odoo-dependent: {odoo_weight} points")
    print(f"🟢 Custom/AI logic: {total_weight - odoo_weight} points")
    print(f"📊 TOTAL: {total_weight} points")
    print(f"\n{'='*80}")
    print(f"**ODOO DEPENDENCY: {overall_percentage:.1f}% of system**")
    print(f"{'='*80}")
    
    print("\nBreakdown:")
    print(f"  - {overall_percentage:.1f}% = Odoo ERP (data storage + PO operations)")
    print(f"  - {100-overall_percentage:.1f}% = Custom AI + Approval Workflows + Frontend")
    
    print("\nConclusion:")
    if overall_percentage > 50:
        print(f"  ⚠️  HIGH dependency on Odoo ({overall_percentage:.1f}%)")
        print(f"      System heavily relies on Odoo for core operations")
    elif overall_percentage > 30:
        print(f"  ✅ MODERATE dependency on Odoo ({overall_percentage:.1f}%)")
        print(f"      Good balance - Odoo for data, AI for intelligence")
    else:
        print(f"  ✅ LOW dependency on Odoo ({overall_percentage:.1f}%)")
        print(f"      System is AI-first with Odoo as data source")

if __name__ == "__main__":
    # Test 1: Odoo connection
    client = check_odoo_connection()
    
    if client:
        # Test 2: Purchase Order access
        check_purchase_order_access(client)
        
        # Test 3: Installed modules
        check_installed_modules(client)
    
    # Test 4: Database access
    check_database_access()
    
    # Test 5: Calculate dependency
    calculate_odoo_dependency()
    
    print("\n" + "=" * 80)
    print("END OF TESTS")
    print("=" * 80)
