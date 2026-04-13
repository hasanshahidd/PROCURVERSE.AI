"""
Install Missing Odoo Modules for Procurement Workflows
Installs: purchase_requisition, account_budget, approvals, auditlog
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dotenv import load_dotenv
load_dotenv()

from backend.services.odoo_client import get_odoo_client

def check_module_availability():
    """Check which modules are available but not installed"""
    client = get_odoo_client()
    
    if not client.is_connected():
        print("Cannot connect to Odoo - make sure it's running")
        return
    
    print("Checking available modules...\n")
    
    # Target modules we want to install
    target_modules = [
        'purchase_requisition',  # Purchase Requisitions (PR workflow)
        'account_budget',        # Budget Management
        'approvals',             # Approval workflows
        'purchase_request',      # Alternative to purchase_requisition
        'hr_expense',            # Expense management (helps with approvals)
    ]
    
    for module_name in target_modules:
        try:
            # Search for module
            modules = client.execute_kw(
                'ir.module.module',
                'search_read',
                [[('name', '=', module_name)]],
                {'fields': ['name', 'shortdesc', 'state', 'summary'], 'limit': 1}
            )
            
            if modules:
                module = modules[0]
                state = module['state']
                
                if state == 'installed':
                    print(f"{module_name}: Already installed")
                    print(f"   {module.get('shortdesc', 'No description')}\n")
                elif state == 'uninstalled':
                    print(f"️  {module_name}: Available but not installed")
                    print(f"   {module.get('shortdesc', 'No description')}")
                    print(f"   State: {state}\n")
                else:
                    print(f"{module_name}: State = {state}")
                    print(f"   {module.get('shortdesc', 'No description')}\n")
            else:
                print(f"{module_name}: NOT FOUND (not available in this Odoo installation)\n")
        
        except Exception as e:
            print(f"Error checking {module_name}: {str(e)}\n")


def list_all_procurement_modules():
    """List all procurement-related modules"""
    client = get_odoo_client()
    
    if not client.is_connected():
        return
    
    print("\n" + "="*70)
    print("ALL PROCUREMENT-RELATED MODULES")
    print("="*70 + "\n")
    
    try:
        # Search for purchase and procurement related modules
        modules = client.execute_kw(
            'ir.module.module',
            'search_read',
            [[('name', 'ilike', 'purchase')]],
            {'fields': ['name', 'shortdesc', 'state'], 'limit': 50}
        )
        
        installed = [m for m in modules if m['state'] == 'installed']
        uninstalled = [m for m in modules if m['state'] == 'uninstalled']
        
        print(f"INSTALLED ({len(installed)}):")
        for m in installed:
            print(f"   • {m['name']}: {m['shortdesc']}")
        
        print(f"\nAVAILABLE TO INSTALL ({len(uninstalled)}):")
        for m in uninstalled:
            print(f"   • {m['name']}: {m['shortdesc']}")
    
    except Exception as e:
        print(f"Error listing modules: {str(e)}")


def install_module(module_name):
    """Install a specific module"""
    client = get_odoo_client()
    
    if not client.is_connected():
        print("Cannot connect to Odoo")
        return False
    
    try:
        print(f"\nInstalling {module_name}...")
        
        # Find module ID
        modules = client.execute_kw(
            'ir.module.module',
            'search',
            [[('name', '=', module_name), ('state', '=', 'uninstalled')]]
        )
        
        if not modules:
            print(f"Module {module_name} not found or already installed")
            return False
        
        module_id = modules[0]
        
        # Install module using button_immediate_install method
        client.execute_kw(
            'ir.module.module',
            'button_immediate_install',
            [[module_id]]
        )
        
        print(f"{module_name} installation initiated!")
        print(f"   This may take a few moments...")
        return True
        
    except Exception as e:
        print(f"Error installing {module_name}: {str(e)}")
        return False


def update_apps_list():
    """Update the apps list in Odoo (like clicking 'Update Apps List' in UI)"""
    client = get_odoo_client()
    
    if not client.is_connected():
        print("Cannot connect to Odoo")
        return False
    
    try:
        print("\nUpdating Odoo apps list...")
        
        # This updates the module list from the addons path
        client.execute_kw(
            'ir.module.module',
            'update_list',
            [[]]
        )
        
        print("Apps list updated successfully!")
        return True
        
    except Exception as e:
        print(f"Error updating apps list: {str(e)}")
        print("   You may need to do this manually via Odoo UI:")
        print("   Settings > Apps > Update Apps List")
        return False


if __name__ == "__main__":
    print("="*70)
    print("ODOO MODULE INSTALLER")
    print("="*70)
    
    # Step 1: Update apps list
    print("\nStep 1: Updating apps list...")
    update_apps_list()
    
    # Step 2: Check current status
    print("\nStep 2: Checking module availability...")
    check_module_availability()
    
    # Step 3: List all procurement modules
    list_all_procurement_modules()
    
    # Step 4: Attempt to install
    print("\n" + "="*70)
    print("INSTALLATION PHASE")
    print("="*70)
    
    modules_to_install = [
        'purchase_requisition',
        'account_budget',
        'approvals',
    ]
    
    user_input = input("\nDo you want to install available modules? (yes/no): ").strip().lower()
    
    if user_input == 'yes' or user_input == 'y':
        for module in modules_to_install:
            install_module(module)
        
        print("\n" + "="*70)
        print("INSTALLATION COMPLETE")
        print("="*70)
        print("\n️  You may need to restart Odoo for changes to take effect:")
        print("   1. Stop Odoo server")
        print("   2. Start Odoo server again")
        print("   3. Or use: Settings > Apps > Update Apps List in UI")
    else:
        print("\n ️  Installation skipped. You can install modules manually via:")
        print("   Odoo UI > Settings > Apps > Search module name > Install")
