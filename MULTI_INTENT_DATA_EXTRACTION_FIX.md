# Multi-Intent Data Extraction Fix

**Date**: Feb 2026  
**Status**: ✅ COMPLETE - Ready for Testing

## Problem Summary

User tested multi-intent query: **"Find best vendor, check budget, and route approval for 20k Electronics"**

**Expected**: All 3 intents share extracted data (amount=20000, category="Electronics")

**Actual Results (BEFORE FIX)**:
1. ❌ **VendorSelectionAgent**: Returned "Gemini Furniture" (wrong category - should be Electronics vendor)
2. ❌ **BudgetVerificationAgent**: Failed with "No budget found for None - OPEX" (missing department)
3. ❌ **ApprovalRoutingAgent**: Failed with "No approval chain for Unknown department" (department=None)

## Root Cause Analysis

**Multi-intent orchestrator was not merging classifier filters into pr_data**

```python
# OLD CODE (broken):
for intent in intents:
    context = {
        "request": request.request,
        "pr_data": request.pr_data or {},  # ❌ Always empty for NL queries!
        ...
    }
    result = await orchestrator.execute(context)
```

**Why this broke:**
- User prompt: "Find best vendor for 20k Electronics"
- Classifier extracts: `intent["filters"] = {"amount": 20000, "category": "Electronics"}`
- But `request.pr_data` is empty dict for NL queries
- Agents receive NO amount, NO category, NO department
- VendorSelectionAgent defaults to first available vendor (Gemini Furniture)
- BudgetVerificationAgent fails because department=None
- ApprovalRoutingAgent fails because department=None

## Three-Part Fix Implementation

### Fix 1: Data Enrichment Function

**File**: `backend/routes/agentic.py`  
**Location**: Lines ~280-360  
**Function**: `_enrich_pr_data_from_filters(base_pr_data, intent_filters)`

**Mappings**:
```python
intent_filters["amount"]        → pr_data["budget"]
intent_filters["total_cost"]    → pr_data["budget"]
intent_filters["category"]      → pr_data["category"]
intent_filters["department"]    → pr_data["department"]
intent_filters["vendor"]        → pr_data["vendor_name"]
intent_filters["product"]       → pr_data["product_name"]
intent_filters["quantity"]      → pr_data["quantity"]
intent_filters["urgency"]       → pr_data["urgency"]
intent_filters["justification"] → pr_data["justification"]
```

**Smart Defaulting**:
1. **Department Inference** (if not specified):
   - Category contains "electronics/IT/computer/software/hardware" → Department = "IT"
   - Category contains "furniture/office supplies" → Department = "Operations"
   - Otherwise → Default to "IT"

2. **Budget Category Inference** (if not specified):
   - Category = "electronics/hardware/equipment/furniture" AND amount > $5k → "CAPEX"
   - Category = "supplies/software/license/subscription" → "OPEX"
   - Otherwise: amount > $10k → "CAPEX", else → "OPEX"

**Example**:
```python
# Input
base_pr_data = {}
intent_filters = {"amount": 20000, "category": "Electronics"}

# Output
enriched_pr_data = {
    "budget": 20000,
    "category": "Electronics",
    "department": "IT",  # Inferred!
    "budget_category": "CAPEX"  # Inferred!
}
```

### Fix 2: Multi-Intent Loop Update

**File**: `backend/routes/agentic.py`  
**Location**: Line ~411

**OLD CODE**:
```python
for intent in intents:
    context = {
        "request": request.request,
        "pr_data": request.pr_data or {},  # ❌ Empty!
        ...
    }
```

**NEW CODE**:
```python
for intent in intents:
    intent_filters = intent.get("filters", {})
    enriched_pr_data = _enrich_pr_data_from_filters(
        request.pr_data or {}, 
        intent_filters
    )
    context = {
        "request": request.request,
        "pr_data": enriched_pr_data,  # ✅ Enriched with extracted data!
        ...
    }
```

### Fix 3: Enhanced Classifier Prompt

**File**: `backend/services/llm_routing_guide.py`  
**Function**: `build_classifier_instructions()`  
**Location**: Lines ~100-200

**Added Section**:
```
### FILTERS EXTRACTION GUIDE (CRITICAL!)

When analyzing user requests, ALWAYS extract these fields into the "filters" object:

1. **Amount/Budget**: Extract from phrases like:
   - "20k" → 20000
   - "$50k" → 50000
   - "100,000" → 100000
   - "1.5 million" → 1500000

2. **Category**: Extract product/service type:
   - "Electronics" → category: "Electronics"
   - "Office Supplies" → category: "Office Supplies"
   - "IT equipment" → category: "Electronics"

3. **Department**: Extract if mentioned:
   - "IT department" → department: "IT"
   - "Finance team" → department: "Finance"
   - If NOT specified, leave blank (enrichment will infer)

4. **Vendor**: Extract if mentioned:
   - "from XYZ Corp" → vendor: "XYZ Corp"

### CRITICAL: For vendor selection, category is MANDATORY!
Without category, VendorSelectionAgent cannot filter by product type.
```

**Enhanced Examples**:
```json
// Example 1: Simple vendor selection
"Find best vendor for Electronics"
→ {
    "module": "vendor_selection",
    "filters": {"category": "Electronics"}
  }

// Example 2: Complete multi-intent
"Find best vendor, check budget, and route approval for 20k Electronics"
→ [
    {
      "module": "vendor_selection",
      "filters": {"amount": 20000, "category": "Electronics"}
    },
    {
      "module": "budget_verification",
      "filters": {"amount": 20000}
    },
    {
      "module": "approval_routing",
      "filters": {"amount": 20000}
    }
  ]
```

## Expected Results After Fix

**Query**: "Find best vendor, check budget, and route approval for 20k Electronics"

**Intent 1 - VENDOR**:
```python
pr_data = {
    "budget": 20000,
    "category": "Electronics",
    "department": "IT",  # Inferred
    "budget_category": "CAPEX"  # Inferred
}
# VendorSelectionAgent filters vendors by category="Electronics"
# Returns: "TechSource Electronics" (not Gemini Furniture!)
```

**Intent 2 - BUDGET**:
```python
pr_data = {
    "budget": 20000,
    "department": "IT",  # Inferred
    "budget_category": "CAPEX"
}
# BudgetVerificationAgent checks IT-CAPEX budget for $20k
# Returns: "✅ Budget available: $75,000 of $150,000 remaining"
```

**Intent 3 - APPROVAL**:
```python
pr_data = {
    "budget": 20000,
    "department": "IT"  # Inferred
}
# ApprovalRoutingAgent finds approval chain for IT dept, $20k amount
# Returns: "Level 2 approval required: Manager + Director"
```

## Validation Checklist

Test the query: **"Find best vendor, check budget, and route approval for 20k Electronics"**

- [ ] **VendorSelectionAgent**: Returns Electronics vendor (e.g., "TechSource Electronics")
- [ ] **BudgetVerificationAgent**: Shows IT department budget check (not "None - OPEX")
- [ ] **ApprovalRoutingAgent**: Shows IT approval chain (not "Unknown department")
- [ ] **All intents**: Share the same extracted data (amount, category, department)
- [ ] **No crashes**: No NoneType errors or missing field errors

## Files Modified

1. **backend/routes/agentic.py**:
   - Added `_enrich_pr_data_from_filters()` function (~80 lines)
   - Updated multi-intent loop to call enrichment (line ~411)
   - Added smart defaulting for department and budget_category

2. **backend/services/llm_routing_guide.py**:
   - Enhanced `build_classifier_instructions()` with FILTERS EXTRACTION GUIDE
   - Added examples for category/amount extraction
   - Added multi-intent example with shared filters

## Related Documentation

- **AGENT_SYSTEM_ANALYSIS.md**: Multi-intent architecture deep-dive
- **TEST_QUERIES_COMPLETE.md**: 60+ test queries including multi-intent scenarios
- **ENHANCED_AGENT_DATA_DISPLAY.md**: Nested data extraction patterns
- **PROCUREMENT_WORKFLOW_EXPLAINED.md**: PR→Approval→PO workflow stages

## Next Steps

1. **Test the fix**: Run the validation query above
2. **Monitor logs**: Check `[PR_DATA_ENRICHMENT]` console output
3. **Verify all test queries**: Use TEST_QUERIES_COMPLETE.md checklist
4. **Optional enhancements**:
   - Add more category→department mappings
   - Add explicit department extraction in classifier
   - Add validation warnings for missing critical fields

## Testing Commands

**PowerShell**:
```powershell
$body = @{ 
    request = "Find best vendor, check budget, and route approval for 20k Electronics"
} | ConvertTo-Json

Invoke-RestMethod -Uri http://localhost:5000/api/agentic/execute -Method Post -Body $body -ContentType "application/json"
```

**Expected Response Structure**:
```json
{
  "intents_executed": 3,
  "results": [
    {
      "module": "vendor_selection",
      "result": {
        "recommended_vendor": "TechSource Electronics",
        "category": "Electronics",
        "score": 88.5
      }
    },
    {
      "module": "budget_verification",
      "result": {
        "available": true,
        "department": "IT",
        "category": "CAPEX",
        "allocated": 150000,
        "spent": 75000,
        "requested": 20000
      }
    },
    {
      "module": "approval_routing",
      "result": {
        "approval_level": "Level 2",
        "department": "IT",
        "approvers": ["Mike Manager", "Diana Director"]
      }
    }
  ]
}
```

---

**Status**: ✅ Implementation complete, ready for validation testing
