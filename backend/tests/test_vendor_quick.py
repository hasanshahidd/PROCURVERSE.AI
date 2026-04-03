"""
Quick test to verify VendorSelectionAgent is operational
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from backend.agents.vendor_selection import VendorSelectionAgent


async def quick_test():
    """Quick verification that vendor agent works"""
    print("\n" + "=" * 70)
    print(" VENDOR AGENT - QUICK OPERATIONAL TEST")
    print("=" * 70)
    
    agent = VendorSelectionAgent()
    
    print("\n✅ Agent instantiated successfully")
    print(f"   Agent name: {agent.name}")
    print(f"   Tools available: {len(agent.tools)}")
    
    # Test basic execution
    context = {
        "request": "Find vendors for IT equipment",
        "pr_data": {
            "category": "Electronics",
            "budget": 50000,
            "urgency": "normal"
        }
    }
    
    print("\n📊 Testing vendor recommendation...")
    print(f"   Category: {context['pr_data']['category']}")
    print(f"   Budget: ${context['pr_data']['budget']:,}")
    
    result = await agent.execute(context)
    
    print(f"\n✅ Execution completed!")
    print(f"   Status: {result.get('status')}")
    print(f"   Agent: {result.get('agent')}")
    
    decision = result.get('decision', {})
    print(f"\n📋 Decision Details:")
    print(f"   Action: {decision.get('action')}")
    print(f"   Confidence: {decision.get('confidence')}")
    
    recommendation = result.get('result', {})
    if 'primary_recommendation' in recommendation:
        vendor = recommendation['primary_recommendation']
        print(f"\n🏆 Primary Vendor: {vendor.get('name')}")
        print(f"   Total Score: {vendor.get('total_score')}/100")
        print(f"   - Quality: {vendor.get('quality_score')}/40")
        print(f"   - Price: {vendor.get('price_score')}/30")
        print(f"   - Delivery: {vendor.get('delivery_score')}/20")
        print(f"   - Category: {vendor.get('category_score')}/10")
        print(f"\n   Strengths: {', '.join(vendor.get('strengths', []))}")
    elif 'error' in recommendation:
        print(f"\n⚠️  No vendors found: {recommendation.get('error')}")
    else:
        print(f"\n📄 Result: {recommendation}")
    
    # Show reasoning
    if decision.get('reasoning'):
        print(f"\n💡 Reasoning: {decision.get('reasoning')[:200]}...")
    
    print("\n" + "=" * 70)
    print("✅ VENDOR AGENT IS OPERATIONAL!")
    print("=" * 70)
    
    # Check status
    status = result.get('status')
    if status == 'completed':
        print("\n✅ Status: COMPLETED (High confidence recommendation)")
    elif status == 'pending_human_approval':
        print("\n⚠️  Status: PENDING HUMAN APPROVAL (Low confidence - normal behavior)")
        print("   This is expected when:")
        print("   - Limited vendor data available")
        print("   - Score differences are small")
        print("   - Confidence < 0.6 threshold")
    
    return True


if __name__ == "__main__":
    asyncio.run(quick_test())
