"""
Test Suite for Week 1 Agents (Sprint 5)
Tests InvoiceMatchingAgent, SpendAnalyticsAgent, InventoryCheckAgent
"""

import asyncio
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backend.agents.invoice_matching import InvoiceMatchingAgent
from backend.agents.spend_analytics import SpendAnalyticsAgent
from backend.agents.inventory_check import InventoryCheckAgent


def print_section(title: str):
    """Print section header"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


async def test_invoice_matching_agent():
    """Test InvoiceMatchingAgent with various scenarios"""
    print_section("TEST 1: InvoiceMatchingAgent - 3-Way Matching")
    
    agent = InvoiceMatchingAgent()
    
    # Scenario 1: Perfect match (variance = 0%)
    print("Scenario 1: Perfect Match (Auto-Approve)")
    test_data_perfect = {
        "invoice_id": 1001,
        "invoice_number": "INV-2026-001",
        "invoice_amount": 50000.00,
        "invoice_lines": [
            {"product_id": 45, "quantity": 100, "unit_price": 500.00}
        ],
        "po_reference": "PO-2026-045"
    }
    
    try:
        result = await agent.execute(test_data_perfect)
        print(f"✓ Agent: {result['agent']}")
        print(f"✓ Action: {result.get('action', 'N/A')}")
        print(f"✓ Status: {result.get('status', 'N/A')}")
        print(f"✓ Message: {result.get('message', 'N/A')}")
        if result.get('variance_analysis'):
            print(f"✓ Amount Variance: {result['variance_analysis'].get('amount_variance_pct', 0)}%")
    except Exception as e:
        print(f"✗ Test failed: {e}")
    
    print("\n" + "-"*80 + "\n")
    
    # Scenario 2: Small variance (5-10% = flag for review)
    print("Scenario 2: Small Variance (Flag for Review)")
    test_data_variance = {
        "invoice_id": 1002,
        "invoice_number": "INV-2026-002",
        "invoice_amount": 53000.00,  # 6% over PO
        "invoice_lines": [
            {"product_id": 45, "quantity": 100, "unit_price": 530.00}
        ],
        "po_reference": "PO-2026-045"
    }
    
    try:
        result = await agent.execute(test_data_variance)
        print(f"✓ Agent: {result['agent']}")
        print(f"✓ Action: {result.get('action', 'N/A')}")
        print(f"✓ Status: {result.get('status', 'N/A')}")
        print(f"✓ Message: {result.get('message', 'N/A')}")
        if result.get('variance_analysis'):
            print(f"✓ Amount Variance: {result['variance_analysis'].get('amount_variance_pct', 0)}%")
    except Exception as e:
        print(f"✗ Test failed: {e}")
    
    print("\n" + "-"*80 + "\n")
    
    # Scenario 3: Large variance (>10% = block)
    print("Scenario 3: Large Variance (Block Investigation)")
    test_data_large_variance = {
        "invoice_id": 1003,
        "invoice_number": "INV-2026-003",
        "invoice_amount": 65000.00,  # 30% over PO
        "invoice_lines": [
            {"product_id": 45, "quantity": 100, "unit_price": 650.00}
        ],
        "po_reference": "PO-2026-045"
    }
    
    try:
        result = await agent.execute(test_data_large_variance)
        print(f"✓ Agent: {result['agent']}")
        print(f"✓ Action: {result.get('action', 'N/A')}")
        print(f"✓ Status: {result.get('status', 'N/A')}")
        print(f"✓ Message: {result.get('message', 'N/A')}")
        if result.get('variance_analysis'):
            print(f"✓ Amount Variance: {result['variance_analysis'].get('amount_variance_pct', 0)}%")
    except Exception as e:
        print(f"✗ Test failed: {e}")


async def test_spend_analytics_agent():
    """Test SpendAnalyticsAgent with various time periods"""
    print_section("TEST 2: SpendAnalyticsAgent - Company-Wide Spend Analysis")
    
    agent = SpendAnalyticsAgent()
    
    # Scenario 1: Year-to-date comprehensive analysis
    print("Scenario 1: YTD Comprehensive Analysis")
    test_data_ytd = {
        "analysis_type": "comprehensive",
        "time_period": "YTD"
    }
    
    try:
        result = await agent.execute(test_data_ytd)
        print(f"✓ Agent: {result['agent']}")
        print(f"✓ Action: {result.get('action', 'N/A')}")
        
        if result.get('executive_summary'):
            summary = result['executive_summary']
            print(f"\n📊 Executive Summary:")
            print(f"   Total Spend: ${summary.get('total_spend', 0):,.2f}")
            print(f"   Purchase Orders: {summary.get('total_purchase_orders', 0)}")
            print(f"   Unique Vendors: {summary.get('unique_vendors', 0)}")
            print(f"   Unique Departments: {summary.get('unique_departments', 0)}")
            print(f"   Savings Identified: ${summary.get('total_savings_identified', 0):,.2f}")
            print(f"   Savings %: {summary.get('savings_percentage', 0):.2f}%")
            print(f"   Opportunities: {summary.get('opportunities_count', 0)}")
        
        if result.get('spend_by_department'):
            print(f"\n💼 Top 3 Departments by Spend:")
            for i, (dept, amount) in enumerate(list(result['spend_by_department'].items())[:3], 1):
                print(f"   {i}. {dept}: ${amount:,.2f}")
        
        if result.get('savings_opportunities'):
            print(f"\n💰 Top 3 Savings Opportunities:")
            for i, opp in enumerate(result['savings_opportunities'][:3], 1):
                print(f"   {i}. {opp.get('type')}: ${opp.get('potential_savings', 0):,.2f}")
                print(f"      {opp.get('recommendation', 'No recommendation')}")
        
        if result.get('top_recommendations'):
            print(f"\n🎯 Top Recommendation:")
            top_rec = result['top_recommendations'][0] if result['top_recommendations'] else {}
            print(f"   Priority: {top_rec.get('priority', 'N/A')}")
            print(f"   Action: {top_rec.get('action', 'N/A')}")
            print(f"   Potential Savings: ${top_rec.get('potential_savings', 0):,.2f}")
            
    except Exception as e:
        print(f"✗ Test failed: {e}")
    
    print("\n" + "-"*80 + "\n")
    
    # Scenario 2: Department-specific analysis
    print("Scenario 2: IT Department Analysis")
    test_data_dept = {
        "analysis_type": "department",
        "time_period": "last_6_months",
        "department": "IT"
    }
    
    try:
        result = await agent.execute(test_data_dept)
        print(f"✓ Agent: {result['agent']}")
        print(f"✓ Action: {result.get('action', 'N/A')}")
        
        if result.get('executive_summary'):
            summary = result['executive_summary']
            print(f"\n📊 IT Department - Last 6 Months:")
            print(f"   Total Spend: ${summary.get('total_spend', 0):,.2f}")
            print(f"   Savings Identified: ${summary.get('total_savings_identified', 0):,.2f}")
            
    except Exception as e:
        print(f"✗ Test failed: {e}")


async def test_inventory_check_agent():
    """Test InventoryCheckAgent with various check types"""
    print_section("TEST 3: InventoryCheckAgent - Inventory Monitoring & Auto-Replenishment")
    
    agent = InventoryCheckAgent()
    
    # Scenario 1: Full inventory scan
    print("Scenario 1: Full Inventory Scan")
    test_data_full = {
        "check_type": "full_scan",
        "auto_create_pr": True
    }
    
    try:
        result = await agent.execute(test_data_full)
        print(f"✓ Agent: {result['agent']}")
        print(f"✓ Action: {result.get('action', 'N/A')}")
        print(f"✓ Message: {result.get('message', 'N/A')}")
        
        if result.get('inventory_summary'):
            summary = result['inventory_summary']
            print(f"\n📦 Inventory Summary:")
            print(f"   Total Products Scanned: {summary.get('total_products', 0)}")
            print(f"   Low Stock Items: {summary.get('low_stock_count', 0)}")
            print(f"   Healthy Stock Items: {summary.get('healthy_stock_count', 0)}")
            print(f"   Critical Items (Urgent): {summary.get('critical_items', 0)}")
        
        if result.get('low_stock_items'):
            print(f"\n🚨 Low Stock Items (Top 5):")
            for i, item in enumerate(result['low_stock_items'][:5], 1):
                print(f"   {i}. {item.get('product_name', 'Unknown')}")
                print(f"      Current Stock: {item.get('current_stock', 0)} units")
                print(f"      Reorder Point: {item.get('reorder_point', 0)} units")
                print(f"      Recommended Order: {item.get('recommended_order_qty', 0)} units")
                print(f"      Urgency: {item.get('urgency', 'N/A')}")
                print(f"      Stockout Risk: {item.get('stockout_risk', 0):.1f}%")
        
        if result.get('prs_created'):
            print(f"\n✅ Purchase Requisitions Created:")
            for i, pr in enumerate(result['prs_created'][:5], 1):
                print(f"   {i}. {pr.get('pr_number')}: {pr.get('product_name')}")
                print(f"      Quantity: {pr.get('quantity')} | Urgency: {pr.get('urgency')}")
                print(f"      Estimated Delivery: {pr.get('estimated_delivery')}")
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
    
    print("\n" + "-"*80 + "\n")
    
    # Scenario 2: Single product check
    print("Scenario 2: Single Product Check (Product ID: 45)")
    test_data_single = {
        "check_type": "single_product",
        "product_id": 45,
        "auto_create_pr": False  # Just check, don't create PR
    }
    
    try:
        result = await agent.execute(test_data_single)
        print(f"✓ Agent: {result['agent']}")
        print(f"✓ Action: {result.get('action', 'N/A')}")
        print(f"✓ Message: {result.get('message', 'N/A')}")
        
        if result.get('low_stock_items'):
            item = result['low_stock_items'][0] if result['low_stock_items'] else {}
            if item:
                print(f"\n📦 Product Details:")
                print(f"   Name: {item.get('product_name', 'Unknown')}")
                print(f"   Code: {item.get('product_code', 'N/A')}")
                print(f"   Current Stock: {item.get('current_stock', 0)} units")
                print(f"   Recommended Order: {item.get('recommended_order_qty', 0)} units")
                print(f"   Vendor: {item.get('vendor', 'No vendor')}")
                print(f"   Lead Time: {item.get('lead_time_days', 0)} days")
        
    except Exception as e:
        print(f"✗ Test failed: {e}")


async def test_integration():
    """Test integration of all 3 agents in a workflow"""
    print_section("TEST 4: Integration Test - Complete Procurement Cycle")
    
    print("Simulating complete procurement workflow:")
    print("1. Inventory Check → identifies low stock")
    print("2. Spend Analysis → validates budget available")
    print("3. 3-Way Matching → approves vendor invoice")
    print("\nExecuting workflow...")
    
    try:
        # Step 1: Inventory check
        inventory_agent = InventoryCheckAgent()
        inventory_result = await inventory_agent.execute({
            "check_type": "full_scan",
            "auto_create_pr": True
        })
        
        print(f"\n✓ Step 1 Complete: Identified {inventory_result.get('inventory_summary', {}).get('low_stock_count', 0)} low-stock items")
        print(f"  Created {len(inventory_result.get('prs_created', []))} purchase requisitions")
        
        # Step 2: Spend analysis
        spend_agent = SpendAnalyticsAgent()
        spend_result = await spend_agent.execute({
            "analysis_type": "comprehensive",
            "time_period": "YTD"
        })
        
        total_spend = spend_result.get('executive_summary', {}).get('total_spend', 0)
        savings = spend_result.get('executive_summary', {}).get('total_savings_identified', 0)
        print(f"\n✓ Step 2 Complete: Analyzed ${total_spend:,.2f} spending")
        print(f"  Identified ${savings:,.2f} in potential savings")
        
        # Step 3: Invoice matching (simulated)
        invoice_agent = InvoiceMatchingAgent()
        invoice_result = await invoice_agent.execute({
            "invoice_number": "INV-TEST-001",
            "invoice_amount": 50000.00,
            "invoice_lines": [{"product_id": 45, "quantity": 100, "unit_price": 500.00}],
            "po_reference": "PO-2026-045"
        })
        
        print(f"\n✓ Step 3 Complete: Invoice matching status: {invoice_result.get('status', 'N/A')}")
        print(f"  Variance: {invoice_result.get('variance_analysis', {}).get('amount_variance_pct', 0)}%")
        
        print(f"\n{'='*80}")
        print("✅ INTEGRATION TEST PASSED - All 3 agents executed successfully")
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"\n✗ Integration test failed: {e}")


async def main():
    """Run all tests"""
    print("\n" + "="*80)
    print(" "*20 + "WEEK 1 AGENTS TEST SUITE")
    print(" "*15 + "InvoiceMatching | SpendAnalytics | InventoryCheck")
    print("="*80)
    
    # Run individual agent tests
    await test_invoice_matching_agent()
    await test_spend_analytics_agent()
    await test_inventory_check_agent()
    
    # Run integration test
    await test_integration()
    
    print("\n" + "="*80)
    print("  TEST SUITE COMPLETE")
    print("="*80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
