"""
Pre-Implementation Verification Script
Run this BEFORE starting agent-Odoo integration to ensure system is ready.

Usage:
    python verify_system_ready.py

This will check:
1. Odoo connection
2. Database schema
3. Current agents operational
4. Required tools available
5. Sample data exists
"""

import sys
import json
import asyncio
from datetime import datetime

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_check(message, status):
    """Print formatted check result"""
    symbol = f"{GREEN}✅{RESET}" if status else f"{RED}❌{RESET}"
    print(f"{symbol} {message}")
    return status

def print_header(message):
    """Print section header"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{message}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")

async def main():
    # Load environment variables FIRST
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    print(f"\n{BLUE}🔍 PRE-IMPLEMENTATION SYSTEM VERIFICATION{RESET}")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    all_checks_passed = True
    
    # ============================================================
    # 1. ODOO CONNECTION CHECK
    # ============================================================
    print_header("1. ODOO CONNECTION")
    
    try:
        from backend.services.odoo_client import get_odoo_client
        
        odoo = get_odoo_client()
        
        # Test connection
        try:
            # Check if connected by testing authentication
            if odoo.is_connected():
                # Try to get server version via common endpoint
                version_info = odoo.common.version()
                server_version = version_info.get('server_version', 'Unknown')
                all_checks_passed &= print_check(
                    f"Odoo connection successful (v{server_version})",
                    True
                )
            else:
                all_checks_passed &= print_check(
                    "Odoo connection FAILED: Authentication failed",
                    False
                )
                print(f"{YELLOW}   → Check Odoo server is running on port 8069{RESET}")
                print(f"{YELLOW}   → Verify credentials in .env file{RESET}")
        except Exception as e:
            all_checks_passed &= print_check(
                f"Odoo connection FAILED: {e}",
                False
            )
            print(f"{YELLOW}   → Check Odoo server is running on port 8069{RESET}")
            print(f"{YELLOW}   → Verify credentials in .env file{RESET}")
    
    except ImportError as e:
        all_checks_passed &= print_check(
            f"Cannot import Odoo client: {e}",
            False
        )
    
    # ============================================================
    # 2. ODOO MODELS CHECK
    # ============================================================
    print_header("2. ODOO MODELS & DATA")
    
    try:
        # Check required models exist
        required_models = [
            'purchase.order',
            'res.partner',
            'product.product',
            'account.move',
            'stock.picking'
        ]
        
        for model in required_models:
            try:
                fields = odoo.execute_kw(model, 'fields_get', [], {'attributes': ['string']})
                all_checks_passed &= print_check(
                    f"Model {model} exists ({len(fields)} fields)",
                    True
                )
            except Exception as e:
                all_checks_passed &= print_check(
                    f"Model {model} NOT accessible: {e}",
                    False
                )
        
        # Check sample data
        print(f"\n{BLUE}Sample Data Check:{RESET}")
        
        vendors = odoo.get_vendors(limit=5)
        all_checks_passed &= print_check(
            f"Vendors available: {len(vendors)} (need at least 5)",
            len(vendors) >= 5
        )
        if len(vendors) < 5:
            print(f"{YELLOW}   → Load more vendors into Odoo{RESET}")
        
        pos = odoo.get_purchase_orders(limit=5)
        all_checks_passed &= print_check(
            f"Purchase orders available: {len(pos)}",
            len(pos) > 0
        )
        
        products = odoo.get_products(limit=5)
        all_checks_passed &= print_check(
            f"Products available: {len(products)} (need at least 5)",
            len(products) >= 5
        )
        if len(products) < 5:
            print(f"{YELLOW}   → Load more products into Odoo{RESET}")
    
    except Exception as e:
        all_checks_passed &= print_check(
            f"Odoo data check failed: {e}",
            False
        )
    
    # ============================================================
    # 3. DATABASE CONNECTION CHECK
    # ============================================================
    print_header("3. POSTGRESQL DATABASE")
    
    try:
        from backend.services import hybrid_query
        
        conn = hybrid_query.get_custom_db_connection()
        cursor = conn.cursor()
        
        all_checks_passed &= print_check("PostgreSQL connection successful", True)
        
        # Check required tables
        required_tables = [
            'approval_chains',
            'budget_tracking',
            'agent_actions',
            'agent_decisions',
            'pending_approvals',
            'pr_approval_workflows',
            'pr_approval_steps'
        ]
        
        for table in required_tables:
            cursor.execute(f"""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                )
            """, (table,))
            exists = cursor.fetchone()[0]
            all_checks_passed &= print_check(
                f"Table {table} exists",
                exists
            )
            if not exists:
                print(f"{YELLOW}   → Run database migration scripts{RESET}")
        
        # Check sample data in custom tables
        print(f"\n{BLUE}Custom Table Data:{RESET}")
        
        cursor.execute("SELECT COUNT(*) FROM approval_chains")
        approval_count = cursor.fetchone()[0]
        all_checks_passed &= print_check(
            f"Approval chains: {approval_count} (need at least 12)",
            approval_count >= 12
        )
        
        cursor.execute("SELECT COUNT(*) FROM budget_tracking")
        budget_count = cursor.fetchone()[0]
        all_checks_passed &= print_check(
            f"Budget tracking records: {budget_count} (need at least 8)",
            budget_count >= 8
        )
        
        cursor.execute("SELECT COUNT(*) FROM agent_actions WHERE success = true")
        action_count = cursor.fetchone()[0]
        print_check(f"Successful agent actions: {action_count}", True)
        
        cursor.close()
        conn.close()
    
    except Exception as e:
        all_checks_passed &= print_check(
            f"Database check failed: {e}",
            False
        )
    
    # ============================================================
    # 4. AGENT SYSTEM CHECK
    # ============================================================
    print_header("4. AGENT SYSTEM")
    
    try:
        from backend.agents.orchestrator import OrchestratorAgent
        from backend.agents.budget_verification import BudgetVerificationAgent
        from backend.agents.approval_routing import ApprovalRoutingAgent
        from backend.agents.vendor_selection import VendorSelectionAgent
        from backend.agents.risk_assessment import RiskAssessmentAgent
        from backend.agents.supplier_performance import SupplierPerformanceAgent
        
        agents_to_check = [
            ("OrchestratorAgent", OrchestratorAgent),
            ("BudgetVerificationAgent", BudgetVerificationAgent),
            ("ApprovalRoutingAgent", ApprovalRoutingAgent),
            ("VendorSelectionAgent", VendorSelectionAgent),
            ("RiskAssessmentAgent", RiskAssessmentAgent),
            ("SupplierPerformanceAgent", SupplierPerformanceAgent),
        ]
        
        for agent_name, AgentClass in agents_to_check:
            try:
                agent = AgentClass()
                all_checks_passed &= print_check(
                    f"{agent_name} initializes successfully",
                    True
                )
            except Exception as e:
                all_checks_passed &= print_check(
                    f"{agent_name} initialization FAILED: {e}",
                    False
                )
    
    except ImportError as e:
        all_checks_passed &= print_check(
            f"Cannot import agents: {e}",
            False
        )
    
    # ============================================================
    # 5. TOOLS CHECK
    # ============================================================
    print_header("5. LANGCHAIN TOOLS")
    
    try:
        from backend.agents.tools import (
            create_odoo_tools,
            create_database_tools
        )
        
        odoo_tools = create_odoo_tools()
        all_checks_passed &= print_check(
            f"Odoo tools created: {len(odoo_tools)} tools",
            len(odoo_tools) >= 5
        )
        
        db_tools = create_database_tools()
        all_checks_passed &= print_check(
            f"Database tools created: {len(db_tools)} tools",
            len(db_tools) >= 4
        )
        
        # List available tools
        print(f"\n{BLUE}Available Odoo Tools:{RESET}")
        for tool in odoo_tools:
            print(f"  • {tool.name}")
        
        print(f"\n{BLUE}Available Database Tools:{RESET}")
        for tool in db_tools:
            print(f"  • {tool.name}")
    
    except Exception as e:
        all_checks_passed &= print_check(
            f"Tools check failed: {e}",
            False
        )
    
    # ============================================================
    # 6. APPROVAL WORKFLOW CHECK
    # ============================================================
    print_header("6. APPROVAL WORKFLOW")
    
    try:
        # Check if we can create workflow
        from backend.services import hybrid_query
        
        conn = hybrid_query.get_custom_db_connection()
        cursor = conn.cursor()
        
        # Check if odoo_po_id column exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'pr_approval_workflows' 
            AND column_name = 'odoo_po_id'
        """)
        has_po_column = cursor.fetchone() is not None
        all_checks_passed &= print_check(
            "pr_approval_workflows has odoo_po_id column",
            has_po_column
        )
        if not has_po_column:
            print(f"{YELLOW}   → Run: python backend/migrations/add_odoo_po_id_column.py{RESET}")
        
        # Check completed workflows with PO IDs
        cursor.execute("""
            SELECT COUNT(*) 
            FROM pr_approval_workflows 
            WHERE workflow_status = 'completed' 
            AND odoo_po_id IS NOT NULL
        """)
        completed_with_po = cursor.fetchone()[0]
        print_check(
            f"Completed workflows with Odoo PO: {completed_with_po}",
            True
        )
        
        cursor.close()
        conn.close()
    
    except Exception as e:
        all_checks_passed &= print_check(
            f"Approval workflow check failed: {e}",
            False
        )
    
    # ============================================================
    # 7. API ENDPOINTS CHECK
    # ============================================================
    print_header("7. API ENDPOINTS")
    
    try:
        import requests
        
        base_url = "http://localhost:5000"
        
        # Check backend is running
        try:
            response = requests.get(f"{base_url}/api/health", timeout=2)
            all_checks_passed &= print_check(
                f"Backend API running (status: {response.status_code})",
                response.status_code == 200
            )
        except requests.exceptions.RequestException:
            all_checks_passed &= print_check(
                "Backend API NOT running",
                False
            )
            print(f"{YELLOW}   → Start backend: cd backend && uvicorn backend.main:app --reload{RESET}")
        
        # Check key endpoints exist
        endpoints_to_check = [
            "/api/odoo/status",
            "/api/agentic/status",
            "/api/agentic/agents",
            "/api/agentic/approval-workflows"
        ]
        
        for endpoint in endpoints_to_check:
            try:
                response = requests.get(f"{base_url}{endpoint}", timeout=2)
                print_check(
                    f"Endpoint {endpoint} accessible",
                    response.status_code == 200
                )
            except:
                print_check(f"Endpoint {endpoint} NOT accessible", False)
    
    except ImportError:
        print(f"{YELLOW}⚠️  requests library not installed (optional check){RESET}")
    
    # ============================================================
    # 8. ENVIRONMENT VARIABLES CHECK
    # ============================================================
    print_header("8. ENVIRONMENT VARIABLES")
    
    # Already loaded at start of main()
    import os
    
    required_env_vars = [
        'OPENAI_API_KEY',
        'DATABASE_URL',
        'ODOO_URL',
        'ODOO_DB',
        'ODOO_USERNAME',
        'ODOO_PASSWORD'
    ]
    
    for var in required_env_vars:
        value = os.getenv(var)
        is_set = value is not None and len(value) > 0
        all_checks_passed &= print_check(
            f"{var} is set",
            is_set
        )
        if not is_set:
            print(f"{YELLOW}   → Add {var} to .env file{RESET}")
    
    # ============================================================
    # SUMMARY
    # ============================================================
    print_header("VERIFICATION SUMMARY")
    
    if all_checks_passed:
        print(f"\n{GREEN}✅✅✅ ALL CHECKS PASSED!{RESET}")
        print(f"\n{GREEN}System is READY for agent-Odoo integration.{RESET}")
        print(f"\n{BLUE}Next steps:{RESET}")
        print(f"1. Review WEEK1_IMPLEMENTATION_PLAN.md")
        print(f"2. Start with VendorSelectionAgent integration")
        print(f"3. Follow step-by-step implementation guide")
        return 0
    else:
        print(f"\n{RED}❌ SOME CHECKS FAILED{RESET}")
        print(f"\n{YELLOW}Please fix the issues above before starting integration.{RESET}")
        print(f"\n{BLUE}Common fixes:{RESET}")
        print(f"• Start Odoo: Run Odoo server on port 8069")
        print(f"• Start Backend: cd backend && uvicorn backend.main:app --reload")
        print(f"• Check .env: Ensure all environment variables are set")
        print(f"• Run migrations: python backend/migrations/add_odoo_po_id_column.py")
        print(f"• Load sample data: Ensure Odoo has vendors, products, and POs")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Verification cancelled by user{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Verification failed with error: {e}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
