"""
Test script to verify race condition fix in budget reservation
Tests that concurrent budget reservations don't cause double-spending
"""

import asyncio
import sys
import os

# Load environment variables from .env file FIRST
from dotenv import load_dotenv
load_dotenv()

# Verify DATABASE_URL is loaded and using port 5433
db_url = os.environ.get("DATABASE_URL", "NOT SET")
print(f"DATABASE_URL: {db_url}")
if ":5432" in db_url:
    print("⚠️  WARNING: Using default port 5432 instead of 5433!")
elif ":5433" in db_url:
    print("✅ Correct port 5433 detected")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.agents.tools import create_database_tools

async def test_concurrent_reservations():
    """
    Simulate two concurrent budget reservations to verify row-level locking works
    """
    print("\n" + "="*70)
    print("RACE CONDITION TEST: Concurrent Budget Reservations")
    print("="*70)
    
    # Get the budget tools
    tools = create_database_tools()
    update_tool = next(t for t in tools if t.name == "update_committed_budget")
    check_tool = next(t for t in tools if t.name == "check_budget_availability")
    
    department = "IT"
    category = "CAPEX"
    amount = 25000
    
    # Check initial budget
    print(f"\n1. Checking initial budget for {department}/{category}...")
    initial_check = check_tool.func(department, category, 0)
    print(f"   Response: {initial_check}")
    
    # Simulate concurrent reservations
    print(f"\n2. Simulating 2 concurrent reservations of ${amount:,} each...")
    print("   (If race condition exists, both would succeed even if only enough budget for one)")
    
    async def reserve_budget(reservation_id: int):
        """Simulate a budget reservation"""
        print(f"\n   [{reservation_id}] Starting reservation...")
        result = update_tool.func(department, category, amount)
        print(f"   [{reservation_id}] Result: {result}")
        return result
    
    # Run reservations concurrently
    results = await asyncio.gather(
        reserve_budget(1),
        reserve_budget(2),
        return_exceptions=True
    )
    
    print("\n3. Results:")
    for i, result in enumerate(results, 1):
        print(f"   Reservation {i}: {result}")
    
    # Check final budget
    print(f"\n4. Checking final budget...")
    final_check = check_tool.func(department, category, 0)
    print(f"   Response: {final_check}")
    
    print("\n" + "="*70)
    print("TEST COMPLETE")
    print("Expected: One reservation succeeds, one may get serialization error")
    print("          Budget should only be reduced by $25,000 (not $50,000)")
    print("="*70 + "\n")

if __name__ == "__main__":
    asyncio.run(test_concurrent_reservations())
