"""
Test Tool Integration Fixes
Tests that PriceAnalysisAgent and ComplianceCheckAgent can call tools without parameter errors
"""

import asyncio
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.agents.orchestrator import initialize_orchestrator_with_agents


async def test_price_analysis_tool_calls():
    """Test PriceAnalysisAgent can call tools successfully"""
    print("\n" + "="*60)
    print("TEST 1: PriceAnalysisAgent Tool Integration")
    print("="*60)
    
    # Initialize orchestrator
    orch = initialize_orchestrator_with_agents()
    price_agent = orch.specialized_agents.get("price_analysis")
    
    if not price_agent:
        print("[FAIL] PriceAnalysisAgent not found in orchestrator")
        return False
    
    # Test data
    test_request = "Analyze pricing for laptop purchase"
    pr_data = {
        "pr_number": "PR-TEST-001",
        "department": "IT",
        "product_name": "Dell Latitude",
        "quoted_price": 1200.00,
        "vendor_name": "Tech Supplies Inc",
        "quantity": 5,
        "category": "Electronics"
    }
    
    try:
        print(f"\nTesting with: {pr_data['product_name']} @ ${pr_data['quoted_price']}")
        print(f"   Vendor: {pr_data['vendor_name']}, Qty: {pr_data['quantity']}")
        
        # Execute agent with combined input data
        input_data = {
            "request": test_request,
            "pr_data": pr_data
        }
        result = await price_agent.execute(input_data)
        
        # Check for tool parameter errors
        if result.get("error"):
            error_msg = str(result["error"])
            if "unexpected keyword argument" in error_msg.lower():
                print(f"\n[FAIL] TOOL PARAMETER ERROR: {error_msg}")
                return False
            elif "got an unexpected keyword" in error_msg.lower():
                print(f"\n[FAIL] TOOL PARAMETER ERROR: {error_msg}")
                return False
        
        print(f"\n[PASS] Agent execution completed without tool parameter errors")
        print(f"   Status: {result.get('status', 'unknown')}")
        print(f"   Confidence: {result.get('confidence', 0):.2f}")
        
        if result.get("recommendation"):
            rec = result["recommendation"]
            print(f"   Recommendation: {rec.get('action', 'N/A')}")
        
        return True
        
    except Exception as e:
        error_msg = str(e)
        if "unexpected keyword argument" in error_msg.lower():
            print(f"\nTOOL PARAMETER ERROR: {e}")
            return False
        print(f"\n️ Execution error (not tool-related): {e}")
        return False


async def test_compliance_check_tool_calls():
    """Test ComplianceCheckAgent can call tools successfully"""
    print("\n" + "="*60)
    print("TEST 2: ComplianceCheckAgent Tool Integration")
    print("="*60)
    
    # Initialize orchestrator
    orch = initialize_orchestrator_with_agents()
    compliance_agent = orch.specialized_agents.get("compliance_check")
    
    if not compliance_agent:
        print("[FAIL] ComplianceCheckAgent not found in orchestrator")
        return False
    
    # Test data
    test_request = "Check compliance for IT purchase"
    pr_data = {
        "pr_number": "PR-TEST-002",
        "department": "IT",
        "amount": 15000.00,
        "vendor_name": "Preferred Tech Corp",
        "category": "Hardware",
        "budget_category": "CAPEX",
        "justification": "Replace aging servers for improved performance",
        "urgency": "Normal"
    }
    
    try:
        print(f"\nTesting with: {pr_data['department']} dept, ${pr_data['amount']:,.2f}")
        print(f"   Vendor: {pr_data['vendor_name']}, Category: {pr_data['budget_category']}")
        
        # Execute agent with combined input data
        input_data = {
            "request": test_request,
            "pr_data": pr_data
        }
        result = await compliance_agent.execute(input_data)
        
        # Check for tool parameter errors
        if result.get("error"):
            error_msg = str(result["error"])
            if "unexpected keyword argument" in error_msg.lower():
                print(f"\n[FAIL] TOOL PARAMETER ERROR: {error_msg}")
                return False
            elif "got an unexpected keyword" in error_msg.lower():
                print(f"\n[FAIL] TOOL PARAMETER ERROR: {error_msg}")
                return False
        
        print(f"\n[PASS] Agent execution completed without tool parameter errors")
        print(f"   Status: {result.get('status', 'unknown')}")
        print(f"   Compliance Score: {result.get('compliance_score', 0)}/100")
        print(f"   Compliance Level: {result.get('compliance_level', 'unknown')}")
        
        if result.get("violations"):
            violations = result["violations"]
            print(f"   Violations: {len(violations)}")
            for v in violations[:3]:  # Show first 3
                print(f"     - {v.get('type')}: {v.get('message')}")
        
        return True
        
    except Exception as e:
        error_msg = str(e)
        if "unexpected keyword argument" in error_msg.lower():
            print(f"\nTOOL PARAMETER ERROR: {e}")
            return False
        print(f"\n️ Execution error (not tool-related): {e}")
        return False


async def main():
    """Run all tool integration tests"""
    print("\n" + "="*60)
    print("TOOL INTEGRATION FIX VALIDATION")
    print("Testing: PriceAnalysisAgent & ComplianceCheckAgent")
    print("="*60)
    
    results = []
    
    # Test 1: Price Analysis
    try:
        result1 = await test_price_analysis_tool_calls()
        results.append(("PriceAnalysisAgent", result1))
    except Exception as e:
        print(f"\n[FAIL] PriceAnalysisAgent test failed: {e}")
        results.append(("PriceAnalysisAgent", False))
    
    # Test 2: Compliance Check
    try:
        result2 = await test_compliance_check_tool_calls()
        results.append(("ComplianceCheckAgent", result2))
    except Exception as e:
        print(f"\n[FAIL] ComplianceCheckAgent test failed: {e}")
        results.append(("ComplianceCheckAgent", False))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for agent_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status}: {agent_name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\nSUCCESS: All tool parameter fixes validated successfully!")
        return True
    else:
        print("\nFAILURE: Some tests failed - review errors above")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
