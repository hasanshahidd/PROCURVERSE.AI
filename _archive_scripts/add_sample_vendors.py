"""Add sample vendors to Odoo for testing

Run this if verification fails with "Only 2 vendors found, need at least 5"
"""
import sys
from backend.services.odoo_client import get_odoo_client

def add_vendors():
    """Add sample vendors to Odoo"""
    print("🚀 Adding Sample Vendors to Odoo\n")
    
    try:
        odoo = get_odoo_client()
    except Exception as e:
        print(f"❌ Failed to connect to Odoo: {e}")
        print("\n💡 Make sure Odoo is running at http://localhost:8069")
        return False
    
    if not odoo.is_connected():
        print("❌ Not connected to Odoo")
        print("\n💡 Check:")
        print("   1. Odoo is running: curl http://localhost:8069")
        print("   2. Database 'odoo_procurement_demo' exists")
        print("   3. Credentials are correct (admin / admin)")
        return False
    
    print("✅ Connected to Odoo")
    
    # Get current vendor count
    try:
        current_vendors = odoo.get_vendors(limit=100)
        print(f"📊 Current vendors: {len(current_vendors)}")
        
        if len(current_vendors) >= 5:
            print("✅ Already have enough vendors (5+)")
            print("\nExisting vendors:")
            for v in current_vendors[:10]:  # Show first 10
                print(f"   - {v.get('name', 'Unknown')} (ID: {v.get('id')})")
            return True
    except Exception as e:
        print(f"❌ Failed to get vendors: {e}")
        return False
    
    # Vendors to add
    new_vendors = [
        {
            'name': 'TechSupply Co',
            'supplier_rank': 1,
            'email': 'sales@techsupply.com',
            'phone': '+1-555-0101',
            'category': 'Electronics'
        },
        {
            'name': 'Office Depot LLC',
            'supplier_rank': 2,
            'email': 'orders@officedepot.com',
            'phone': '+1-555-0102',
            'category': 'Office Supplies'
        },
        {
            'name': 'Industrial Parts Inc',
            'supplier_rank': 3,
            'email': 'info@industrialparts.com',
            'phone': '+1-555-0103',
            'category': 'Industrial Equipment'
        },
        {
            'name': 'Global Electronics Supply',
            'supplier_rank': 1,
            'email': 'sales@globalelec.com',
            'phone': '+1-555-0104',
            'category': 'Electronics'
        },
        {
            'name': 'Mega Wholesale Corp',
            'supplier_rank': 2,
            'email': 'wholesale@megacorp.com',
            'phone': '+1-555-0105',
            'category': 'General Supplies'
        }
    ]
    
    added_count = 0
    vendors_needed = max(5 - len(current_vendors), 0)
    
    if vendors_needed == 0:
        print("✅ Already have 5+ vendors")
        return True
    
    print(f"\n📝 Adding {vendors_needed} vendors...\n")
    
    for vendor_data in new_vendors[:vendors_needed]:
        try:
            # Create vendor in Odoo
            vendor_id = odoo.execute_kw('res.partner', 'create', [{
                'name': vendor_data['name'],
                'supplier_rank': vendor_data['supplier_rank'],
                'email': vendor_data['email'],
                'phone': vendor_data['phone'],
                'is_company': True,
                'company_type': 'company'
            }])
            
            print(f"  ✅ Added: {vendor_data['name']}")
            print(f"     - ID: {vendor_id}")
            print(f"     - Email: {vendor_data['email']}")
            print(f"     - Category: {vendor_data['category']}")
            print()
            added_count += 1
            
        except Exception as e:
            print(f"  ❌ Failed to add {vendor_data['name']}: {e}")
            print()
    
    # Verify
    print("🔍 Verifying...\n")
    try:
        final_vendors = odoo.get_vendors(limit=100)
        print(f"📊 Final vendor count: {len(final_vendors)}")
        
        if len(final_vendors) >= 5:
            print("✅✅✅ Success! Now have 5+ vendors\n")
            print("Vendor list:")
            for v in final_vendors[:10]:  # Show first 10
                print(f"   - {v.get('name', 'Unknown')} (ID: {v.get('id')})")
            print("\n✅ Ready to proceed with agent integration!")
            return True
        else:
            print(f"⚠️  Still need {5 - len(final_vendors)} more vendors")
            print("💡 You can:")
            print("   1. Run this script again")
            print("   2. Add vendors manually in Odoo UI")
            return False
    except Exception as e:
        print(f"❌ Failed to verify: {e}")
        return False

if __name__ == "__main__":
    success = add_vendors()
    
    if success:
        print("\n🎯 Next Step:")
        print("   Run: python verify_system_ready.py")
        sys.exit(0)
    else:
        print("\n❌ Failed to add vendors")
        print("\n💡 Troubleshooting:")
        print("   1. Make sure Odoo is running")
        print("   2. Check database 'odoo_procurement_demo' exists")
        print("   3. Try adding vendors manually in Odoo UI")
        sys.exit(1)
