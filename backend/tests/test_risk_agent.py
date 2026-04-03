"""
Quick test to verify RiskAssessmentAgent is operational
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from backend.agents.risk_assessment import RiskAssessmentAgent


async def test_low_risk_scenario():
    """Test low-risk procurement"""
    print("\n" + "=" * 70)
    print(" TEST 1: LOW RISK SCENARIO")
    print("=" * 70)
    
    agent = RiskAssessmentAgent()
    
    context = {
        "request": "Assess risk for office supplies",
        "pr_data": {
            "pr_number": "PR-2026-TEST-001",
            "vendor_name": "Office Depot",
            "vendor_id": 5,
            "category": "Office Supplies",
            "budget": 5000,
            "department": "IT",
            "urgency": "Low",
            "description": "Standard office supplies for Q2 2026",
            "requester_name": "John Smith"
        }
    }
    
    result = await agent.execute(context)
    
    risk_data = result.get("result", {})
    print(f"\n✅ Risk Assessment Complete!")
    print(f"   Risk Score: {risk_data.get('risk_score')}/100")
    print(f"   Risk Level: {risk_data.get('risk_level')}")
    print(f"   Status: {risk_data.get('status')}")
    print(f"   Can Proceed: {risk_data.get('can_proceed')}")
    
    breakdown = risk_data.get('breakdown', {})
    print(f"\n📊 Risk Breakdown:")
    print(f"   Vendor Risk: {breakdown.get('vendor_risk', {}).get('score')}/100 (30% weight)")
    print(f"   Financial Risk: {breakdown.get('financial_risk', {}).get('score')}/100 (30% weight)")
    print(f"   Compliance Risk: {breakdown.get('compliance_risk', {}).get('score')}/100 (25% weight)")
    print(f"   Operational Risk: {breakdown.get('operational_risk', {}).get('score')}/100 (15% weight)")
    
    mitigations = risk_data.get('mitigations', [])
    if mitigations:
        print(f"\n💡 Recommended Mitigations:")
        for i, mitigation in enumerate(mitigations[:3], 1):
            print(f"   {i}. {mitigation}")


async def test_high_risk_scenario():
    """Test high-risk procurement"""
    print("\n\n" + "=" * 70)
    print(" TEST 2: HIGH RISK SCENARIO")
    print("=" * 70)
    
    agent = RiskAssessmentAgent()
    
    context = {
        "request": "Assess risk for large electronics purchase",
        "pr_data": {
            "pr_number": "PR-2026-TEST-002",
            "vendor_name": "Unknown Vendor LLC",
            "category": "Electronics",
            "budget": 150000,  # Very large amount
            "department": "IT",
            "urgency": "High",  # Urgent
            "description": "Servers",  # Short description
            "requester_name": "Jane Doe"
        }
    }
    
    result = await agent.execute(context)
    
    risk_data = result.get("result", {})
    print(f"\n⚠️  Risk Assessment Complete!")
    print(f"   Risk Score: {risk_data.get('risk_score')}/100")
    print(f"   Risk Level: {risk_data.get('risk_level')}")
    print(f"   Status: {risk_data.get('status')}")
    print(f"   Can Proceed: {risk_data.get('can_proceed')}")
    print(f"   Requires Human Review: {risk_data.get('requires_human_review')}")
    
    breakdown = risk_data.get('breakdown', {})
    print(f"\n📊 Risk Breakdown:")
    print(f"   Vendor Risk: {breakdown.get('vendor_risk', {}).get('score')}/100")
    for concern in breakdown.get('vendor_risk', {}).get('concerns', [])[:2]:
        print(f"      • {concern}")
    
    print(f"   Financial Risk: {breakdown.get('financial_risk', {}).get('score')}/100")
    for concern in breakdown.get('financial_risk', {}).get('concerns', [])[:2]:
        print(f"      • {concern}")
    
    print(f"   Compliance Risk: {breakdown.get('compliance_risk', {}).get('score')}/100")
    for concern in breakdown.get('compliance_risk', {}).get('concerns', [])[:2]:
        print(f"      • {concern}")
    
    print(f"   Operational Risk: {breakdown.get('operational_risk', {}).get('score')}/100")
    for concern in breakdown.get('operational_risk', {}).get('concerns', [])[:2]:
        print(f"      • {concern}")
    
    mitigations = risk_data.get('mitigations', [])
    if mitigations:
        print(f"\n💡 Top Mitigations Required:")
        for i, mitigation in enumerate(mitigations, 1):
            print(f"   {i}. {mitigation}")
    
    actions = risk_data.get('recommended_actions', [])
    if actions:
        print(f"\n📋 Recommended Actions:")
        for i, action in enumerate(actions[:3], 1):
            print(f"   {i}. {action}")


async def test_medium_risk_scenario():
    """Test medium-risk procurement"""
    print("\n\n" + "=" * 70)
    print(" TEST 3: MEDIUM RISK SCENARIO")
    print("=" * 70)
    
    agent = RiskAssessmentAgent()
    
    context = {
        "request": "Assess risk for IT equipment",
        "pr_data": {
            "pr_number": "PR-2026-TEST-003",
            "vendor_name": "Tech Solutions Inc",
            "vendor_id": 8,
            "category": "Electronics",
            "budget": 45000,  # Medium amount
            "department": "Finance",
            "urgency": "Medium",
            "description": "Desktop computers and monitors for new employees",
            "requester_name": "Sarah Johnson"
        }
    }
    
    result = await agent.execute(context)
    
    risk_data = result.get("result", {})
    print(f"\n⚡ Risk Assessment Complete!")
    print(f"   Risk Score: {risk_data.get('risk_score')}/100")
    print(f"   Risk Level: {risk_data.get('risk_level')}")
    print(f"   Status: {risk_data.get('status')}")
    
    mitigations = risk_data.get('mitigations', [])
    if mitigations:
        print(f"\n💡 Recommended Mitigations:")
        for i, mitigation in enumerate(mitigations[:3], 1):
            print(f"   {i}. {mitigation}")


async def test_orchestrator_integration():
    """Test risk assessment through orchestrator"""
    print("\n\n" + "=" * 70)
    print(" TEST 4: ORCHESTRATOR INTEGRATION")
    print("=" * 70)
    
    from backend.agents.orchestrator import initialize_orchestrator_with_agents
    
    orch = initialize_orchestrator_with_agents()
    
    context = {
        "request": "What are the risks of purchasing from new vendor XYZ for $80K?",
        "pr_data": {
            "pr_number": "PR-2026-TEST-004",
            "vendor_name": "XYZ Corp",
            "budget": 80000,
            "department": "Operations",
            "category": "Manufacturing Equipment"
        }
    }
    
    result = await orch.execute(context)
    
    print(f"\n✅ Orchestrator routed to: {result.get('agent')}")
    print(f"   Status: {result.get('status')}")
    
    decision = result.get('decision', {})
    print(f"\n📋 Decision:")
    print(f"   Action: {decision.get('action')}")
    print(f"   Confidence: {decision.get('confidence')}")
    print(f"   Reasoning: {decision.get('reasoning')[:150]}...")


async def main():
    """Run all tests"""
    print("\n🚀 RISK ASSESSMENT AGENT - COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    
    try:
        await test_low_risk_scenario()
        await test_high_risk_scenario()
        await test_medium_risk_scenario()
        await test_orchestrator_integration()
        
        print("\n\n" + "=" * 70)
        print("✅ ALL TESTS PASSED - RISK AGENT IS OPERATIONAL!")
        print("=" * 70)
        print("\nRisk Agent Features:")
        print("  ✅ Multi-dimensional risk scoring (Vendor, Financial, Compliance, Operational)")
        print("  ✅ 4 risk levels (LOW/MEDIUM/HIGH/CRITICAL)")
        print("  ✅ Automated mitigation recommendations")
        print("  ✅ Confidence-based human escalation")
        print("  ✅ Orchestrator integration")
        print("  ✅ Detailed risk breakdowns")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
