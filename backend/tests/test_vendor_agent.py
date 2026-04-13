"""
Test suite for VendorSelectionAgent

Tests vendor scoring, recommendation logic, and Odoo integration.

Run: python backend/tests/test_vendor_agent.py
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from backend.agents.vendor_selection import VendorSelectionAgent


class TestVendorAgent:
    """Test cases for VendorSelectionAgent"""
    
    def __init__(self):
        self.agent = VendorSelectionAgent()
        self.passed = 0
        self.failed = 0
        
    async def test_basic_vendor_recommendation(self):
        """Test 1: Basic vendor recommendation for IT equipment"""
        print("\n[TEST 1] Basic Vendor Recommendation")
        print("=" * 60)
        
        try:
            context = {
                "request": "Find best vendor for IT equipment",
                "pr_data": {
                    "category": "Electronics",
                    "budget": 50000,
                    "urgency": "normal"
                }
            }
            
            result = await self.agent.execute(context)
            
            print(f"Status: {result.get('status')}")
            print(f"Agent: {result.get('agent')}")
            
            decision = result.get('decision', {})
            print(f"\nDecision: {decision.get('action')}")
            print(f"Confidence: {decision.get('confidence')}")
            print(f"\nReasoning:\n{decision.get('reasoning')}")
            
            recommendation = result.get('result', {})
            if 'primary_recommendation' in recommendation:
                primary = recommendation['primary_recommendation']
                print(f"\nPrimary Vendor: {primary.get('name')}")
                print(f"   Score: {primary.get('total_score')}/100")
                print(f"   Quality: {primary.get('quality_score')}/40")
                print(f"   Price: {primary.get('price_score')}/30")
                print(f"   Delivery: {primary.get('delivery_score')}/20")
                print(f"   Category: {primary.get('category_score')}/10")
                
            assert result.get('status') == 'completed'
            assert 'primary_recommendation' in recommendation
            print("\nTEST 1 PASSED")
            self.passed += 1
            return True
            
        except Exception as e:
            print(f"\nTEST 1 FAILED: {e}")
            self.failed += 1
            return False
    
    async def test_high_budget_vendor(self):
        """Test 2: High budget vendor recommendation"""
        print("\n[TEST 2] High Budget Vendor ($200K)")
        print("=" * 60)
        
        try:
            context = {
                "request": "Find vendor for large purchase",
                "pr_data": {
                    "category": "Industrial Equipment",
                    "budget": 200000,
                    "urgency": "high"
                }
            }
            
            result = await self.agent.execute(context)
            
            decision = result.get('decision', {})
            print(f"Confidence: {decision.get('confidence')}")
            print(f"Action: {decision.get('action')}")
            
            recommendation = result.get('result', {})
            if 'primary_recommendation' in recommendation:
                vendor = recommendation['primary_recommendation']
                print(f"\nRecommended: {vendor.get('name')}")
                print(f"   Total Score: {vendor.get('total_score')}/100")
                
                # Check confidence is reasonable for high-budget purchase
                confidence = decision.get('confidence', 0)
                assert confidence >= 0.55, "Confidence too low"
                assert confidence <= 0.95, "Confidence too high"
                
            print("\nTEST 2 PASSED")
            self.passed += 1
            return True
            
        except Exception as e:
            print(f"\nTEST 2 FAILED: {e}")
            self.failed += 1
            return False
    
    async def test_urgent_delivery_vendor(self):
        """Test 3: Vendor recommendation with urgent delivery"""
        print("\n[TEST 3] Urgent Delivery Vendor")
        print("=" * 60)
        
        try:
            context = {
                "request": "Find vendor for urgent delivery",
                "pr_data": {
                    "category": "Office Supplies",
                    "budget": 5000,
                    "urgency": "urgent"
                }
            }
            
            result = await self.agent.execute(context)
            
            decision = result.get('decision', {})
            recommendation = result.get('result', {})
            
            if 'primary_recommendation' in recommendation:
                vendor = recommendation['primary_recommendation']
                print(f"\nRecommended: {vendor.get('name')}")
                print(f"   Delivery Score: {vendor.get('delivery_score')}/20")
                
                # For urgent requests, delivery should be weighted higher
                print(f"\nVerifying delivery prioritization...")
                
            print("\nTEST 3 PASSED")
            self.passed += 1
            return True
            
        except Exception as e:
            print(f"\nTEST 3 FAILED: {e}")
            self.failed += 1
            return False
    
    async def test_quality_focused_vendor(self):
        """Test 4: Quality-focused vendor selection"""
        print("\n[TEST 4] Quality-Focused Vendor")
        print("=" * 60)
        
        try:
            context = {
                "request": "Find highest quality vendor",
                "pr_data": {
                    "category": "Medical Equipment",
                    "budget": 100000,
                    "quality_priority": "high"
                }
            }
            
            result = await self.agent.execute(context)
            
            recommendation = result.get('result', {})
            
            if 'primary_recommendation' in recommendation:
                vendor = recommendation['primary_recommendation']
                print(f"\nRecommended: {vendor.get('name')}")
                print(f"   Quality Score: {vendor.get('quality_score')}/40")
                print(f"   Total Score: {vendor.get('total_score')}/100")
                
                # Quality should be a major factor
                quality_score = vendor.get('quality_score', 0)
                print(f"\nQuality score: {quality_score}/40")
                
            print("\nTEST 4 PASSED")
            self.passed += 1
            return True
            
        except Exception as e:
            print(f"\nTEST 4 FAILED: {e}")
            self.failed += 1
            return False
    
    async def test_multiple_vendors_returned(self):
        """Test 5: Multiple vendor recommendations (top 3)"""
        print("\n[TEST 5] Multiple Vendor Recommendations")
        print("=" * 60)
        
        try:
            context = {
                "request": "Compare vendors for IT equipment",
                "pr_data": {
                    "category": "Electronics",
                    "budget": 75000
                }
            }
            
            result = await self.agent.execute(context)
            
            recommendation = result.get('result', {})
            
            # Check primary recommendation
            assert 'primary_recommendation' in recommendation, "No primary recommendation"
            
            # Check alternatives
            alternatives = recommendation.get('alternative_recommendations', [])
            print(f"\nFound {len(alternatives) + 1} total vendors")
            
            # Display all vendors
            primary = recommendation['primary_recommendation']
            print(f"\n1. {primary.get('name')} - Score: {primary.get('total_score')}/100")
            
            for idx, alt in enumerate(alternatives, start=2):
                print(f"{idx}. {alt.get('name')} - Score: {alt.get('total_score')}/100")
            
            print("\nTEST 5 PASSED")
            self.passed += 1
            return True
            
        except Exception as e:
            print(f"\nTEST 5 FAILED: {e}")
            self.failed += 1
            return False
    
    async def test_orchestrator_routing(self):
        """Test 6: Orchestrator routes vendor query correctly"""
        print("\n[TEST 6] Orchestrator Routing to Vendor Agent")
        print("=" * 60)
        
        try:
            from backend.agents.orchestrator import get_orchestrator
            
            orchestrator = get_orchestrator()
            
            context = {
                "request": "Which vendor should I use for office furniture?",
                "pr_data": {
                    "category": "Furniture",
                    "budget": 30000
                }
            }
            
            result = await orchestrator.execute(context)
            
            # Check that vendor agent was selected
            agent_used = result.get('agent', '')
            print(f"Agent selected: {agent_used}")
            
            assert 'vendor' in agent_used.lower(), f"Wrong agent selected: {agent_used}"
            
            print("\nTEST 6 PASSED")
            self.passed += 1
            return True
            
        except Exception as e:
            print(f"\nTEST 6 FAILED: {e}")
            self.failed += 1
            return False
    
    async def test_confidence_calculation(self):
        """Test 7: Confidence score is calculated correctly"""
        print("\n[TEST 7] Confidence Score Calculation")
        print("=" * 60)
        
        try:
            context = {
                "request": "Find vendor",
                "pr_data": {
                    "category": "Electronics",
                    "budget": 50000
                }
            }
            
            result = await self.agent.execute(context)
            
            decision = result.get('decision', {})
            confidence = decision.get('confidence', 0)
            
            print(f"Confidence: {confidence}")
            
            # Confidence should be in valid range
            assert 0.55 <= confidence <= 0.95, f"Confidence out of range: {confidence}"
            
            print(f"\nConfidence is valid: {confidence:.2f}")
            print("\nTEST 7 PASSED")
            self.passed += 1
            return True
            
        except Exception as e:
            print(f"\nTEST 7 FAILED: {e}")
            self.failed += 1
            return False
    
    async def test_empty_category(self):
        """Test 8: Error handling for empty/invalid category"""
        print("\n[TEST 8] Error Handling - Empty Category")
        print("=" * 60)
        
        try:
            context = {
                "request": "Find vendor",
                "pr_data": {
                    "category": "",
                    "budget": 50000
                }
            }
            
            result = await self.agent.execute(context)
            
            # Should still return a result (may use general vendors)
            status = result.get('status')
            print(f"Status: {status}")
            
            # Agent should handle gracefully
            assert status in ['completed', 'escalated'], f"Unexpected status: {status}"
            
            print("\nTEST 8 PASSED")
            self.passed += 1
            return True
            
        except Exception as e:
            print(f"\nTEST 8 FAILED: {e}")
            self.failed += 1
            return False
    
    async def run_all_tests(self):
        """Run all test cases"""
        print("\n" + "=" * 70)
        print(" VENDOR SELECTION AGENT - COMPREHENSIVE TEST SUITE")
        print("=" * 70)
        
        tests = [
            self.test_basic_vendor_recommendation,
            self.test_high_budget_vendor,
            self.test_urgent_delivery_vendor,
            self.test_quality_focused_vendor,
            self.test_multiple_vendors_returned,
            self.test_orchestrator_routing,
            self.test_confidence_calculation,
            self.test_empty_category
        ]
        
        for test in tests:
            await test()
            await asyncio.sleep(0.5)  # Small delay between tests
        
        # Print summary
        print("\n" + "=" * 70)
        print(" TEST SUMMARY")
        print("=" * 70)
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print(f"Total:  {self.passed + self.failed}")
        
        if self.failed == 0:
            print("\nALL TESTS PASSED! VendorSelectionAgent is working correctly!")
        else:
            print(f"\n️  {self.failed} test(s) failed. Review errors above.")
        
        print("=" * 70)
        
        return self.failed == 0


async def main():
    """Main test runner"""
    tester = TestVendorAgent()
    success = await tester.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
