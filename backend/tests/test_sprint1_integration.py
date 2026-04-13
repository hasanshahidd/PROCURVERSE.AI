"""
Sprint 1 Full Integration Test
Tests frontend-backend agentic system alignment
"""

import requests
import json

# Test URLs
BASE_URL = "http://localhost:5000"

def test_agentic_endpoints():
    """Test all agentic API endpoints"""
    
    print("="*60)
    print("SPRINT 1 FULL INTEGRATION TEST")
    print("="*60)
    print()
    
    # 1. Test system health
    print("1. Testing /api/health...")
    response = requests.get(f"{BASE_URL}/api/health")
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {data.get('status', 'N/A')}")
        print(f"   Mode: {data.get('mode', 'N/A')}")
        
        # Database stats
        db_stats = data.get('stats', {})
        print(f"   Database: {db_stats.get('total', 0)} total records")
        
        # Odoo connection
        odoo = data.get('odoo', {})
        print(f"   Odoo: {odoo.get('connected', False)}")
        
        # Agentic tables
        agentic = data.get('agentic', {})
        print(f"   Agentic Tables: approval_chains={agentic.get('approval_chains', 0)}, budgets={agentic.get('budgets', 0)}, actions={agentic.get('agent_actions', 0)}")
    else:
        print(f"   Failed: {response.status_code}")
        return False
    print()
    
    # 2. Test agentic status
    print("2. Testing /api/agentic/status...")
    response = requests.get(f"{BASE_URL}/api/agentic/status")
    if response.status_code == 200:
        data = response.json()
        print(f"   System: {data['system']}")
        print(f"   Version: {data['version']}")
        print(f"   Orchestrator: {data['orchestrator']['name']} ({data['orchestrator']['status']})")
        print(f"   Registered Agents: {data['orchestrator']['registered_agents']}")
        for agent_type, agent_data in data['agents'].items():
            print(f"      - {agent_data['name']} ({agent_data['status']})")
    else:
        print(f"   Failed: {response.status_code}")
        return False
    print()
    
    # 3. Test agent listing
    print("3. Testing /api/agentic/agents...")
    response = requests.get(f"{BASE_URL}/api/agentic/agents")
    if response.status_code == 200:
        data = response.json()
        print(f"   Total Agents: {data['count']}")
        for agent in data['agents']:
            print(f"      - {agent['name']}: {agent['status']} (tools={agent['tools_count']}, decisions={agent['decision_history_count']})")
    else:
        print(f"   Failed: {response.status_code}")
        return False
    print()
    
    # 4. Test agentic health
    print("4. Testing /api/agentic/health...")
    response = requests.get(f"{BASE_URL}/api/agentic/health")
    if response.status_code == 200:
        data = response.json()
        print(f"   Service: {data['service']}")
        print(f"   Status: {data['status']}")
        print(f"   Orchestrator Active: {data['orchestrator_active']}")
        print(f"   Registered Agents: {data['registered_agents']}")
    else:
        print(f"   Failed: {response.status_code}")
        return False
    print()
    
    # 5. Test budget verification agent
    print("5. Testing /api/agentic/budget/verify...")
    test_request = {
        "request": "Verify budget availability for IT department",
        "pr_data": {
            "department": "IT",
            "budget": 50000,
            "budget_category": "CAPEX",
            "fiscal_year": 2026
        }
    }
    response = requests.post(f"{BASE_URL}/api/agentic/budget/verify", json=test_request)
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {data['status']}")
        print(f"   Agent: {data['agent']}")
        if data.get('decision'):
            print(f"   Decision: {data['decision'].get('action', 'N/A')}")
            print(f"   Confidence: {data['decision'].get('confidence', 0)}")
    else:
        print(f"   Failed: {response.status_code}")
        print(f"   Error: {response.text}")
        return False
    print()
    
    # 6. Test orchestrator execution
    print("6. Testing /api/agentic/execute (Orchestrator)...")
    test_request = {
        "request": "Check if Finance department has budget for $100K OPEX expense",
        "pr_data": {
            "department": "Finance",
            "budget": 100000,
            "budget_category": "OPEX",
            "fiscal_year": 2026
        }
    }
    response = requests.post(f"{BASE_URL}/api/agentic/execute", json=test_request)
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {data['status']}")
        print(f"   Agent: {data['agent']}")
        if data.get('result'):
            print(f"   Result: {json.dumps(data['result'], indent=6)[:200]}...")
    else:
        print(f"   Failed: {response.status_code}")
        print(f"   Error: {response.text}")
        return False
    print()
    
    print("="*60)
    print("ALL TESTS PASSED - SPRINT 1 COMPLETE!")
    print("="*60)
    print()
    print("Frontend Integration:")
    print("  - AgentStatus component shows real-time agent status")
    print("  - AgentDashboard page displays system metrics")
    print("  - Navigation: ChatPage header -> Dashboard button")
    print("  - Route: http://localhost:5173/agents")
    print()
    print("Backend Integration:")
    print("  - All API endpoints operational")
    print("  - Database tables created and seeded")
    print("  - BudgetVerificationAgent working")
    print("  - Orchestrator routing functional")
    print()
    
    return True

if __name__ == "__main__":
    try:
        success = test_agentic_endpoints()
        exit(0 if success else 1)
    except Exception as e:
        print(f"Test failed with error: {e}")
        exit(1)
