"""
Quick test to demonstrate comprehensive connection pool logging.
This will make a few API calls and show the detailed logs.
"""

import requests
import time

API_URL = "http://localhost:5000/api"

def test_logging():
    print("\n" + "="*80)
    print("TESTING CONNECTION POOL LOGGING")
    print("="*80)
    print("\n📋 This test makes 3 API calls to demonstrate the detailed logging.")
    print("💡 Check the BACKEND TERMINAL to see the comprehensive logs!\n")
    
    print("Making 3 requests to /api/agentic/approval-chains...\n")
    
    for i in range(3):
        print(f"Request {i+1}:", end=" ")
        try:
            response = requests.get(f"{API_URL}/agentic/approval-chains", timeout=10)
            if response.status_code == 200:
                print("✅ Success (200)")
            elif response.status_code == 429:
                print("⚠️  Rate limited (429) - Expected from FIX #3")
            else:
                print(f"❌ Status {response.status_code}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        time.sleep(1)  # Small delay between requests
    
    # Get final pool stats
    print("\n📊 Final Pool Statistics:")
    try:
        response = requests.get(f"{API_URL}/health/connection-pool", timeout=10)
        stats = response.json()["statistics"]
        print(f"   - Total acquired: {stats['total_acquired']}")
        print(f"   - Total returned: {stats['total_returned']}")
        print(f"   - Active: {stats['active_connections']}")
        print(f"   - Idle: {stats['idle_connections']}")
        print(f"   - Failures: {stats['failures']}")
        
        if stats['total_acquired'] == stats['total_returned']:
            print("\n✅ NO LEAKS: All acquired connections were returned!")
        else:
            print(f"\n⚠️  WARNING: Leak detected! {stats['total_acquired']} acquired but only {stats['total_returned']} returned")
    
    except Exception as e:
        print(f"   Error getting stats: {e}")
    
    print("\n" + "="*80)
    print("CHECK YOUR BACKEND TERMINAL NOW!")
    print("="*80)
    print("\nYou should see detailed INFO-level logs showing:")
    print("  [POOL GET] - Connection acquisition attempts")
    print("  ✅ [POOL GET SUCCESS] - Successful acquisitions with stats")
    print("  [AGENTIC API] - API endpoint operations")
    print("  ✅ [POOL RETURN SUCCESS] - Connection returns with stats")
    print("\n" + "="*80)

if __name__ == "__main__":
    print("\n⚠️  Make sure your backend server is running on port 5000!")
    input("Press Enter to start the test...")
    test_logging()
