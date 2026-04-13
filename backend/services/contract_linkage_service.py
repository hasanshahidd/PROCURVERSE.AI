"""
Contract Linkage Service — G-02 Dev Spec 2.0
==============================================
Validates PO creation against active contracts.
- Links PO line items to contract prices
- Detects price variance (<=2% auto-approve, 2-10% notify, >10% block)
- Flags maverick spend (PO without a contract)

Usage:
    from backend.services.contract_linkage_service import ContractLinkageService
    svc = ContractLinkageService()
    result = svc.validate_po_against_contract(po_data)
"""
import logging
import os
import json
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)
DB_URL = os.environ.get('DATABASE_URL')

# Price variance thresholds
VARIANCE_AUTO_APPROVE_PCT = 2.0    # <= 2% auto-approve
VARIANCE_NOTIFY_PCT = 10.0          # 2-10% notify procurement
# > 10% blocked

class ContractLinkageService:
    """Validates PO prices against contracts and detects maverick spend."""

    def validate_po_against_contract(self, po_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a PO against active contracts for the vendor.

        Args:
            po_data: dict with keys:
                - po_number: str
                - vendor_id: str
                - vendor_name: str
                - items: list of {item_code, quantity, unit_price, description}
                - department: str
                - total_amount: float

        Returns:
            dict with: has_contract, contract_details, line_validations,
                       maverick_flag, overall_status, recommendations
        """
        vendor_id = str(po_data.get('vendor_id', '')).strip()
        vendor_name = str(po_data.get('vendor_name', '')).strip()
        po_number = str(po_data.get('po_number', '')).strip()
        items = po_data.get('items', [])

        result = {
            'po_number': po_number,
            'vendor_id': vendor_id,
            'vendor_name': vendor_name,
            'has_contract': False,
            'contract_details': None,
            'line_validations': [],
            'maverick_flag': True,  # Assume maverick until proven otherwise
            'overall_status': 'no_contract',
            'price_variance_alerts': [],
            'recommendations': [],
            'blocked': False,
        }

        conn = None
        try:
            conn = psycopg2.connect(DB_URL)
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Find active contracts for this vendor
            cur.execute("""
                SELECT id, contract_number, vendor_name, start_date, end_date,
                       contract_value, status, auto_renew, contract_type, description
                FROM contracts
                WHERE (vendor_name ILIKE %s OR vendor_id = %s)
                  AND status IN ('active', 'Active', 'approved')
                  AND (end_date IS NULL OR end_date >= CURRENT_DATE)
                ORDER BY start_date DESC
                LIMIT 5
            """, (f'%{vendor_name}%', vendor_id))
            contracts = cur.fetchall()

            if not contracts:
                result['recommendations'] = [
                    f"No active contract found for vendor '{vendor_name}'.",
                    "This is maverick spend — consider establishing a contract.",
                    "Recommend RFQ process for recurring purchases."
                ]
                # Log maverick spend
                self._log_po_contract_link(cur, conn, po_number, None, None, None, None, 0, 'no_contract', True)
                return result

            # Use the most recent active contract
            contract = dict(contracts[0])
            for k, v in contract.items():
                if isinstance(v, Decimal):
                    contract[k] = float(v)

            result['has_contract'] = True
            result['maverick_flag'] = False
            result['contract_details'] = {
                'contract_id': contract['id'],
                'contract_number': contract.get('contract_number'),
                'start_date': str(contract.get('start_date', '')),
                'end_date': str(contract.get('end_date', '')),
                'contract_value': contract.get('contract_value', 0),
                'status': contract.get('status'),
                'auto_renew': contract.get('auto_renew', False),
            }

            # Get contract line items for price validation
            cur.execute("""
                SELECT id, item_code, item_description, contracted_price, currency,
                       min_qty, max_qty, uom, price_valid_from, price_valid_to
                FROM contract_line_items
                WHERE contract_id = %s
            """, (contract['id'],))
            contract_lines = cur.fetchall()
            contract_price_map = {}
            for cl in contract_lines:
                cl_dict = dict(cl)
                for k, v in cl_dict.items():
                    if isinstance(v, Decimal):
                        cl_dict[k] = float(v)
                code = str(cl_dict.get('item_code', '')).strip().lower()
                if code:
                    contract_price_map[code] = cl_dict

            # Validate each PO line item against contract prices
            any_blocked = False
            for item in items:
                item_code = str(item.get('item_code', '')).strip().lower()
                unit_price = float(item.get('unit_price', 0))
                qty = float(item.get('quantity', 0))

                line_result = {
                    'item_code': item.get('item_code'),
                    'description': item.get('description', ''),
                    'po_price': unit_price,
                    'contracted_price': None,
                    'variance_pct': None,
                    'variance_status': 'no_contract_price',
                    'contract_line_id': None,
                }

                if item_code in contract_price_map:
                    cl = contract_price_map[item_code]
                    contracted_price = float(cl.get('contracted_price', 0))
                    line_result['contracted_price'] = contracted_price
                    line_result['contract_line_id'] = cl.get('id')

                    if contracted_price > 0:
                        variance_pct = ((unit_price - contracted_price) / contracted_price) * 100
                        line_result['variance_pct'] = round(variance_pct, 2)

                        abs_variance = abs(variance_pct)
                        if abs_variance <= VARIANCE_AUTO_APPROVE_PCT:
                            line_result['variance_status'] = 'within_tolerance'
                        elif abs_variance <= VARIANCE_NOTIFY_PCT:
                            line_result['variance_status'] = 'notify'
                            result['price_variance_alerts'].append(
                                f"Item {item.get('item_code')}: {variance_pct:+.1f}% vs contract price ${contracted_price:.2f}"
                            )
                        else:
                            line_result['variance_status'] = 'blocked'
                            any_blocked = True
                            result['price_variance_alerts'].append(
                                f"BLOCKED: Item {item.get('item_code')}: {variance_pct:+.1f}% exceeds 10% tolerance (contract: ${contracted_price:.2f}, PO: ${unit_price:.2f})"
                            )

                    # Log the link
                    self._log_po_contract_link(
                        cur, conn, po_number, contract['id'],
                        contract.get('contract_number'), cl.get('id'),
                        contracted_price, unit_price,
                        line_result['variance_status'], False
                    )
                else:
                    # Item not in contract — partial maverick
                    line_result['variance_status'] = 'not_in_contract'
                    result['recommendations'].append(
                        f"Item '{item.get('item_code', 'unknown')}' not covered by contract. Consider adding to next renewal."
                    )

                result['line_validations'].append(line_result)

            # Overall status
            if any_blocked:
                result['overall_status'] = 'blocked'
                result['blocked'] = True
                result['recommendations'].insert(0, "PO blocked due to price variance >10%. Renegotiate with vendor or get override approval.")
            elif result['price_variance_alerts']:
                result['overall_status'] = 'approved_with_alerts'
                result['recommendations'].insert(0, "PO approved but price variances detected. Review before confirming.")
            else:
                result['overall_status'] = 'approved'
                result['recommendations'].insert(0, "PO prices validated against contract. All within tolerance.")

            return result

        except Exception as e:
            logger.error("[ContractLinkageService] Error: %s", e)
            result['error'] = str(e)
            return result
        finally:
            if conn:
                conn.close()

    def get_contract_for_vendor(self, vendor_id: str = '', vendor_name: str = '') -> Optional[Dict]:
        """Look up active contract for a vendor."""
        conn = None
        try:
            conn = psycopg2.connect(DB_URL)
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT id, contract_number, vendor_name, start_date, end_date,
                       contract_value, status, contract_type
                FROM contracts
                WHERE (vendor_name ILIKE %s OR vendor_id = %s)
                  AND status IN ('active', 'Active', 'approved')
                  AND (end_date IS NULL OR end_date >= CURRENT_DATE)
                ORDER BY start_date DESC LIMIT 1
            """, (f'%{vendor_name}%', vendor_id))
            row = cur.fetchone()
            if row:
                d = dict(row)
                for k, v in d.items():
                    if isinstance(v, Decimal):
                        d[k] = float(v)
                return d
            return None
        except Exception as e:
            logger.error("[ContractLinkageService] Lookup error: %s", e)
            return None
        finally:
            if conn:
                conn.close()

    def check_maverick_spend(self, po_number: str, vendor_name: str, amount: float) -> Dict[str, Any]:
        """Check if a PO represents maverick spend (no contract backing)."""
        contract = self.get_contract_for_vendor(vendor_name=vendor_name)
        return {
            'is_maverick': contract is None,
            'po_number': po_number,
            'vendor_name': vendor_name,
            'amount': amount,
            'contract': contract,
            'recommendation': (
                'Covered by contract' if contract
                else f'Maverick spend: ${amount:,.2f} to {vendor_name} with no active contract'
            )
        }

    def _log_po_contract_link(self, cur, conn, po_number, contract_id, contract_number,
                               line_item_id, contracted_price, actual_price,
                               variance_status, maverick_flag):
        """Log PO-contract link to po_contract_link table."""
        try:
            variance_pct = None
            if contracted_price and actual_price and contracted_price > 0:
                variance_pct = round(((actual_price - contracted_price) / contracted_price) * 100, 2)

            cur.execute("""
                INSERT INTO po_contract_link (
                    po_number, contract_id, contract_number, line_item_id,
                    contracted_price, actual_price, price_variance_pct,
                    variance_status, maverick_flag, validated_by, validated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'ContractLinkageService', NOW())
            """, (po_number, contract_id, contract_number, line_item_id,
                  contracted_price, actual_price, variance_pct,
                  variance_status, maverick_flag))
            conn.commit()
        except Exception as e:
            logger.warning("[ContractLinkageService] Could not log link: %s", e)
            try:
                conn.rollback()
            except:
                pass


# Singleton
_instance: Optional[ContractLinkageService] = None

def get_contract_linkage_service() -> ContractLinkageService:
    global _instance
    if _instance is None:
        _instance = ContractLinkageService()
    return _instance
