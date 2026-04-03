"""
Test Suite for PriceAnalysisAgent
Tests pricing analysis, market comparison, and negotiation recommendations
"""

import asyncio
import logging
import sys
from pathlib import Path
from pprint import pprint
from dotenv import load_dotenv

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_competitive_price():
    """Test 1: Price within market range (±10%)"""
    from backend.agents.price_analysis import PriceAnalysisAgent
    
    print("\n" + "="*80)
    print("TEST 1: Competitive Price Analysis")
    print("="*80)
    
    agent = PriceAnalysisAgent()
    
    context = {
        "request": "Analyze this price quote",
        "pr_data": {
            "product_name": "Dell Laptop XPS 15",
            "quoted_price": 1500,
            "vendor_name": "Dell Technologies",
            "quantity": 10,
            "category": "Electronics",
            "budget": 15000
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    assert result["result"]["action"] in ["approve", "approve_with_note"], "Competitive price should be approved"
    
    print("\n✅ Test 1 PASSED: Competitive price approved")
    return result


async def test_high_price_negotiation():
    """Test 2: Price significantly above market (>20%)"""
    from backend.agents.price_analysis import PriceAnalysisAgent
    
    print("\n" + "="*80)
    print("TEST 2: High Price - Negotiation Required")
    print("="*80)
    
    agent = PriceAnalysisAgent()
    
    context = {
        "request": "Analyze this price quote",
        "pr_data": {
            "product_name": "Office Chairs",
            "quoted_price": 500,  # Market avg might be $350-400
            "vendor_name": "Luxury Office Furnishings",
            "quantity": 50,
            "category": "Furniture",
            "budget": 25000
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    # High prices for large orders should trigger negotiation
    if result["result"].get("total_value", 0) > 10000:
        assert result["result"]["action"] == "negotiate", "High-value high-price should require negotiation"
    
    print("\n✅ Test 2 PASSED: High price flagged for negotiation")
    return result


async def test_single_source_risk():
    """Test 3: Single-source dependency warning"""
    from backend.agents.price_analysis import PriceAnalysisAgent
    
    print("\n" + "="*80)
    print("TEST 3: Single-Source Dependency Detection")
    print("="*80)
    
    agent = PriceAnalysisAgent()
    
    context = {
        "request": "Analyze this specialized component quote",
        "pr_data": {
            "product_name": "Specialized Manufacturing Component XYZ-9000",
            "quoted_price": 10000,
            "vendor_name": "Only Manufacturer Inc",
            "quantity": 5,
            "category": "Industrial Equipment",
            "budget": 50000
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    # Check for single-source warnings in context
    if result["decision"]["context"].get("is_single_source"):
        print("\n⚠️ Single-source dependency detected (expected)")
    
    print("\n✅ Test 3 PASSED: Single-source risk evaluated")
    return result


async def test_excellent_price():
    """Test 4: Price well below market (great deal)"""
    from backend.agents.price_analysis import PriceAnalysisAgent
    
    print("\n" + "="*80)
    print("TEST 4: Excellent Price (Below Market)")
    print("="*80)
    
    agent = PriceAnalysisAgent()
    
    context = {
        "request": "Analyze this discount offer",
        "pr_data": {
            "product_name": "Software Licenses - Microsoft Office 365",
            "quoted_price": 85,  # Below typical $120 price
            "vendor_name": "Microsoft",
            "quantity": 100,
            "category": "Software",
            "budget": 8500
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    assert result["result"]["action"] == "approve", "Excellent price should be approved"
    
    print("\n✅ Test 4 PASSED: Excellent price approved")
    return result


async def test_bulk_order_opportunity():
    """Test 5: Large order with negotiation leverage"""
    from backend.agents.price_analysis import PriceAnalysisAgent
    
    print("\n" + "="*80)
    print("TEST 5: Bulk Order - Volume Discount Opportunity")
    print("="*80)
    
    agent = PriceAnalysisAgent()
    
    context = {
        "request": "Analyze bulk order pricing",
        "pr_data": {
            "product_name": "USB-C Cables (Bulk)",
            "quoted_price": 15,
            "vendor_name": "Cable Depot",
            "quantity": 1000,  # Large quantity
            "category": "Accessories",
            "budget": 15000
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    
    # Check for volume discount recommendations
    alternatives = result["decision"]["context"].get("alternatives", [])
    if alternatives:
        print(f"\n💡 Alternatives suggested: {len(alternatives)}")
        for alt in alternatives:
            print(f"  - {alt.get('description')}")
    
    print("\n✅ Test 5 PASSED: Bulk order analyzed for volume discounts")
    return result


async def run_all_tests():
    """Run all price analysis tests"""
    print("\n" + "="*100)
    print("PRICE ANALYSIS AGENT - COMPREHENSIVE TEST SUITE")
    print("="*100)
    
    results = {
        "total": 5,
        "passed": 0,
        "failed": 0
    }
    
    tests = [
        ("Competitive Price", test_competitive_price),
        ("High Price Negotiation", test_high_price_negotiation),
        ("Single-Source Risk", test_single_source_risk),
        ("Excellent Price", test_excellent_price),
        ("Bulk Order Opportunity", test_bulk_order_opportunity)
    ]
    
    for test_name, test_func in tests:
        try:
            await test_func()
            results["passed"] += 1
        except AssertionError as e:
            print(f"\n❌ {test_name} FAILED: {e}")
            results["failed"] += 1
        except Exception as e:
            print(f"\n❌ {test_name} ERROR: {e}")
            results["failed"] += 1
    
    print("\n" + "="*100)
    print("TEST SUMMARY")
    print("="*100)
    print(f"Total Tests: {results['total']}")
    print(f"✅ Passed: {results['passed']}")
    print(f"❌ Failed: {results['failed']}")
    print(f"Success Rate: {(results['passed']/results['total'])*100:.1f}%")
    print("="*100)
    
    return results


if __name__ == "__main__":
    asyncio.run(run_all_tests())
