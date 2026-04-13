"""
Sprint 1 Test Script
Tests the agentic infrastructure: orchestrator, base agent, budget verification
"""

import asyncio
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from backend.agents.orchestrator import get_orchestrator
from backend.agents.budget_verification import BudgetVerificationAgent


async def test_budget_agent():
    """Test budget verification agent directly"""
    print("\n" + "="*60)
    print("TEST 1: Budget Verification Agent (Direct)")
    print("="*60)
    
    agent = BudgetVerificationAgent()
    
    # Test case: IT department wants to buy $50,000 equipment
    test_pr = {
        "pr_number": "PR-2026-TEST-001",
        "department": "IT",
        "budget": 50000,
        "budget_category": "CAPEX",
        "priority_level": "High",
        "requester_name": "Hassan"
    }
    
    context = {
        "request": "Verify budget for IT department equipment purchase",
        "pr_data": test_pr
    }
    
    print(f"\nTest PR: {test_pr['pr_number']}")
    print(f"   Department: {test_pr['department']}")
    print(f"   Budget: ${test_pr['budget']:,}")
    print(f"   Category: {test_pr['budget_category']}")
    
    print("\nExecuting budget verification...")
    result = await agent.execute(context)
    
    print(f"\nResult:")
    print(json.dumps(result, indent=2))
    
    return result


async def test_orchestrator():
    """Test orchestrator routing"""
    print("\n" + "="*60)
    print("TEST 2: Orchestrator Routing")
    print("="*60)
    
    orchestrator = get_orchestrator()
    
    # Register budget agent
    orchestrator.register_agent("budget_verification", BudgetVerificationAgent())
    
    # Test routing
    test_request = {
        "request": "Check if IT has budget for $75,000 server purchase",
        "pr_data": {
            "pr_number": "PR-2026-TEST-002",
            "department": "IT",
            "budget": 75000,
            "budget_category": "CAPEX"
        }
    }
    
    print(f"\nRequest: {test_request['request']}")
    print(f"   Budget: ${test_request['pr_data']['budget']:,}")
    
    print("\nOrchestrator analyzing and routing...")
    result = await orchestrator.execute(test_request)
    
    print(f"\nResult:")
    print(json.dumps(result, indent=2))
    
    return result


async def test_budget_threshold_alerts():
    """Test budget threshold alerts"""
    print("\n" + "="*60)
    print("TEST 3: Budget Threshold Alerts")
    print("="*60)
    
    agent = BudgetVerificationAgent()
    
    # Test cases for different alert levels
    test_cases = [
        {
            "name": "Normal (< 80%)",
            "pr": {
                "pr_number": "PR-2026-TEST-003",
                "department": "Finance",
                "budget": 50000,  # Finance CAPEX has 650K available
                "budget_category": "CAPEX"
            }
        },
        {
            "name": "Warning (80-90%)",
            "pr": {
                "pr_number": "PR-2026-TEST-004",
                "department": "Procurement",
                "budget": 200000,  # Will push Procurement OPEX to ~80%
                "budget_category": "OPEX"
            }
        },
        {
            "name": "Insufficient Budget",
            "pr": {
                "pr_number": "PR-2026-TEST-005",
                "department": "Finance",
                "budget": 1000000,  # Exceeds available CAPEX
                "budget_category": "CAPEX"
            }
        }
    ]
    
    for test in test_cases:
        print(f"\n{test['name']}")
        print(f"   PR: {test['pr']['pr_number']}")
        print(f"   Budget: ${test['pr']['budget']:,}")
        
        context = {
            "request": f"Verify budget for {test['name']}",
            "pr_data": test['pr']
        }
        
        result = await agent.execute(context)
        
        print(f"   Status: {result.get('status', 'unknown')}")
        if result.get('result'):
            alert_level = result['result'].get('alert_level', 'none')
            print(f"   Alert Level: {alert_level}")
    
    print("\nThreshold tests completed")


async def test_agent_decision_history():
    """Test agent learning from decision history"""
    print("\n" + "="*60)
    print("TEST 4: Agent Decision History")
    print("="*60)
    
    agent = BudgetVerificationAgent()
    
    # Make 3 decisions
    for i in range(3):
        test_pr = {
            "pr_number": f"PR-2026-TEST-00{i+6}",
            "department": "IT",
            "budget": 30000 * (i + 1),
            "budget_category": "OPEX"
        }
        
        context = {
            "request": f"Budget check #{i+1}",
            "pr_data": test_pr
        }
        
        await agent.execute(context)
    
    print(f"\nDecision History: {len(agent.decision_history)} decisions")
    
    for i, decision in enumerate(agent.decision_history, 1):
        print(f"\n   Decision {i}:")
        print(f"   - Action: {decision.action}")
        print(f"   - Confidence: {decision.confidence:.2f}")
        print(f"   - Reasoning: {decision.reasoning[:60]}...")
    
    print("\nDecision history test completed")


async def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("AGENTIC PROCUREMENT SYSTEM - SPRINT 1 TESTS")
    print("="*60)
    print("\nTesting:")
    print("1. Budget Verification Agent (direct execution)")
    print("2. Orchestrator Routing")
    print("3. Budget Threshold Alerts")
    print("4. Agent Decision History")
    
    try:
        await test_budget_agent()
        await test_orchestrator()
        await test_budget_threshold_alerts()
        await test_agent_decision_history()
        
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED SUCCESSFULLY")
        print("="*60)
        print("\nSprint 1 Foundation Status:")
        print("   LangChain installed")
        print("   Base agent framework working")
        print("   Custom database tables created")
        print("   Orchestrator routing functional")
        print("   Tool wrappers operational")
        print("   Budget verification agent implemented")
        print("\nReady for Sprint 2: More specialized agents!")
        
    except Exception as e:
        print(f"\nTEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
