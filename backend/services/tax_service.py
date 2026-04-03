"""
Tax Calculation Service — Sprint 10
Calculates VAT/GST/sales tax based on jurisdiction and item category.

Supports:
  - UAE VAT (5%)
  - Saudi VAT (15%)
  - EU VAT (varies by country)
  - US Sales Tax (varies by state)
  - Zero-rated and exempt categories
"""
import logging, os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Standard tax rates by jurisdiction
TAX_RATES = {
    # Middle East
    "AE": {"standard": 0.05, "name": "UAE VAT", "currency": "AED"},
    "SA": {"standard": 0.15, "name": "Saudi VAT", "currency": "SAR"},
    "BH": {"standard": 0.10, "name": "Bahrain VAT", "currency": "BHD"},
    "OM": {"standard": 0.05, "name": "Oman VAT", "currency": "OMR"},
    # Europe
    "GB": {"standard": 0.20, "name": "UK VAT", "currency": "GBP"},
    "DE": {"standard": 0.19, "name": "German VAT", "currency": "EUR"},
    "FR": {"standard": 0.20, "name": "French VAT", "currency": "EUR"},
    # Americas
    "US": {"standard": 0.00, "name": "US Sales Tax", "currency": "USD"},  # State-level
    "CA": {"standard": 0.05, "name": "Canada GST", "currency": "CAD"},
    # Asia
    "IN": {"standard": 0.18, "name": "India GST", "currency": "INR"},
    "SG": {"standard": 0.09, "name": "Singapore GST", "currency": "SGD"},
    "JP": {"standard": 0.10, "name": "Japan CT", "currency": "JPY"},
}

# US state sales tax (simplified)
US_STATE_TAX = {
    "CA": 0.0725, "NY": 0.08, "TX": 0.0625, "FL": 0.06,
    "WA": 0.065, "IL": 0.0625, "PA": 0.06, "OH": 0.0575,
    "NJ": 0.06625, "VA": 0.053, "MA": 0.0625, "GA": 0.04,
    "OR": 0.0, "NH": 0.0, "MT": 0.0, "DE": 0.0, "AK": 0.0,
}

# Zero-rated categories (no tax)
ZERO_RATED_CATEGORIES = {
    "medical_equipment", "educational_materials", "exports",
    "international_transport", "basic_food", "precious_metals",
}

# Exempt categories
EXEMPT_CATEGORIES = {
    "financial_services", "insurance", "residential_rent",
    "local_passenger_transport", "bare_land",
}


def calculate_tax(
    amount: float,
    country_code: str = "AE",
    state_code: str = "",
    category: str = "general",
    is_import: bool = False,
) -> Dict[str, Any]:
    """
    Calculate tax for a given amount.

    Returns dict with tax_amount, tax_rate, total_with_tax, tax_name, details.
    """
    country = country_code.upper()
    category_lower = category.lower().replace(" ", "_")

    # Check zero-rated
    if category_lower in ZERO_RATED_CATEGORIES:
        return {
            "amount": amount,
            "tax_rate": 0.0,
            "tax_amount": 0.0,
            "total_with_tax": amount,
            "tax_name": "Zero-rated",
            "category": category,
            "country": country,
            "details": f"Category '{category}' is zero-rated in {country}",
        }

    # Check exempt
    if category_lower in EXEMPT_CATEGORIES:
        return {
            "amount": amount,
            "tax_rate": 0.0,
            "tax_amount": 0.0,
            "total_with_tax": amount,
            "tax_name": "Exempt",
            "category": category,
            "country": country,
            "details": f"Category '{category}' is tax-exempt in {country}",
        }

    # Get rate
    tax_info = TAX_RATES.get(country, {"standard": 0.0, "name": f"{country} Tax", "currency": "USD"})
    rate = tax_info["standard"]

    # US state override
    if country == "US" and state_code:
        rate = US_STATE_TAX.get(state_code.upper(), 0.0)

    # Import duty surcharge (simplified)
    import_surcharge = 0.05 if is_import and country in ("AE", "SA", "BH", "OM") else 0.0

    effective_rate = rate + import_surcharge
    tax_amount = round(amount * effective_rate, 2)

    return {
        "amount": amount,
        "tax_rate": effective_rate,
        "tax_amount": tax_amount,
        "total_with_tax": round(amount + tax_amount, 2),
        "tax_name": tax_info["name"],
        "base_rate": rate,
        "import_surcharge": import_surcharge,
        "category": category,
        "country": country,
        "state": state_code,
        "details": f"{tax_info['name']} at {effective_rate*100:.2f}%{' (includes import duty)' if import_surcharge else ''}",
    }


def calculate_invoice_tax(
    line_items: List[Dict],
    country_code: str = "AE",
    state_code: str = "",
) -> Dict[str, Any]:
    """Calculate tax for all line items on an invoice."""
    results = []
    total_before_tax = 0.0
    total_tax = 0.0

    for item in line_items:
        amount = float(item.get("amount", item.get("total", 0)))
        category = item.get("category", item.get("item_category", "general"))

        tax_result = calculate_tax(amount, country_code, state_code, category)
        results.append({
            "item": item.get("description", item.get("item_code", "?")),
            **tax_result,
        })
        total_before_tax += amount
        total_tax += tax_result["tax_amount"]

    return {
        "line_items": results,
        "subtotal": round(total_before_tax, 2),
        "total_tax": round(total_tax, 2),
        "grand_total": round(total_before_tax + total_tax, 2),
        "country": country_code,
        "tax_summary": f"Total tax: {country_code} {total_tax:,.2f}",
    }
