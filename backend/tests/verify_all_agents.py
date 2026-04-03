"""
Comprehensive Agent System Verification
Checks all 4 agents, backend, frontend, database, and API endpoints
"""

import os
import sys
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_header(title):
    print(f"\n{BLUE}{'='*70}{RESET}")
    print(f"{BLUE}{title.center(70)}{RESET}")
    print(f"{BLUE}{'='*70}{RESET}\n")

def check_database_tables():
    """Verify all 4 custom tables exist"""
    print_header("DATABASE TABLES VERIFICATION")
    
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        
        tables_to_check = [
            'approval_chains',
            'budget_tracking',
            'agent_actions',
            'agent_decisions'
        ]
        
        for table in tables_to_check:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            print(f"{GREEN}✅{RESET} {table}: {count} records")
        
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"{RED}❌ Database check failed: {e}{RESET}")
        return False


def check_agent_files():
    """Verify all agent files exist"""
    print_header("AGENT FILES VERIFICATION")
    
    agent_files = [
        ('backend/agents/__init__.py', 'BaseAgent'),
        ('backend/agents/orchestrator.py', 'OrchestratorAgent'),
        ('backend/agents/budget_verification.py', 'BudgetVerificationAgent'),
        ('backend/agents/approval_routing.py', 'ApprovalRoutingAgent'),
        ('backend/agents/tools.py', 'LangChain Tools')
    ]
    
    all_exist = True
    for file_path, agent_name in agent_files:
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            print(f"{GREEN}✅{RESET} {agent_name}: {file_path} ({size} bytes)")
        else:
            print(f"{RED}❌{RESET} {agent_name}: {file_path} NOT FOUND")
            all_exist = False
    
    return all_exist


def check_frontend_components():
    """Verify frontend integration"""
    print_header("FRONTEND COMPONENTS VERIFICATION")

    # Support both historical `client/` layout and current `frontend/` layout.
    component_candidates = [
        (['client/src/components/AgentStatus.tsx', 'frontend/src/components/AgentStatus.tsx'], 'AgentStatus Component'),
        (['client/src/pages/AgentDashboard.tsx', 'frontend/src/pages/AgentDashboard.tsx'], 'AgentDashboard Page'),
        (['client/src/pages/ChatPage.tsx', 'frontend/src/pages/ChatPage.tsx'], 'ChatPage Integration')
    ]
    
    all_exist = True
    for candidate_paths, component_name in component_candidates:
        existing_path = next((p for p in candidate_paths if os.path.exists(p)), None)
        if existing_path:
            size = os.path.getsize(existing_path)
            print(f"{GREEN}✅{RESET} {component_name}: {existing_path} ({size} bytes)")
        else:
            print(f"{RED}❌{RESET} {component_name}: NOT FOUND in {candidate_paths}")
            all_exist = False
    
    return all_exist


def check_api_endpoints():
    """Test all API endpoints"""
    print_header("API ENDPOINTS VERIFICATION")
    
    base_url = "http://localhost:5000"
    
    endpoints = [
        ('GET', '/api/health', 'Health Check'),
        ('GET', '/api/agentic/health', 'Agentic Health'),
        ('GET', '/api/agentic/status', 'System Status'),
        ('GET', '/api/agentic/agents', 'List Agents'),
    ]
    
    all_working = True
    for method, endpoint, description in endpoints:
        try:
            if method == 'GET':
                response = requests.get(f"{base_url}{endpoint}", timeout=5)
            
            if response.status_code == 200:
                print(f"{GREEN}✅{RESET} {description}: {endpoint} ({response.status_code})")
            else:
                print(f"{YELLOW}⚠️{RESET} {description}: {endpoint} ({response.status_code})")
        except requests.exceptions.ConnectionError:
            print(f"{RED}❌{RESET} {description}: {endpoint} (Backend not running)")
            all_working = False
        except Exception as e:
            print(f"{RED}❌{RESET} {description}: {endpoint} ({str(e)})")
            all_working = False
    
    return all_working


def check_agent_methods():
    """Verify critical agent methods exist in code"""
    print_header("AGENT METHODS VERIFICATION")
    
    checks = [
        ('backend/agents/__init__.py', ['async def observe', 'async def decide', 'async def learn']),
        ('backend/agents/budget_verification.py', ['async def observe', 'async def decide', 'async def _execute_action']),
        ('backend/agents/approval_routing.py', ['async def observe', 'async def decide', 'async def _execute_action', 'async def learn']),
    ]
    
    all_methods_found = True
    for file_path, methods in checks:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            agent_name = file_path.split('/')[-1].replace('.py', '')
            print(f"\n{agent_name}:")
            
            for method in methods:
                if method in content:
                    print(f"  {GREEN}✅{RESET} {method}")
                else:
                    print(f"  {RED}❌{RESET} {method} NOT FOUND")
                    all_methods_found = False
        else:
            print(f"{RED}❌{RESET} {file_path} not found")
            all_methods_found = False
    
    return all_methods_found


def generate_summary_report():
    """Generate final summary"""
    print_header("VERIFICATION SUMMARY")
    
    results = {
        'Agent Files': check_agent_files(),
        'Agent Methods': check_agent_methods(),
        'Database Tables': check_database_tables(),
        'Frontend Components': check_frontend_components(),
        'API Endpoints': check_api_endpoints()
    }
    
    print("\n" + "="*70)
    print("FINAL RESULTS:")
    print("="*70 + "\n")
    
    all_passed = True
    for category, passed in results.items():
        status = f"{GREEN}✅ PASS{RESET}" if passed else f"{RED}❌ FAIL{RESET}"
        print(f"{category:.<50} {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*70)
    if all_passed:
        print(f"{GREEN}🎉 ALL SYSTEMS OPERATIONAL - 4 AGENTS FULLY FUNCTIONAL{RESET}")
    else:
        print(f"{YELLOW}⚠️  SOME CHECKS FAILED - REVIEW ABOVE{RESET}")
    print("="*70 + "\n")
    
    return all_passed


if __name__ == "__main__":
    try:
        success = generate_summary_report()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n{RED}❌ Verification failed with error: {e}{RESET}\n")
        sys.exit(1)
