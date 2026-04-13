import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL")
db_available = False

def get_connection():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL not configured")
    return psycopg2.connect(DATABASE_URL)

@contextmanager
def get_cursor():
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

def init_database():
    global db_available
    try:
        with get_cursor() as cursor:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS procurement_records (
                id SERIAL PRIMARY KEY,
                year INTEGER,
                quarter TEXT,
                month TEXT,
                period TEXT,
                date TEXT,
                pr_number TEXT UNIQUE,
                description TEXT,
                department TEXT,
                contact_person TEXT,
                assign_to TEXT,
                budget REAL,
                budget_q1 REAL,
                budget_q2 REAL,
                budget_q3 REAL,
                budget_q4 REAL,
                source_method TEXT,
                status TEXT,
                supplier_details TEXT,
                supplier_rating TEXT,
                local_content_percentage REAL,
                pr_approval_scope_input TEXT,
                approving_authority TEXT,
                planned TEXT,
                target_date TEXT,
                actual_project_start TEXT,
                sla INTEGER,
                note TEXT,
                review_approval_scope_eval REAL,
                floating REAL,
                tender_submit_by_vendor REAL,
                evaluation REAL,
                award_approval REAL,
                contract_and_po REAL,
                pr_approval_scope_input_pd REAL,
                review_approval_scope_eval_pd REAL,
                floating_pd REAL,
                tender_submit_by_vendor_pd REAL,
                evaluation_pd REAL,
                award_approval_pd REAL,
                contract_and_po_pd REAL,
                total_days_pd REAL,
                review_approval_scope_eval_ad REAL,
                floating_ad REAL,
                tender_submit_by_vendor_ad REAL,
                evaluation_ad REAL,
                award_approval_ad REAL,
                contract_and_po_ad REAL,
                total_days_ad REAL,
                review_approval_scope_eval_pd_sla REAL,
                floating_pd_sla REAL,
                tender_submit_by_vendor_pd_sla REAL,
                evaluation_pd_sla REAL,
                award_approval_pd_sla REAL,
                contract_and_po_pd_sla REAL,
                review_approval_scope_eval_ad_sla REAL,
                floating_ad_sla REAL,
                tender_submit_by_vendor_ad_sla REAL,
                evaluation_ad_sla REAL,
                award_approval_ad_sla REAL,
                contract_and_po_ad_sla REAL,
                review_approval_scope_eval_diff_sla REAL,
                floating_diff_sla REAL,
                tender_submit_by_vendor_diff_sla REAL,
                evaluation_diff_sla REAL,
                award_approval_diff_sla REAL,
                contract_and_po_diff_sla REAL,
                project_status INTEGER,
                risk TEXT,
                duration INTEGER,
                last_status_date TEXT,
                status_duration INTEGER,
                status_sla INTEGER,
                status_co TEXT,
                escalate_48h TEXT,
                ceo_escalation TEXT,
                detailed_description TEXT,
                business_justification TEXT,
                expected_outcomes TEXT,
                impact_if_delayed TEXT,
                special_requirements TEXT,
                requester_name TEXT,
                requester_email TEXT,
                requester_department TEXT,
                project_manager TEXT,
                finance_approver TEXT,
                technical_reviewer TEXT,
                supplier_name TEXT,
                supplier_category TEXT,
                supplier_country TEXT,
                supplier_payment_terms TEXT,
                supplier_delivery_time INTEGER,
                supplier_quality_score REAL,
                supplier_past_performance TEXT,
                currency TEXT,
                exchange_rate REAL,
                budget_category TEXT,
                cost_center TEXT,
                tax_amount REAL,
                total_cost_with_tax REAL,
                priority_level TEXT,
                urgency TEXT,
                category TEXT,
                subcategory TEXT,
                tags TEXT,
                created_date TEXT,
                submitted_date TEXT,
                first_approval_date TEXT,
                final_approval_date TEXT,
                rejection_count INTEGER,
                rejection_reason TEXT,
                last_modified_by TEXT,
                last_modified_date TEXT,
                delivery_status TEXT,
                expected_delivery_date TEXT,
                actual_delivery_date TEXT,
                delivery_location TEXT,
                milestone_1_date TEXT,
                milestone_2_date TEXT,
                completion_percentage INTEGER,
                compliance_status TEXT,
                required_documents TEXT,
                documents_submitted TEXT,
                compliance_officer TEXT,
                regulatory_framework TEXT,
                audit_trail_url TEXT,
                contract_type TEXT,
                contract_duration_months INTEGER,
                warranty_period_months INTEGER,
                renewal_date TEXT,
                legal_review_status TEXT,
                on_time_delivery BOOLEAN,
                budget_variance_percentage REAL,
                quality_rating INTEGER,
                customer_satisfaction INTEGER,
                issues_reported INTEGER
            )
            """)
        db_available = True
        print("Database connected and initialized successfully")
    except Exception as e:
        db_available = False
        print(f"Database connection failed: {e}")
        print("Application will run without database functionality")

def get_record_count():
    if not db_available:
        return 0
    with get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as count FROM procurement_records")
        result = cursor.fetchone()
        return result['count'] if result else 0

def insert_records(records: list):
    if not db_available:
        print("Database not available - skipping record insertion")
        return
    with get_cursor() as cursor:
        for record in records:
            cursor.execute("""
                INSERT INTO procurement_records (
                    year, quarter, month, period, date, pr_number, description,
                    department, contact_person, assign_to, budget, budget_q1,
                    budget_q2, budget_q3, budget_q4, source_method, status,
                    supplier_details, supplier_rating, local_content_percentage,
                    pr_approval_scope_input, approving_authority, planned, target_date,
                    actual_project_start, sla, note, review_approval_scope_eval,
                    floating, tender_submit_by_vendor, evaluation, award_approval,
                    contract_and_po, pr_approval_scope_input_pd, review_approval_scope_eval_pd,
                    floating_pd, tender_submit_by_vendor_pd, evaluation_pd, award_approval_pd,
                    contract_and_po_pd, total_days_pd, review_approval_scope_eval_ad,
                    floating_ad, tender_submit_by_vendor_ad, evaluation_ad, award_approval_ad,
                    contract_and_po_ad, total_days_ad, review_approval_scope_eval_pd_sla,
                    floating_pd_sla, tender_submit_by_vendor_pd_sla, evaluation_pd_sla,
                    award_approval_pd_sla, contract_and_po_pd_sla, review_approval_scope_eval_ad_sla,
                    floating_ad_sla, tender_submit_by_vendor_ad_sla, evaluation_ad_sla,
                    award_approval_ad_sla, contract_and_po_ad_sla, review_approval_scope_eval_diff_sla,
                    floating_diff_sla, tender_submit_by_vendor_diff_sla, evaluation_diff_sla,
                    award_approval_diff_sla, contract_and_po_diff_sla, project_status,
                    risk, duration, last_status_date, status_duration, status_sla,
                    status_co, escalate_48h, ceo_escalation
                ) VALUES (
                    %(year)s, %(quarter)s, %(month)s, %(period)s, %(date)s,
                    %(pr_number)s, %(description)s, %(department)s, %(contact_person)s,
                    %(assign_to)s, %(budget)s, %(budget_q1)s, %(budget_q2)s,
                    %(budget_q3)s, %(budget_q4)s, %(source_method)s, %(status)s,
                    %(supplier_details)s, %(supplier_rating)s, %(local_content_percentage)s,
                    %(pr_approval_scope_input)s, %(approving_authority)s, %(planned)s, %(target_date)s,
                    %(actual_project_start)s, %(sla)s, %(note)s, %(review_approval_scope_eval)s,
                    %(floating)s, %(tender_submit_by_vendor)s, %(evaluation)s, %(award_approval)s,
                    %(contract_and_po)s, %(pr_approval_scope_input_pd)s, %(review_approval_scope_eval_pd)s,
                    %(floating_pd)s, %(tender_submit_by_vendor_pd)s, %(evaluation_pd)s, %(award_approval_pd)s,
                    %(contract_and_po_pd)s, %(total_days_pd)s, %(review_approval_scope_eval_ad)s,
                    %(floating_ad)s, %(tender_submit_by_vendor_ad)s, %(evaluation_ad)s, %(award_approval_ad)s,
                    %(contract_and_po_ad)s, %(total_days_ad)s, %(review_approval_scope_eval_pd_sla)s,
                    %(floating_pd_sla)s, %(tender_submit_by_vendor_pd_sla)s, %(evaluation_pd_sla)s,
                    %(award_approval_pd_sla)s, %(contract_and_po_pd_sla)s, %(review_approval_scope_eval_ad_sla)s,
                    %(floating_ad_sla)s, %(tender_submit_by_vendor_ad_sla)s, %(evaluation_ad_sla)s,
                    %(award_approval_ad_sla)s, %(contract_and_po_ad_sla)s, %(review_approval_scope_eval_diff_sla)s,
                    %(floating_diff_sla)s, %(tender_submit_by_vendor_diff_sla)s, %(evaluation_diff_sla)s,
                    %(award_approval_diff_sla)s, %(contract_and_po_diff_sla)s, %(project_status)s,
                    %(risk)s, %(duration)s, %(last_status_date)s, %(status_duration)s, %(status_sla)s,
                    %(status_co)s, %(escalate_48h)s, %(ceo_escalation)s
                ) ON CONFLICT (pr_number) DO NOTHING
            """, record)

def execute_query(sql: str):
    if not db_available:
        return []
    with get_cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()

def get_stats():
    if not db_available:
        return {
            "totalBudget": 0.0,
            "totalProjects": 0,
            "highRiskProjects": 0,
            "averageBudget": 0.0,
            "departmentCount": 0,
            "completedProjects": 0,
            "inProgressProjects": 0,
            "delayedProjects": 0
        }
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT 
                COALESCE(SUM(budget), 0) as total_budget,
                COUNT(*) as total_projects,
                COUNT(*) FILTER (WHERE risk = 'High') as high_risk_projects,
                COALESCE(AVG(budget), 0) as average_budget,
                COUNT(DISTINCT department) as department_count,
                COUNT(*) FILTER (WHERE project_status = 'Completed') as completed_projects,
                COUNT(*) FILTER (WHERE project_status = 'In Progress') as in_progress_projects,
                COUNT(*) FILTER (WHERE project_status = 'Delayed' OR 
                    (total_days_ad IS NOT NULL AND total_days_pd IS NOT NULL AND total_days_ad > total_days_pd)
                ) as delayed_projects
            FROM procurement_records
        """)
        result = cursor.fetchone()
        return {
            "totalBudget": float(result['total_budget']),
            "totalProjects": result['total_projects'],
            "highRiskProjects": result['high_risk_projects'],
            "averageBudget": float(result['average_budget']),
            "departmentCount": result['department_count'],
            "completedProjects": result['completed_projects'],
            "inProgressProjects": result['in_progress_projects'],
            "delayedProjects": result['delayed_projects']
        }
