"""
Sprint 1 — NMI Data Ingestion Pipeline
Loads all 58 NexaManufacturing Industries Excel files into PostgreSQL.

Each loader:
  1. Reads the Excel file (skip 2 title rows, header on row 3)
  2. Cleans/transforms column names to DB snake_case
  3. Upserts rows into the target table
  4. Logs results to data_ingestion_log

Usage:
    python backend/migrations/sprint1_data_ingestion.py
    python backend/migrations/sprint1_data_ingestion.py --file 01  # single file
    python backend/migrations/sprint1_data_ingestion.py --group master  # by group
"""

import os
import sys
import argparse
import pandas as pd
import psycopg2
import psycopg2.extras
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)

# Resolve the NMI Excel files directory
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent  # backend/migrations -> procure AI
DATA_DIR = PROJECT_ROOT / "master files"

if not DATA_DIR.exists():
    # Try one level up if running from Procure-AI root
    DATA_DIR = PROJECT_ROOT.parent / "master files"

if not DATA_DIR.exists():
    print(f"ERROR: Cannot find 'master files' directory. Checked:\n  {PROJECT_ROOT / 'master files'}")
    print("Set NMI_DATA_DIR environment variable to override.")
    DATA_DIR = Path(os.getenv("NMI_DATA_DIR", str(DATA_DIR)))


# ─────────────────────────────────────────────
#  Utility helpers
# ─────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def clean_col(col: str) -> str:
    """Convert Excel column name to snake_case DB column."""
    import re
    col = str(col).strip()
    col = re.sub(r'[^\w\s]', '', col)
    col = re.sub(r'\s+', '_', col)
    col = col.lower().strip('_')
    return col


def read_nmi_excel(filename: str, sheet: int = 0) -> pd.DataFrame:
    """Read NMI Excel file, skip 2 title rows, use row 3 as header."""
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Not found: {path}")
    df = pd.read_excel(path, header=2, sheet_name=sheet)
    # Ensure column names are strings (float NaN column names cause issues)
    df.columns = [str(c) for c in df.columns]
    # Drop columns with no name (Unnamed or nan)
    keep = [c for c in df.columns if not c.startswith('Unnamed') and c.lower() != 'nan']
    df = df[keep]
    # Drop rows that are entirely NaN
    df = df.dropna(how='all')
    return df


def log_ingestion(cur, source_file: str, table_name: str, rows: int, skipped: int,
                  status: str, error: str = None, started_at: datetime = None):
    cur.execute("""
        INSERT INTO data_ingestion_log
            (source_file, table_name, rows_loaded, rows_skipped, status, error_message, started_at, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT DO NOTHING
    """, (source_file, table_name, rows, skipped, status, error, started_at or datetime.now()))


def upsert_df(conn, df: pd.DataFrame, table: str, conflict_col: str,
              col_map: dict = None, source_file: str = "") -> tuple[int, int]:
    """
    Upsert a DataFrame into a table.
    col_map: {excel_col: db_col} mapping.
    Returns (rows_inserted, rows_skipped).
    """
    if col_map:
        df = df.rename(columns=col_map)

    # Clean all column names
    df.columns = [clean_col(c) for c in df.columns]

    # Get actual table columns and their data types from DB
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_name = %s AND table_schema = 'public'
        ORDER BY ordinal_position
    """, (table,))
    col_info = cur.fetchall()
    db_cols = {row[0] for row in col_info}
    bool_cols = {row[0] for row in col_info if row[1] == 'boolean'}

    # Keep only columns that exist in DB
    valid_cols = [c for c in df.columns if c in db_cols]
    skipped_cols = [c for c in df.columns if c not in db_cols]
    if skipped_cols:
        pass  # silently skip unmapped columns

    df = df[valid_cols].copy()
    # Replace NaN with None for psycopg2
    df = df.where(pd.notna(df), None)

    # Comprehensive value converter: handles all numpy/pandas types psycopg2 can't adapt.
    import numpy as np
    import pandas as pd_mod
    import math
    from datetime import datetime as _dt, date as _date

    _NULL_STRS  = {'—', '–', 'n/a', 'na', 'nil', 'none', 'null', 'tbd', 'n.a.', 'unlimited', 'n.a'}
    _DATE_FMTS  = ('%d-%b-%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y',
                   '%d-%m-%Y', '%b-%Y', '%Y/%m/%d', '%d %b %Y')
    # Boolean indicator sets — used only in cast_val for schema-boolean columns
    _BOOL_TRUE  = {'yes', 'true', 'y', 'on', '', '1', 'x'}
    _BOOL_FALSE = {'no', 'false', 'n', 'off', '', '0'}

    def to_native(v):
        if v is None:
            return None
        # pandas NaT / NA
        if v is pd_mod.NaT:
            return None
        try:
            if pd_mod.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        # pandas Timestamp -> python date
        if isinstance(v, pd_mod.Timestamp):
            return v.to_pydatetime()
        # numpy bool (before integer — np.bool_ is subclass of int)
        if isinstance(v, np.bool_):
            return bool(v)
        # numpy integer
        if isinstance(v, np.integer):
            return int(v)
        # numpy float — guard against NaN
        if isinstance(v, np.floating):
            f = float(v)
            return None if math.isnan(f) else f
        # fallback: any numpy scalar with .item()
        if hasattr(v, 'item'):
            try:
                return v.item()
            except Exception:
                pass
        # pandas Series (duplicate column names return Series instead of scalar)
        if isinstance(v, pd_mod.Series):
            v = v.iloc[0] if len(v) > 0 else None
            return to_native(v)
        if isinstance(v, str):
            s = v.strip().lstrip("'")  # strip Excel apostrophe-prefix trick
            if not s:
                return None
            sl = s.lower()
            # Null indicators
            if sl in _NULL_STRS:
                return None
            # Percentage strings  "18%" -> 18.0
            if s.endswith('%'):
                try:
                    return float(s[:-1].replace(',', ''))
                except ValueError:
                    pass
            # Date strings "08-Jan-2025" etc.
            for fmt in _DATE_FMTS:
                try:
                    return _dt.strptime(s, fmt).date()
                except ValueError:
                    pass
            # Pure comma-numeric "1,250.50" -> 1250.5
            stripped = s.replace(',', '')
            if stripped and stripped.lstrip('-').replace('.', '', 1).isdigit():
                try:
                    return float(stripped) if '.' in stripped else int(stripped)
                except ValueError:
                    pass
            return s
        # Python float NaN guard
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    rows_inserted = 0
    rows_skipped = 0

    if not valid_cols:
        return 0, len(df)

    cols_str = ", ".join(f'"{c}"' for c in valid_cols)
    placeholders = ", ".join(["%s"] * len(valid_cols))

    if conflict_col and conflict_col in valid_cols:
        update_cols = [c for c in valid_cols if c != conflict_col and c not in ('id', 'created_at')]
        if update_cols:
            update_str = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
            sql = f"""
                INSERT INTO {table} ({cols_str})
                VALUES ({placeholders})
                ON CONFLICT ("{conflict_col}") DO UPDATE SET {update_str}
            """
        else:
            sql = f"""
                INSERT INTO {table} ({cols_str})
                VALUES ({placeholders})
                ON CONFLICT ("{conflict_col}") DO NOTHING
            """
    else:
        sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    for _, row in df.iterrows():
        def cast_val(c, v):
            v = to_native(v)
            if c in bool_cols:
                if v is None:
                    return None
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return bool(v)
                if isinstance(v, str):
                    sl = v.strip().lstrip("'").lower()
                    if sl in _BOOL_TRUE:
                        return True
                    if sl in _BOOL_FALSE:
                        return False
                return bool(v)  # truthy/falsy for anything else
            return v
        values = tuple(cast_val(c, row[c]) for c in valid_cols)
        try:
            cur.execute(sql, values)
            rows_inserted += 1
        except Exception:
            conn.rollback()  # clear error state so next row can proceed
            rows_skipped += 1
            # re-open cursor after rollback
            cur = conn.cursor()

    conn.commit()
    cur.close()
    return rows_inserted, rows_skipped


# ─────────────────────────────────────────────
#  Individual file loaders
# ─────────────────────────────────────────────

def load_vendors(conn):
    df = read_nmi_excel("01_Vendor_Master.xlsx")
    col_map = {
        "Vendor ID": "vendor_id", "Vendor Name": "vendor_name",
        "Short Name": "short_name", "Category": "category",
        "Currency": "currency", "Country": "country",
        "Tax ID / NTN": "tax_id", "GST/VAT No.": "gst_vat_no",
        "Address": "address", "City": "city", "Postal Code": "postal_code",
        "Phone": "phone", "Email": "email", "Website": "website",
        "Payment Terms": "payment_terms", "Payment Method": "payment_method",
        "Bank Name": "bank_name", "Bank Account No.": "bank_account_no",
        "IBAN / SWIFT": "iban_swift", "Credit Limit": "credit_limit",
        "Incoterms": "incoterms", "Lead Time (days)": "lead_time_days",
        "Min Order Qty": "min_order_qty", "Contact Person": "contact_person",
        "Vendor Rating": "vendor_rating", "Hold Status": "hold_status",
        "Hold Reason": "hold_reason", "Approved By": "approved_by", "Active": "active",
    }
    return upsert_df(conn, df, "vendors", "vendor_id", col_map, "01_Vendor_Master.xlsx")


def load_items(conn):
    df = read_nmi_excel("02_Item_Product_Master.xlsx")
    col_map = {
        "Item Code": "item_code", "Item Description": "item_description",
        "Item Type": "item_type", "Category": "category", "Sub-Category": "sub_category",
        "UOM": "uom", "Std. Unit Cost": "std_unit_cost", "Currency": "currency",
        "Min Order Qty": "min_order_qty", "Lead Time (days)": "lead_time_days",
        "Reorder Point": "reorder_point", "Safety Stock": "safety_stock",
        "GL Account": "gl_account", "Cost Center": "cost_center", "Tax Code": "tax_code",
        "HS Code": "hs_code", "Weight KG": "weight_kg",
        "Country of Origin": "country_of_origin", "Shelf Life (days)": "shelf_life_days",
        "QC Required": "qc_required", "Hazardous": "hazardous", "Active": "active",
        "Odoo Ref": "odoo_ref", "D365 Item No.": "erp_ref_d365",
        "SAP Mat. No.": "erp_ref_sap", "Oracle Item No.": "erp_ref_oracle",
    }
    return upsert_df(conn, df, "items", "item_code", col_map, "02_Item_Product_Master.xlsx")


def load_chart_of_accounts(conn):
    df = read_nmi_excel("03_Chart_of_Accounts.xlsx")
    col_map = {
        "Account Code": "account_code", "Account Name": "account_name",
        "Account Type": "account_type", "Sub-Type": "sub_type",
        "Currency": "currency", "Normal Balance": "normal_balance",
        "P&L / BS": "pl_bs", "Cost Center": "cost_center",
        "Parent Account": "parent_account", "Tax Applicable": "tax_applicable",
        "Description": "description", "Odoo Account": "odoo_account",
        "Active": "active",
    }
    return upsert_df(conn, df, "chart_of_accounts", "account_code", col_map)


def load_cost_centers(conn):
    df = read_nmi_excel("04_Cost_Center_Master.xlsx")
    col_map = {
        "Cost Center Code": "cost_center_code", "Cost Center Name": "cost_center_name",
        "Department": "department", "Type": "type", "Location": "location",
        "Manager / Owner": "manager", "Budget Holder": "budget_holder",
        "Annual Budget (PKR)": "annual_budget_pkr", "Annual Budget (USD eq.)": "annual_budget_usd",
        "Currency": "currency", "Company Code": "company_code",
        "Profit Center": "profit_center", "Parent CC": "parent_cc",
        "GL Account Prefix": "gl_account_prefix", "Active": "active",
    }
    return upsert_df(conn, df, "cost_centers", "cost_center_code", col_map)


def load_employees(conn):
    df = read_nmi_excel("05_Employee_User_Master.xlsx")
    col_map = {
        "User ID": "user_id", "Full Name": "full_name", "Username": "username",
        "Email": "email", "Department": "department", "Job Title": "job_title",
        "Role": "role", "Approval Limit (PKR)": "approval_limit_pkr",
        "Approval Limit (USD)": "approval_limit_usd", "Cost Center": "cost_center",
        "Company Code": "company_code", "Location": "location",
        "Manager": "manager", "ERP Access Level": "erp_access_level", "Active": "active",
    }
    return upsert_df(conn, df, "employees", "user_id", col_map)


def load_exchange_rates(conn):
    df = read_nmi_excel("06_Currency_Exchange_Rates.xlsx")
    col_map = {
        "Period": "period", "From Currency": "from_currency", "To Currency": "to_currency",
        "Exchange Rate": "exchange_rate", "Rate Type": "rate_type",
        "Effective Date": "effective_date", "Expiry Date": "expiry_date",
        "Source": "source", "Entered By": "entered_by", "Status": "status",
    }
    return upsert_df(conn, df, "exchange_rates", None, col_map)


def load_uom_master(conn):
    df = read_nmi_excel("07_UOM_Master.xlsx")
    col_map = {
        "UOM Code": "uom_code", "UOM Name": "uom_name", "UOM Type": "uom_type",
        "Base UOM": "base_uom", "Conversion Factor": "conversion_factor",
        "Decimal Places": "decimal_places", "Description": "description",
        "Odoo UOM": "odoo_uom", "Active": "active",
    }
    return upsert_df(conn, df, "uom_master", "uom_code", col_map)


def load_tax_codes(conn):
    df = read_nmi_excel("08_Tax_Code_Master.xlsx")
    col_map = {
        "Tax Code": "tax_code", "Tax Name": "tax_name", "Tax Type": "tax_type",
        "Rate %": "rate_pct", "Currency": "currency", "Country": "country",
        "Applicable To": "applicable_to", "GL Account": "gl_account",
        "Jurisdiction": "jurisdiction", "Recoverable": "recoverable",
        "Exempt": "exempt", "Description": "description", "Active": "active",
    }
    return upsert_df(conn, df, "tax_codes", "tax_code", col_map)


def load_payment_terms(conn):
    df = read_nmi_excel("09_Payment_Terms_Master.xlsx")
    col_map = {
        "Term Code": "term_code", "Term Description": "term_description",
        "Net Days": "net_days", "Discount % if Paid Early": "discount_pct",
        "Discount Days": "discount_days", "Penalty % if Late": "penalty_pct",
        "Penalty Grace Days": "penalty_grace_days", "Base Date": "base_date",
        "Currency": "currency", "Applicable To": "applicable_to",
        "ERP Term Code (Odoo)": "erp_code_odoo", "ERP Term Code (D365)": "erp_code_d365",
        "ERP Term Code (SAP)": "erp_code_sap", "ERP Term Code (Oracle)": "erp_code_oracle",
        "Active": "active",
    }
    return upsert_df(conn, df, "payment_terms", "term_code", col_map)


def load_warehouses(conn):
    df = read_nmi_excel("10_Warehouse_Location_Master.xlsx")
    col_map = {
        "Warehouse Code": "warehouse_code", "Warehouse Name": "warehouse_name",
        "Type": "type", "Address": "address", "City": "city", "Country": "country",
        "Manager": "manager", "Capacity SQM": "capacity_sqm",
        "Capacity Pallets": "capacity_pallets", "Temp. Controlled": "temp_controlled",
        "Hazmat Approved": "hazmat_approved", "Operating Hours": "operating_hours",
        "Company Code": "company_code", "Odoo WH Code": "odoo_wh_code",
        "SAP Plant": "erp_plant_sap", "D365 Site": "erp_site_d365", "Active": "active",
    }
    return upsert_df(conn, df, "warehouses", "warehouse_code", col_map)


def load_companies(conn):
    df = read_nmi_excel("11_Company_Entity_Master.xlsx")
    col_map = {
        "Company Code": "company_code", "Legal Name": "legal_name",
        "Short Name": "short_name", "Country": "country", "Currency": "currency",
        "Tax Reg. No.": "tax_reg_no", "GST/VAT No.": "gst_vat_no",
        "Registered Address": "registered_address", "City": "city",
        "Fiscal Year Start": "fiscal_year_start", "Fiscal Year End": "fiscal_year_end",
        "Chart of Accounts": "chart_of_accounts", "Bank Account (Primary)": "bank_account",
        "Industry": "industry", "Parent Company": "parent_company",
        "ERP Company Code": "erp_company_code", "Active": "active",
    }
    return upsert_df(conn, df, "companies", "company_code", col_map)


def load_buyers(conn):
    df = read_nmi_excel("12_Buyer_Purchasing_Agent_Master.xlsx")
    col_map = {
        "Buyer ID": "buyer_id", "Buyer Name": "buyer_name", "Email": "email",
        "Phone": "phone", "Category Responsibility": "category_responsibility",
        "Spend Limit (USD)": "spend_limit_usd", "Preferred Vendors (IDs)": "preferred_vendor_ids",
        "Active POs": "active_pos", "Languages": "languages",
        "Location": "location", "Reporting To": "reporting_to", "Active": "active",
    }
    return upsert_df(conn, df, "buyers", "buyer_id", col_map)


def load_purchase_requisitions(conn):
    df = read_nmi_excel("13_Purchase_Requisitions.xlsx")
    col_map = {
        "PR Number": "pr_number", "PR Date": "pr_date", "Requester": "requester",
        "Department": "department", "Cost Center": "cost_center",
        "Item Code": "item_code", "Item Description": "item_description",
        "Qty": "qty", "UOM": "uom", "Est. Unit Price": "est_unit_price",
        "Currency": "currency", "Est. Total": "est_total",
        "Preferred Vendor": "preferred_vendor", "Vendor Name": "vendor_name",
        "Required By Date": "required_by_date", "Business Justification": "business_justification",
        "Priority": "priority", "Budget Code": "budget_code",
        "Budget Amount": "budget_amount", "Variance to Budget": "variance_to_budget",
        "Approval Required": "approval_required", "Approval Status": "approval_status",
        "Approved By": "approved_by", "Approval Date": "approval_date",
        "Exception Flag": "exception_flag", "Notes": "notes",
    }
    return upsert_df(conn, df, "purchase_requisitions", "pr_number", col_map)


def load_approved_supplier_list(conn):
    df = read_nmi_excel("14_Approved_Supplier_List.xlsx")
    col_map = {
        "ASL ID": "asl_id", "Vendor ID": "vendor_id", "Vendor Name": "vendor_name",
        "Item Code": "item_code", "Item Category": "item_category",
        "Approval Status": "approval_status", "Preferred Rank": "preferred_rank",
        "Approved By": "approved_by", "Approval Date": "approval_date",
        "Expiry Date": "expiry_date", "Annual Spend Cap (USD)": "annual_spend_cap_usd",
        "YTD Spend (USD)": "ytd_spend_usd", "Qualification Basis": "qualification_basis",
        "Quality Cert.": "quality_cert", "Last Audit Date": "last_audit_date",
        "Notes": "notes",
    }
    return upsert_df(conn, df, "approved_supplier_list", "asl_id", col_map)


def load_vendor_evaluations(conn):
    df = read_nmi_excel("15_Vendor_Evaluation_Scorecard.xlsx")
    col_map = {
        "Scorecard ID": "scorecard_id", "Vendor ID": "vendor_id",
        "Vendor Name": "vendor_name", "Evaluation Period": "evaluation_period",
        "Evaluator": "evaluator", "On-Time Delivery %": "on_time_delivery_pct",
        "Quality Score /100": "quality_score", "Invoice Accuracy %": "invoice_accuracy_pct",
        "Responsiveness /10": "responsiveness_score", "Compliance Score /10": "compliance_score",
        "Price Competitiveness /10": "price_competitiveness",
        "Overall Score /100": "overall_score", "Rating": "rating",
        "Issues Noted": "issues_noted", "Action Required": "action_required",
        "Next Review": "next_review",
    }
    return upsert_df(conn, df, "vendor_evaluations", "scorecard_id", col_map)


def load_rfq_headers(conn):
    df = read_nmi_excel("16_Request_for_Quotation.xlsx")
    col_map = {
        "RFQ Number": "rfq_number", "RFQ Date": "rfq_date",
        "PR Reference": "pr_reference", "Item Code": "item_code",
        "Item Description": "item_description", "Qty Required": "qty_required",
        "UOM": "uom", "Target Price": "target_price", "Currency": "currency",
        "Vendors Invited": "vendors_invited", "No. of Vendors": "no_of_vendors",
        "RFQ Deadline": "rfq_deadline", "Submission Method": "submission_method",
        "Buyer": "buyer", "Status": "status", "Selected Vendor": "selected_vendor",
        "Notes": "notes",
    }
    return upsert_df(conn, df, "rfq_headers", "rfq_number", col_map)


def load_vendor_quotes(conn):
    df = read_nmi_excel("17_Vendor_Quotes_Bids.xlsx")
    col_map = {
        "Quote ID": "quote_id", "RFQ Reference": "rfq_reference",
        "Vendor ID": "vendor_id", "Vendor Name": "vendor_name",
        "Item Code": "item_code", "Qty Quoted": "qty_quoted",
        "Unit Price": "unit_price", "Currency": "currency",
        "Total Quote Value": "total_quote_value", "Lead Time (days)": "lead_time_days",
        "Validity Days": "validity_days", "Payment Terms": "payment_terms",
        "Delivery Terms": "delivery_terms", "Tax Rate": "tax_rate",
        "Total incl. Tax": "total_incl_tax",
        "Technical Compliance": "technical_compliance",
        "Recommended": "recommended", "Rejection Reason": "rejection_reason",
    }
    return upsert_df(conn, df, "vendor_quotes", "quote_id", col_map)


def load_contracts(conn):
    df = read_nmi_excel("19_Contracts_Master.xlsx")
    col_map = {
        "Contract No.": "contract_no", "Vendor ID": "vendor_id",
        "Vendor Name": "vendor_name", "Contract Type": "contract_type",
        "Category": "category", "Start Date": "start_date", "End Date": "end_date",
        "Contract Value": "contract_value", "Currency": "currency",
        "Committed Spend": "committed_spend", "YTD Spend": "ytd_spend",
        "Balance": "balance", "Payment Terms": "payment_terms",
        "Auto-Renew": "auto_renew", "Notice Period": "notice_period_days",
        "Key SLA": "key_sla", "Contract Owner": "contract_owner",
        "Status": "status", "Notes": "notes",
    }
    return upsert_df(conn, df, "contracts", "contract_no", col_map)


def load_po_headers(conn):
    df = read_nmi_excel("20_Purchase_Orders_Header.xlsx")
    col_map = {
        "PO Number": "po_number", "PO Date": "po_date",
        "PR Reference": "pr_reference", "Vendor ID": "vendor_id",
        "Vendor Name": "vendor_name", "Buyer": "buyer",
        "Payment Terms": "payment_terms", "Currency": "currency",
        "Delivery Address": "delivery_address",
        "Requested Delivery": "requested_delivery",
        "Promised Delivery": "promised_delivery", "PO Subtotal": "po_subtotal",
        "Tax Amount": "tax_amount", "PO Grand Total": "po_grand_total",
        "Approval Status": "approval_status", "Approved By": "approved_by",
        "Approval Date": "approval_date", "PO Status": "po_status",
        "ERP Doc Type": "erp_doc_type",
        "Exception Flag": "exception_flag", "Notes": "notes",
    }
    return upsert_df(conn, df, "po_headers", "po_number", col_map)


def load_po_line_items(conn):
    df = read_nmi_excel("21_PO_Line_Items.xlsx")
    col_map = {
        "Line ID": "line_id", "PO Number": "po_number", "Line No.": "line_no",
        "Item Code": "item_code", "Item Description": "item_description",
        "Qty Ordered": "qty_ordered", "UOM": "uom", "Unit Price": "unit_price",
        "Currency": "currency", "Discount %": "discount_pct",
        "Net Unit Price": "net_unit_price", "Line Total": "line_total",
        "Tax Code": "tax_code", "Tax Amount": "tax_amount",
        "Line Total incl. Tax": "line_total_incl_tax",
        "GL Account": "gl_account", "Cost Center": "cost_center",
        "Delivery Address": "delivery_address", "Req. Delivery": "req_delivery_date",
        "Status": "status", "Notes": "notes",
    }
    return upsert_df(conn, df, "po_line_items", "line_id", col_map)


def load_grn_headers(conn):
    df = read_nmi_excel("26_Goods_Receipt_Notes.xlsx")
    col_map = {
        "GRN Number": "grn_number", "GRN Date": "grn_date",
        "PO Reference": "po_reference", "Vendor ID": "vendor_id",
        "Vendor Name": "vendor_name", "Received By": "received_by",
        "Warehouse": "warehouse", "Delivery Note No.": "delivery_note_no",
        "Carrier": "carrier", "Airway Bill / BOL": "airway_bill_bol",
        "Packages Received": "packages_received", "Total Weight KG": "total_weight_kg",
        "GRN Status": "grn_status", "QC Status": "qc_status",
        "Exception Flag": "exception_flag", "Notes": "notes",
    }
    return upsert_df(conn, df, "grn_headers", "grn_number", col_map)


def load_grn_line_items(conn):
    df = read_nmi_excel("27_GRN_Line_Items.xlsx")
    col_map = {
        "GRN Line ID": "grn_line_id", "GRN Number": "grn_number",
        "PO Number": "po_number", "Item Code": "item_code",
        "Item Description": "item_description", "PO Qty": "po_qty",
        "Received Qty": "received_qty", "Variance Qty": "variance_qty",
        "UOM": "uom", "Unit Cost": "unit_cost", "Currency": "currency",
        "Line Value": "line_value", "Lot / Batch No.": "lot_batch_no",
        "Serial Numbers": "serial_numbers", "Expiry Date": "expiry_date",
        "Storage Location": "storage_location", "QC Status": "qc_status",
        "Notes": "notes",
    }
    return upsert_df(conn, df, "grn_line_items", "grn_line_id", col_map)


def load_vendor_invoices(conn):
    df = read_nmi_excel("32_Vendor_Invoices.xlsx")
    col_map = {
        "Invoice No.": "invoice_no", "Vendor Invoice No.": "vendor_invoice_no",
        "Invoice Date": "invoice_date", "PO Reference": "po_reference",
        "GRN Reference": "grn_reference", "Vendor ID": "vendor_id",
        "Vendor Name": "vendor_name", "Invoice Type": "invoice_type",
        "Subtotal": "subtotal", "Tax Amount": "tax_amount",
        "Invoice Total": "invoice_total", "Currency": "currency",
        "Payment Terms": "payment_terms", "Due Date": "due_date",
        "GL Account": "gl_account", "Cost Center": "cost_center",
        "AP Status": "ap_status", "3WM Status": "three_way_match_status",
        "Approved By": "approved_by", "Exception Flag": "exception_flag",
        "Notes": "notes",
    }
    return upsert_df(conn, df, "vendor_invoices", "invoice_no", col_map)


def load_invoice_line_items(conn):
    df = read_nmi_excel("33_Invoice_Line_Items.xlsx")
    col_map = {
        "INV Line ID": "inv_line_id", "Invoice No.": "invoice_no",
        "Line No.": "line_no", "Item Code": "item_code",
        "Item Description": "item_description", "Qty Invoiced": "qty_invoiced",
        "UOM": "uom", "Unit Price": "unit_price", "Currency": "currency",
        "Discount %": "discount_pct", "Net Price": "net_price",
        "Line Subtotal": "line_subtotal", "Tax Code": "tax_code",
        "Tax Amt": "tax_amt", "Line Total": "line_total",
        "GL Account": "gl_account", "Cost Center": "cost_center",
        "Exception": "exception", "Notes": "notes",
    }
    return upsert_df(conn, df, "invoice_line_items", "inv_line_id", col_map)


def load_three_way_match(conn):
    df = read_nmi_excel("31_Three_Way_Match_Log.xlsx")
    col_map = {
        "Match ID": "match_id", "PO Number": "po_number",
        "GRN Number": "grn_number", "Invoice Number": "invoice_number",
        "Vendor": "vendor", "Item Code": "item_code",
        "PO Qty": "po_qty", "GRN Qty": "grn_qty", "INV Qty": "inv_qty",
        "PO Price": "po_price", "INV Price": "inv_price",
        "Currency": "currency", "PO Total": "po_total",
        "GRN Value": "grn_value", "INV Total": "inv_total",
        "Qty Match": "qty_match", "Price Match": "price_match",
        "Value Match": "value_match", "3WM Result": "match_result",
        "Exception Type": "exception_type", "Action Required": "action_required",
        "Resolved": "resolved",
    }
    return upsert_df(conn, df, "three_way_match_log", "match_id", col_map)


def load_invoice_exceptions(conn):
    df = read_nmi_excel("35_Invoice_Exceptions_Log.xlsx")
    col_map = {
        "Exception ID": "exception_id", "Invoice No.": "invoice_no",
        "PO Reference": "po_reference", "Vendor": "vendor",
        "Exception Type": "exception_type", "Exception Date": "exception_date",
        "PO Amount": "po_amount", "Invoice Amount": "invoice_amount",
        "Currency": "currency", "Variance": "variance",
        "Variance %": "variance_pct", "Detected By": "detected_by",
        "Detection Method": "detection_method", "Assigned To": "assigned_to",
        "Status": "status", "Resolution": "resolution",
        "Resolved Date": "resolved_date", "Impact": "impact",
    }
    return upsert_df(conn, df, "invoice_exceptions", "exception_id", col_map)


def load_payment_proposals(conn):
    df = read_nmi_excel("39_Payment_Proposals.xlsx")
    col_map = {
        "Proposal ID": "proposal_id", "Proposal Date": "proposal_date",
        "Invoice No.": "invoice_no", "Vendor ID": "vendor_id",
        "Vendor Name": "vendor_name", "Invoice Amount": "invoice_amount",
        "Currency": "currency", "Due Date": "due_date",
        "Payment Date (Proposed)": "proposed_payment_date",
        "Early Pay Discount": "early_pay_discount_pct",
        "Discount Amount": "discount_amount", "Net Payment": "net_payment",
        "Payment Method": "payment_method", "Bank Account": "bank_account",
        "Included in Run": "included_in_run", "Status": "status", "Notes": "notes",
    }
    return upsert_df(conn, df, "payment_proposals", "proposal_id", col_map)


def load_payment_runs(conn):
    df = read_nmi_excel("40_Payment_Runs.xlsx")
    col_map = {
        "Payment Run ID": "payment_run_id", "Run Date": "run_date",
        "Run Type": "run_type", "No. of Payments": "no_of_payments",
        "Total Amount PKR": "total_amount_pkr", "Currencies": "currencies",
        "Run By": "run_by", "Approved By": "approved_by",
        "Bank File Ref": "bank_file_ref", "Status": "status", "Notes": "notes",
    }
    return upsert_df(conn, df, "payment_runs", "payment_run_id", col_map)


def load_payment_holds(conn):
    df = read_nmi_excel("44_Payment_Exceptions_Holds.xlsx")
    col_map = {
        "Exception ID": "exception_id", "Invoice No.": "invoice_no",
        "PO Reference": "po_reference", "Vendor": "vendor",
        "Hold Reason": "hold_reason", "Hold Date": "hold_date",
        "Invoice Amount": "invoice_amount", "Currency": "currency",
        "Held Amount": "held_amount", "Hold Owner": "hold_owner",
        "Status": "status", "Resolution": "resolution", "Release Date": "release_date",
    }
    return upsert_df(conn, df, "payment_holds", "exception_id", col_map)


def load_spend_analytics(conn):
    df = read_nmi_excel("47_Spend_Analytics_Dataset.xlsx")
    # Header is on row 0 for this file
    path = DATA_DIR / "47_Spend_Analytics_Dataset.xlsx"
    df = pd.read_excel(path, header=0)
    df = df.dropna(how='all')
    col_map = {
        "Transaction ID": "transaction_id", "Period": "period",
        "Month": "month", "Quarter": "quarter",
        "Vendor ID": "vendor_id", "Vendor Name": "vendor_name",
        "Category": "category", "Sub-Category": "sub_category",
        "Item Code": "item_code", "Description": "item_description",
        "Qty": "qty", "UOM": "uom", "Unit Price": "unit_price",
        "Currency": "currency", "Total Amount USD": "total_amount_usd",
        "Legal Entity": "legal_entity", "Cost Center": "cost_center",
        "GL Account": "gl_account", "PO Number": "po_number",
        "Buyer": "buyer", "Spend Classification": "spend_classification",
    }
    return upsert_df(conn, df, "spend_analytics", "transaction_id", col_map)


def load_budget_vs_actuals(conn):
    path = DATA_DIR / "48_Budget_vs_Actuals.xlsx"
    df = pd.read_excel(path, header=0)
    df = df.dropna(how='all')
    col_map = {
        "Cost Center": "cost_center", "Cost Center Name": "cost_center_name",
        "GL Account": "gl_account", "GL Account Name": "gl_account_name",
        "Category": "category",
        "Q1 Budget": "q1_budget", "Q1 Actual": "q1_actual",
        "Q1 Variance": "q1_variance", "Q1 Var%": "q1_variance_pct",
        "Q2 Budget": "q2_budget", "Q2 Actual": "q2_actual",
        "Q2 Variance": "q2_variance", "Q2 Var%": "q2_variance_pct",
        "Q3 Budget": "q3_budget", "Q3 Actual": "q3_actual",
        "Q3 Variance": "q3_variance", "Q3 Var%": "q3_variance_pct",
        "Q4 Budget": "q4_budget", "Q4 Actual": "q4_actual",
        "Q4 Variance": "q4_variance", "Q4 Var%": "q4_variance_pct",
        "FY Budget": "fy_budget", "FY Actual": "fy_actual",
        "FY Variance": "fy_variance", "FY Var%": "fy_variance_pct",
        "Status": "status", "Exception Flag": "exception_flag",
    }
    return upsert_df(conn, df, "budget_vs_actuals", None, col_map)


def load_vendor_performance(conn):
    path = DATA_DIR / "49_Vendor_Performance_Dashboard.xlsx"
    df = pd.read_excel(path, header=0)  # no title rows in this file
    df.columns = [str(c) for c in df.columns]
    keep = [c for c in df.columns if not c.startswith('Unnamed') and c.lower() != 'nan']
    df = df[keep].dropna(how='all')
    col_map = {
        "Vendor ID": "vendor_id", "Vendor Name": "vendor_name",
        "Category": "category", "Total POs": "total_pos",
        "Total Spend USD": "total_spend_usd",
        "On-Time Delivery %": "on_time_delivery_pct",
        "Quality Pass Rate %": "quality_pass_rate_pct",
        "Invoice Accuracy %": "invoice_accuracy_pct",
        "Price Compliance %": "price_compliance_pct",
        "Lead Time Days": "lead_time_days", "Defect Rate %": "defect_rate_pct",
        "Returns": "returns_count", "Disputes": "disputes_count",
        "Overall Score": "overall_score", "Rating": "rating",
        "Preferred": "preferred", "Comments": "comments",
        "Review Period": "review_period",
    }
    return upsert_df(conn, df, "vendor_performance", "vendor_id", col_map)


def load_duplicate_invoice_log(conn):
    path = DATA_DIR / "52_Duplicate_Invoice_Detection_Log.xlsx"
    df = pd.read_excel(path, header=0)  # no title rows in this file
    df.columns = [str(c) for c in df.columns]
    keep = [c for c in df.columns if not c.startswith('Unnamed') and c.lower() != 'nan']
    df = df[keep].dropna(how='all')
    col_map = {
        "Detection ID": "detection_id", "Detection Date": "detection_date",
        "Invoice 1": "invoice_1", "Invoice 2": "invoice_2",
        "Vendor ID": "vendor_id", "Vendor Name": "vendor_name",
        "Amount 1": "amount_1", "Amount 2": "amount_2", "Currency": "currency",
        "Match Criteria": "match_criteria", "Similarity %": "similarity_pct",
        "Detection Method": "detection_method", "Status": "status",
        "Action Taken": "action_taken", "Reviewed By": "reviewed_by",
        "Resolution Date": "resolution_date",
        "Savings Avoided USD": "savings_avoided_usd",
        "Exception Flag": "exception_flag",
    }
    return upsert_df(conn, df, "duplicate_invoice_log", "detection_id", col_map)


def load_audit_trail(conn):
    path = DATA_DIR / "53_Audit_Trail_Change_Log.xlsx"
    df = pd.read_excel(path, header=0)  # no title rows in this file
    df.columns = [str(c) for c in df.columns]
    keep = [c for c in df.columns if not c.startswith('Unnamed') and c.lower() != 'nan']
    df = df[keep].dropna(how='all')
    col_map = {
        "Log ID": "log_id", "Timestamp": "timestamp",
        "User ID": "user_id", "User Name": "user_name", "Role": "role",
        "Module": "module", "Transaction ID": "transaction_id",
        "Action": "action", "Field Changed": "field_changed",
        "Old Value": "old_value", "New Value": "new_value",
        "Reason": "reason", "IP Address": "ip_address",
        "ERP System": "erp_system", "Legal Entity": "legal_entity",
        "Change Category": "change_category", "Risk Flag": "risk_flag",
    }
    return upsert_df(conn, df, "audit_trail", "log_id", col_map)


def load_workflow_approval_matrix(conn):
    path = DATA_DIR / "56_Workflow_Approval_Matrix.xlsx"
    df = pd.read_excel(path, header=0)  # no title rows in this file
    df.columns = [str(c) for c in df.columns]
    keep = [c for c in df.columns if not c.startswith('Unnamed') and c.lower() != 'nan']
    df = df[keep].dropna(how='all')
    col_map = {
        "Workflow ID": "workflow_id", "Process": "process",
        "Document Type": "document_type",
        "Threshold": "threshold_min",
        "Currency": "currency",
        "L1 Approver": "l1_approver", "L1 Role": "l1_role", "L1 Limit": "l1_limit",
        "L2 Approver": "l2_approver", "L2 Role": "l2_role", "L2 Limit": "l2_limit",
        "L3 Approver": "l3_approver", "L3 Role": "l3_role",
        "SLA Hours": "sla_hours", "Escalation Hours": "escalation_hours",
        "Auto-Approve": "auto_approve", "Conditions": "conditions",
        "ERP Workflow Name": "erp_workflow_name",
        "Override Approver": "override_approver", "Status": "status",
    }
    return upsert_df(conn, df, "workflow_approval_matrix", "workflow_id", col_map)


# ─────────────────────────────────────────────
#  Loader registry
# ─────────────────────────────────────────────

LOADERS = {
    # group -> [(file_num, table_name, loader_fn)]
    "master": [
        ("01", "vendors",               load_vendors),
        ("02", "items",                 load_items),
        ("03", "chart_of_accounts",     load_chart_of_accounts),
        ("04", "cost_centers",          load_cost_centers),
        ("05", "employees",             load_employees),
        ("06", "exchange_rates",        load_exchange_rates),
        ("07", "uom_master",            load_uom_master),
        ("08", "tax_codes",             load_tax_codes),
        ("09", "payment_terms",         load_payment_terms),
        ("10", "warehouses",            load_warehouses),
        ("11", "companies",             load_companies),
        ("12", "buyers",                load_buyers),
    ],
    "procurement": [
        ("13", "purchase_requisitions", load_purchase_requisitions),
        ("14", "approved_supplier_list",load_approved_supplier_list),
        ("15", "vendor_evaluations",    load_vendor_evaluations),
        ("16", "rfq_headers",           load_rfq_headers),
        ("17", "vendor_quotes",         load_vendor_quotes),
        ("19", "contracts",             load_contracts),
    ],
    "purchase_orders": [
        ("20", "po_headers",            load_po_headers),
        ("21", "po_line_items",         load_po_line_items),
    ],
    "goods_receipt": [
        ("26", "grn_headers",           load_grn_headers),
        ("27", "grn_line_items",        load_grn_line_items),
    ],
    "invoicing": [
        ("31", "three_way_match_log",   load_three_way_match),
        ("32", "vendor_invoices",       load_vendor_invoices),
        ("33", "invoice_line_items",    load_invoice_line_items),
        ("35", "invoice_exceptions",    load_invoice_exceptions),
    ],
    "payments": [
        ("39", "payment_proposals",     load_payment_proposals),
        ("40", "payment_runs",          load_payment_runs),
        ("44", "payment_holds",         load_payment_holds),
    ],
    "analytics": [
        ("47", "spend_analytics",       load_spend_analytics),
        ("48", "budget_vs_actuals",     load_budget_vs_actuals),
        ("49", "vendor_performance",    load_vendor_performance),
        ("52", "duplicate_invoice_log", load_duplicate_invoice_log),
        ("53", "audit_trail",           load_audit_trail),
        ("56", "workflow_approval_matrix", load_workflow_approval_matrix),
    ],
}

ALL_LOADERS_FLAT = [item for group in LOADERS.values() for item in group]


def run_ingestion(file_filter: str = None, group_filter: str = None):
    conn = get_conn()
    cur = conn.cursor()

    total_loaded = 0
    total_skipped = 0
    errors = []

    loaders_to_run = []
    if group_filter:
        loaders_to_run = LOADERS.get(group_filter, [])
        if not loaders_to_run:
            print(f"Unknown group '{group_filter}'. Valid: {list(LOADERS.keys())}")
            return
    elif file_filter:
        loaders_to_run = [l for l in ALL_LOADERS_FLAT if l[0] == file_filter]
        if not loaders_to_run:
            print(f"No loader for file '{file_filter}'")
            return
    else:
        loaders_to_run = ALL_LOADERS_FLAT

    print(f"\nNMI Data Ingestion — {len(loaders_to_run)} files to load\n")
    print(f"{'File':<6} {'Table':<35} {'Loaded':>8} {'Skipped':>8}  Status")
    print("─" * 75)

    for file_num, table_name, loader_fn in loaders_to_run:
        started = datetime.now()
        try:
            loaded, skipped = loader_fn(conn)
            total_loaded += loaded
            total_skipped += skipped
            status = ""
            log_ingestion(cur, f"{file_num}_*.xlsx", table_name,
                          loaded, skipped, "Complete", started_at=started)
            conn.commit()
        except FileNotFoundError as e:
            status = "FILE NOT FOUND"
            errors.append((file_num, table_name, str(e)))
            loaded, skipped = 0, 0
            log_ingestion(cur, f"{file_num}_*.xlsx", table_name,
                          0, 0, "Failed", str(e), started)
            conn.commit()
        except Exception as e:
            status = f"{type(e).__name__}"
            errors.append((file_num, table_name, str(e)))
            loaded, skipped = 0, 0
            log_ingestion(cur, f"{file_num}_*.xlsx", table_name,
                          0, 0, "Failed", str(e)[:255], started)
            conn.commit()

        print(f"  {file_num:<4} {table_name:<35} {loaded:>8} {skipped:>8}  {status}")

    print("─" * 75)
    print(f"{'TOTAL':<40} {total_loaded:>8} {total_skipped:>8}")

    if errors:
        print(f"\n{len(errors)} error(s):")
        for file_num, table, msg in errors:
            print(f"   File {file_num} → {table}: {msg[:120]}")
    else:
        print(f"\nAll {len(loaders_to_run)} files loaded successfully.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sprint 1 NMI Data Ingestion")
    parser.add_argument("--file", help="Load only this file number (e.g. 01)")
    parser.add_argument("--group", help=f"Load only this group: {list(LOADERS.keys())}")
    args = parser.parse_args()

    run_ingestion(file_filter=args.file, group_filter=args.group)
