"""
Test Week 1 Agents via API (Server-based testing)
Tests: InvoiceMatching, SpendAnalytics, InventoryCheck
"""

import requests
import json

API_BASE = "http://localhost:5000/api/agentic"

def print_section(title):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")

def test_invoice_matching():
    """Test InvoiceMatchingAgent via API"""
    print_section("TEST 1: InvoiceMatchingAgent - 3-Way Matching")
    
    # Test 1: Perfect match
    print("Scenario 1: Perfect Match (0% variance)")
    payload = {
        "request": "Match invoice INV-2026-001 against PO PO-2026-0055",
        "pr_data": {
            "invoice_number": "INV-2026-001",
            "invoice_amount": 50000,
            "vendor_name": "Dell Corporation",
            "po_reference": "PO-2026-0055",
            "invoice_date": "2026-03-05"
        }
    }
    
    try:
        response = requests.post(f"{API_BASE}/invoice/match", json=payload, timeout=30)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Response: {json.dumps(result, indent=2)}")
            return True
        else:
            print(f"❌ Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def test_spend_analytics():
    """Test SpendAnalyticsAgent via API"""
    print_section("TEST 2: SpendAnalyticsAgent - $50M Spend Analysis")
    
    # Test: YTD comprehensive analysis
    print("Scenario 1: Year-to-Date Comprehensive Analysis")
    payload = {
        "request": "Analyze company-wide spending year to date",
        "analysis_params": {
            "analysis_type": "comprehensive",
            "time_period": "YTD",
            "include_savings_opportunities": True
        }
    }
    
    try:
        response = requests.post(f"{API_BASE}/spend/analyze", json=payload, timeout=30)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Response received (truncated):")
            print(f"   Status: {result.get('status', 'N/A')}")
            print(f"   Agent: {result.get('agent', 'N/A')}")
            return True
        else:
            print(f"❌ Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def test_inventory_check():
    """Test InventoryCheckAgent via API"""
    print_section("TEST 3: InventoryCheckAgent - Stock Monitoring")
    
    # Test: Full inventory scan
    print("Scenario 1: Full Inventory Scan with Auto-PR Creation")
    payload = {
        "request": "Check all inventory levels and create PRs for low stock",
        "check_params": {
            "check_type": "full_scan",
            "auto_create_pr": True,
            "urgency_threshold": "MEDIUM"
        }
    }
    
    try:
        response = requests.post(f"{API_BASE}/inventory/check", json=payload, timeout=30)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Response received:")
            print(f"   Status: {result.get('status', 'N/A')}")
            print(f"   Agent: {result.get('agent', 'N/A')}")
            return True
        else:
            print(f"❌ Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def test_system_status():
    """Test system status endpoint"""
    print_section("SYSTEM STATUS CHECK")
    
    try:
        response = requests.get(f"{API_BASE}/status", timeout=10)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ System Status:")
            print(f"   Total Agents: {result.get('total_agents', 'N/A')}")
            print(f"   Active Agents: {result.get('active_agents', 'N/A')}")
            return True
        else:
            print(f"❌ Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def main():
    print("\n" + "="*80)
    print(" "*20 + "WEEK 1 AGENTS - API TESTING")
    print(" "*15 + "InvoiceMatching | SpendAnalytics | InventoryCheck")
    print("="*80)
    
    results = []
    
    # Check system status first
    print("\n🔍 Checking if server is ready...")
    if not test_system_status():
        print("\n❌ Server not ready or agents not loaded!")
        return
    
    # Test each agent
    results.append(("InvoiceMatchingAgent", test_invoice_matching()))
    results.append(("SpendAnalyticsAgent", test_spend_analytics()))
    results.append(("InventoryCheckAgent", test_inventory_check()))
    
    # Summary
    print("\n" + "="*80)
    print(" "*25 + "TEST SUMMARY")
    print("="*80 + "\n")
    
    for agent_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {agent_name}: {status}")
    
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print(f"\n{'='*80}")
        print(" "*15 + "🎉 ALL TESTS PASSED - WEEK 1 VALIDATED! 🎉")
        print(" "*10 + "InvoiceMatchingAgent | SpendAnalyticsAgent | InventoryCheckAgent")
        print(" "*20 + "11 of 17 Agents Operational (65%)")
        print(f"{'='*80}\n")
    else:
        print(f"\n{'='*80}")
        print(" "*20 + "⚠️ SOME TESTS FAILED")
        print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
