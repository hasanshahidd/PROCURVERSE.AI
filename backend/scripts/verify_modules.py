"""
Verify Installed Odoo Modules
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dotenv import load_dotenv
load_dotenv()

from backend.services.odoo_client import get_odoo_client

def verify_modules():
    """Check which procurement modules are now installed"""
    client = get_odoo_client()
    
    if not client.is_connected():
        print("❌ Cannot connect to Odoo")
        return
    
    print("="*70)
    print("📋 INSTALLED PROCUREMENT MODULES")
    print("="*70 + "\n")
    
    try:
        # Get all installed purchase-related modules
        modules = client.execute_kw(
            'ir.module.module',
            'search_read',
            [[('state', '=', 'installed'), ('name', 'ilike', 'purchase')]],
            {'fields': ['name', 'shortdesc', 'installed_version']}
        )
        
        print(f"Found {len(modules)} installed modules:\n")
        for m in modules:
            print(f"✅ {m['name']}")
            print(f"   Description: {m['shortdesc']}")
            print(f"   Version: {m.get('installed_version', 'N/A')}\n")
        
        # Check specific modules
        print("="*70)
        print("🎯 KEY MODULE STATUS")
        print("="*70 + "\n")
        
        key_modules = {
            'purchase_requisition': 'Purchase Requisitions/Agreements',
            'purchase': 'Purchase Orders',
            'stock': 'Inventory Management',
            'account': 'Accounting',
            'hr_expense': 'Expense Management'
        }
        
        for module_name, description in key_modules.items():
            modules = client.execute_kw(
                'ir.module.module',
                'search_read',
                [[('name', '=', module_name)]],
                {'fields': ['name', 'state']}
            )
            
            if modules and modules[0]['state'] == 'installed':
                print(f"✅ {description} ({module_name}): INSTALLED")
            else:
                print(f"❌ {description} ({module_name}): NOT INSTALLED")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")


if __name__ == "__main__":
    verify_modules()
