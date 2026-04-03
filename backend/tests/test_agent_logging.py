"""
Simple test to demonstrate enhanced agent logging
"""

import asyncio
import logging
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging to show all levels
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Import agents
from backend.agents.budget_verification import BudgetVerificationAgent
from backend.agents.risk_assessment import RiskAssessmentAgent
from backend.agents.vendor_selection import VendorSelectionAgent


async def test_budget_logging():
    """Test budget agent with enhanced logging"""
    print("\n" + "="*70)
    print("TEST: BUDGET VERIFICATION AGENT - ENHANCED LOGGING")
    print("="*70 + "\n")
    
    agent = BudgetVerificationAgent()
    
    result = await agent.execute({
        "request": "Check budget availability",
        "pr_data": {
            "pr_number": "PR-2026-LOG-001",
            "department": "IT",
            "budget": 25000,
            "budget_category": "OPEX",
            "requester_name": "Test User"
        }
    })
    
    print(f"\nResult: {result.get('status')}")
    print(f"Budget Sufficient: {result.get('sufficient')}")
    

async def test_risk_logging():
    """Test risk agent with enhanced logging"""
    print("\n" + "="*70)
    print("TEST: RISK ASSESSMENT AGENT - ENHANCED LOGGING")
    print("="*70 + "\n")
    
    agent = RiskAssessmentAgent()
    
    result = await agent.execute({
        "request": "Assess procurement risks",
        "pr_data": {
            "pr_number": "PR-2026-LOG-002",
            "vendor_name": "Tech Solutions Inc",
            "category": "Electronics",
            "budget": 45000,
            "department": "IT",
            "urgency": "Medium"
        }
    })
    
    print(f"\nResult: {result.get('status')}")
    print(f"Risk Level: {result.get('risk_level')}")
    print(f"Risk Score: {result.get('total_score')}/100")


async def test_vendor_logging():
    """Test vendor agent with enhanced logging"""
    print("\n" + "="*70)
    print("TEST: VENDOR SELECTION AGENT - ENHANCED LOGGING")
    print("="*70 + "\n")
    
    agent = VendorSelectionAgent()
    
    result = await agent.execute({
        "request": "Recommend best vendor",
        "pr_data": {
            "pr_number": "PR-2026-LOG-003",
            "category": "Office Supplies",
            "budget": 5000,
            "quantity": 100,
            "urgency": "Low"
        }
    })
    
    print(f"\nResult: {result.get('status')}")
    if 'primary_recommendation' in result:
        vendor = result['primary_recommendation']
        print(f"Recommended: {vendor.get('vendor_name')} (Score: {vendor.get('score'):.1f}/100)")


async def main():
    """Run all logging tests"""
    
    print("\n" + "="*70)
    print("AGENT LOGGING DEMONSTRATION - REAL-TIME ACTIONS")
    print("="*70)
    print("\nThis test demonstrates:")
    print("  - Real database queries to approval_chains, budget_tracking")
    print("  - Real Odoo API calls (XML-RPC)")
    print("  - Real AI reasoning (GPT-4o-mini)")
    print("  - Enhanced logging showing all intermediate steps")
    print("\n")
    
    try:
        # Test 1: Budget verification
        await test_budget_logging()
        
        # Test 2: Risk assessment  
        await test_risk_logging()
        
        # Test 3: Vendor selection
        await test_vendor_logging()
        
        print("\n" + "="*70)
        print("ALL TESTS COMPLETE - CHECK LOGS ABOVE FOR REAL-TIME ACTIONS")
        print("="*70)
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
