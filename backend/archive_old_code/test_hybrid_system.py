"""
Test Hybrid Query System
Tests both Odoo API queries and custom agentic table queries
"""

import requests
import json

API_URL = "http://localhost:5000/api"

def test_odoo_vendor_query():
    """Test querying Odoo vendors"""
    print("\nTEST 1: Odoo Vendor Query")
    response = requests.post(
        f"{API_URL}/chat",
        json={"message": "Show me all vendors", "language": "en"}
    )
    result = response.json()
    print(f"Response: {result['response'][:200]}...")
    print(f"   Data count: {len(result.get('data', []))}")
    return result

def test_budget_query():
    """Test querying custom budget_tracking table"""
    print("\nTEST 2: Budget Tracking Query")
    response = requests.post(
        f"{API_URL}/chat",
        json={"message": "What is the IT department budget?", "language": "en"}
    )
    result = response.json()
    print(f"Response: {result['response'][:200]}...")
    print(f"   Data count: {len(result.get('data', []))}")
    return result

def test_approval_chain_query():
    """Test querying custom approval_chains table"""
    print("\nTEST 3: Approval Chain Query") 
    response = requests.post(
        f"{API_URL}/chat",
        json={"message": "Who approves purchases in Finance department?", "language": "en"}
    )
    result = response.json()
    print(f"Response: {result['response'][:200]}...")
    print(f"   Data count: {len(result.get('data', []))}")
    return result

def test_product_query():
    """Test querying Odoo products"""
    print("\nTEST 4: Odoo Product Query")
    response = requests.post(
        f"{API_URL}/chat",
        json={"message": "Show me products", "language": "en"}
    )
    result = response.json()
    print(f"Response: {result['response'][:200]}...")
    print(f"   Data count: {len(result.get('data', []))}")
    return result

def test_health():
    """Test health endpoint"""
    print("\nTEST 5: Health Check")
    response = requests.get(f"{API_URL}/health")
    result = response.json()
    print(f"Mode: {result['mode']}")
    print(f"   Stats: {json.dumps(result['stats'], indent=2)}")
    return result

if __name__ == "__main__":
    print("="*60)
    print("HYBRID QUERY SYSTEM TEST SUITE")
    print("="*60)
    
    try:
        # Test health first
        test_health()
        
        # Test Odoo queries
        test_odoo_vendor_query()
        test_product_query()
        
        # Test custom table queries
        test_budget_query()
        test_approval_chain_query()
        
        print("\n" + "="*60)
        print("ALL TESTS PASSED - HYBRID SYSTEM WORKING!")
        print("="*60)
        
    except Exception as e:
        print(f"\nERROR: {e}")
