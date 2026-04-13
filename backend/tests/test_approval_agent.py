"""
Test ApprovalRoutingAgent
Sprint 2 Day 1: Comprehensive testing of approval routing
"""

import asyncio
import requests
import json

BASE_URL = "http://localhost:5000"


def test_approval_routing_direct():
    """Test direct approval routing endpoint"""
    print("\n" + "="*60)
    print("TEST 1: Direct Approval Routing (Low Amount - Manager Level)")
    print("="*60)
    
    response = requests.post(
        f"{BASE_URL}/api/agentic/approval/route",
        json={
            "request": "Route this PR for approval",
            "pr_data": {
                "pr_number": "PR-2026-0001",
                "department": "IT",
                "budget": 5000,
                "requester_name": "John Doe",
                "description": "New laptops for team",
                "priority_level": "High"
            }
        }
    )
    
    print(f"\nStatus Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Agent: {data['agent']}")
        print(f"Status: {data['status']}")
        print(f"\nDecision:")
        print(json.dumps(data.get('decision'), indent=2))
        print(f"\nResult:")
        print(json.dumps(data.get('result'), indent=2))
    else:
        print(f"Error: {response.text}")


def test_high_amount_approval():
    """Test high amount requiring VP approval"""
    print("\n" + "="*60)
    print("TEST 2: High Amount Approval (VP Level Required)")
    print("="*60)
    
    response = requests.post(
        f"{BASE_URL}/api/agentic/approval/route",
        json={
            "request": "Route this high-value PR",
            "pr_data": {
                "pr_number": "PR-2026-0002",
                "department": "Finance",
                "budget": 75000,
                "requester_name": "Sarah Johnson",
                "description": "Enterprise software licenses",
                "priority_level": "Critical"
            }
        }
    )
    
    print(f"\nStatus Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Agent: {data['agent']}")
        print(f"Status: {data['status']}")
        print(f"\nDecision:")
        print(json.dumps(data.get('decision'), indent=2))
        print(f"\nResult:")
        print(json.dumps(data.get('result'), indent=2))
    else:
        print(f"Error: {response.text}")


def test_orchestrator_routing():
    """Test orchestrator intelligent routing to approval agent"""
    print("\n" + "="*60)
    print("TEST 3: Orchestrator Intelligent Routing")
    print("="*60)
    
    response = requests.post(
        f"{BASE_URL}/api/agentic/execute",
        json={
            "request": "Who should approve this HR purchase requisition?",
            "pr_data": {
                "pr_number": "PR-2026-0003",
                "department": "HR",
                "budget": 25000,
                "requester_name": "Mike Williams",
                "description": "Recruitment platform subscription"
            }
        }
    )
    
    print(f"\nStatus Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Agent Routed To: {data['agent']}")
        print(f"Status: {data['status']}")
        print(f"\nDecision:")
        print(json.dumps(data.get('decision'), indent=2))
        print(f"\nResult:")
        print(json.dumps(data.get('result'), indent=2))
    else:
        print(f"Error: {response.text}")


def test_unknown_department():
    """Test approval request for unconfigured department"""
    print("\n" + "="*60)
    print("TEST 4: Unconfigured Department (Should Escalate)")
    print("="*60)
    
    response = requests.post(
        f"{BASE_URL}/api/agentic/approval/route",
        json={
            "request": "Route this PR",
            "pr_data": {
                "pr_number": "PR-2026-0004",
                "department": "Legal",  # Not in seed data
                "budget": 15000,
                "requester_name": "Anna Smith"
            }
        }
    )
    
    print(f"\nStatus Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Agent: {data['agent']}")
        print(f"Status: {data['status']}")
        print(f"\nDecision:")
        print(json.dumps(data.get('decision'), indent=2))
        print(f"\nResult:")
        print(json.dumps(data.get('result'), indent=2))
    else:
        print(f"Error: {response.text}")


def test_agent_registration():
    """Test that ApprovalRoutingAgent is registered"""
    print("\n" + "="*60)
    print("TEST 5: Agent Registration Status")
    print("="*60)
    
    response = requests.get(f"{BASE_URL}/api/agentic/agents")
    
    print(f"\nStatus Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total Agents: {data['count']}")
        
        for agent in data['agents']:
            print(f"\n  Agent: {agent['name']}")
            print(f"  Type: {agent['type']}")
            print(f"  Status: {agent['status']}")
            print(f"  Tools: {agent['tools_count']}")
            print(f"  Decisions: {agent['decision_history_count']}")
    else:
        print(f"Error: {response.text}")


def test_system_status():
    """Test overall system status"""
    print("\n" + "="*60)
    print("TEST 6: System Status")
    print("="*60)
    
    response = requests.get(f"{BASE_URL}/api/agentic/status")
    
    print(f"\nStatus Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"System: {data.get('system')}")
        print(f"Version: {data.get('version')}")
        print(f"\nAgent Status:")
        print(json.dumps(data.get('agent_status'), indent=2))
    else:
        print(f"Error: {response.text}")


if __name__ == "__main__":
    print("\nSPRINT 2 - APPROVAL ROUTING AGENT TESTS")
    print("="*60)
    
    tests = [
        test_approval_routing_direct,
        test_high_amount_approval,
        test_orchestrator_routing,
        test_unknown_department,
        test_agent_registration,
        test_system_status
    ]
    
    for test in tests:
        try:
            test()
        except requests.exceptions.ConnectionError:
            print("\nERROR: Cannot connect to backend at http://localhost:5000")
            print("   Make sure the backend is running: uvicorn backend.main:app --reload")
            break
        except Exception as e:
            print(f"\nTest failed with error: {e}")
    
    print("\n" + "="*60)
    print("ALL TESTS COMPLETED")
    print("="*60)
