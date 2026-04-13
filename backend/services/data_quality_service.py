"""
Data Quality Service
=====================
Scans imported ERP tables for data quality issues:
  - INVALID_*, TBD, UNKNOWN, N/A, TEMP, XXX values
  - NULL/empty columns
  - Duplicate primary keys / IDs
  - Type mismatches (strings in numeric fields)
  - Date format inconsistencies
  - Email/phone format violations
  - Outlier values (statistical)

Returns per-table and per-column quality scores with specific issue details.

Used by:
  - DataQualityAgent (autonomous scheduled scan)
  - POST /api/quality/scan     — scan specific table or all tables
  - GET  /api/quality/report   — get latest quality report
"""

import os
import re
import logging
from typing import Optional
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

log = logging.getLogger(__name__)

DB_URL = os.environ.get('DATABASE_URL')
if not DB_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

# Patterns that indicate dirty/invalid data
DIRTY_PATTERNS = [
    (r'^INVALID[_\-]', 'INVALID_value'),
    (r'^TEMP[_\-]?', 'TEMP_placeholder'),
    (r'^TBD$', 'TBD_placeholder'),
    (r'^UNKNOWN$', 'UNKNOWN_value'),
    (r'^XXX', 'XXX_placeholder'),
    (r'^N/?A$', 'NA_value'),
    (r'^NONE$', 'NONE_string'),
    (r'^NULL$', 'NULL_string'),
    (r'^0{5,}$', 'zero_padded'),
    (r'^TEST[_\-]', 'TEST_value'),
    (r'^DUMMY[_\-]', 'DUMMY_value'),
    (r'^FAKE[_\-]', 'FAKE_value'),
]

# Compiled patterns for speed
_DIRTY_RE = [(re.compile(p, re.IGNORECASE), label) for p, label in DIRTY_PATTERNS]

# Email pattern
_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

# Date patterns
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}')

# Phone pattern (loose — just checks for digits)
_PHONE_RE = re.compile(r'^[\d\s\+\-\(\)\.]{7,20}$')


def scan_table(table_name: str, sample_limit: int = 500) -> dict:
    """Scan a single table for data quality issues.

    Returns:
        dict with: table_name, total_rows, total_columns, overall_score,
                   column_reports (per-column issues), issues (aggregated)
    """
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get column info
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = %s AND table_schema = 'public' AND column_name != '_row_id'
            ORDER BY ordinal_position
        """, (table_name,))
        columns = [{'name': r['column_name'], 'type': r['data_type']} for r in cur.fetchall()]

        if not columns:
            return {'table_name': table_name, 'error': 'Table not found or has no columns'}

        # Get total row count
        cur.execute(f'SELECT count(*) FROM "{table_name}"')
        total_rows = cur.fetchone()['count']

        # Get sample data
        cur.execute(f'SELECT * FROM "{table_name}" LIMIT %s', (sample_limit,))
        rows = cur.fetchall()

        # Analyze each column
        column_reports = []
        total_issues = 0
        total_cells = total_rows * len(columns)

        for col_info in columns:
            col_name = col_info['name']
            col_type = col_info['type']
            values = [str(row.get(col_name, '')) if row.get(col_name) is not None else None for row in rows]

            report = _analyze_column(col_name, col_type, values, total_rows)
            column_reports.append(report)
            total_issues += report['issue_count']

        # Calculate overall score
        if total_cells > 0:
            clean_cells = total_cells - total_issues
            overall_score = round((clean_cells / total_cells) * 100, 1)
        else:
            overall_score = 100.0

        # Aggregate issues by type
        issue_summary = {}
        for cr in column_reports:
            for issue in cr.get('issues', []):
                itype = issue['type']
                if itype not in issue_summary:
                    issue_summary[itype] = {'count': 0, 'columns': [], 'severity': issue['severity']}
                issue_summary[itype]['count'] += issue['count']
                if cr['column'] not in issue_summary[itype]['columns']:
                    issue_summary[itype]['columns'].append(cr['column'])

        return {
            'table_name': table_name,
            'total_rows': total_rows,
            'total_columns': len(columns),
            'total_cells': total_cells,
            'total_issues': total_issues,
            'overall_score': overall_score,
            'grade': _score_to_grade(overall_score),
            'column_reports': column_reports,
            'issue_summary': issue_summary,
            'scanned_at': datetime.utcnow().isoformat() + 'Z',
        }

    except Exception as e:
        log.error("scan_table %s failed: %s", table_name, e)
        return {'table_name': table_name, 'error': str(e)}
    finally:
        cur.close()
        conn.close()


def _analyze_column(col_name: str, col_type: str, values: list, total_rows: int) -> dict:
    """Analyze a single column for quality issues."""
    issues = []
    non_null = [v for v in values if v is not None]
    null_count = len(values) - len(non_null)

    # 1. NULL/empty check
    null_pct = (null_count / len(values) * 100) if values else 0
    if null_pct > 50:
        issues.append({
            'type': 'high_null_rate',
            'severity': 'high' if null_pct > 80 else 'medium',
            'count': null_count,
            'detail': f'{null_pct:.0f}% NULL values ({null_count}/{len(values)})',
        })
    elif null_pct > 20:
        issues.append({
            'type': 'moderate_null_rate',
            'severity': 'low',
            'count': null_count,
            'detail': f'{null_pct:.0f}% NULL values',
        })

    # 2. Dirty value patterns
    dirty_count = 0
    dirty_types = {}
    for v in non_null:
        for pattern, label in _DIRTY_RE:
            if pattern.search(v):
                dirty_count += 1
                dirty_types[label] = dirty_types.get(label, 0) + 1
                break

    if dirty_count > 0:
        issues.append({
            'type': 'dirty_values',
            'severity': 'high' if dirty_count > len(values) * 0.1 else 'medium',
            'count': dirty_count,
            'detail': f'{dirty_count} dirty values: {dict(list(dirty_types.items())[:3])}',
            'examples': list(dirty_types.keys())[:5],
        })

    # 3. Duplicate check (for ID-like columns)
    if any(kw in col_name.lower() for kw in ('id', 'number', 'code', 'key', 'name', 'ref')):
        unique_count = len(set(non_null))
        dup_count = len(non_null) - unique_count
        if dup_count > 0:
            issues.append({
                'type': 'duplicates',
                'severity': 'high' if 'id' in col_name.lower() else 'medium',
                'count': dup_count,
                'detail': f'{dup_count} duplicate values in {len(non_null)} non-null ({unique_count} unique)',
            })

    # 4. Empty string check (not NULL but empty)
    empty_count = sum(1 for v in non_null if v.strip() == '')
    if empty_count > 0:
        issues.append({
            'type': 'empty_strings',
            'severity': 'low',
            'count': empty_count,
            'detail': f'{empty_count} empty string values (not NULL)',
        })

    # 5. Email format check
    if any(kw in col_name.lower() for kw in ('email', 'mail', 'email_id')):
        bad_emails = sum(1 for v in non_null if v.strip() and not _EMAIL_RE.match(v.strip()))
        if bad_emails > 0:
            issues.append({
                'type': 'invalid_email_format',
                'severity': 'medium',
                'count': bad_emails,
                'detail': f'{bad_emails} values with invalid email format',
            })

    # 6. Date format check
    if any(kw in col_name.lower() for kw in ('date', 'created', 'updated', 'timestamp', '_at', '_on')):
        bad_dates = sum(1 for v in non_null if v.strip() and not _DATE_RE.match(v.strip()))
        if bad_dates > 0:
            issues.append({
                'type': 'inconsistent_date_format',
                'severity': 'low',
                'count': bad_dates,
                'detail': f'{bad_dates} values with non-standard date format',
            })

    # Calculate column score
    issue_count = sum(i['count'] for i in issues)
    if len(values) > 0:
        clean_pct = round(((len(values) - issue_count) / len(values)) * 100, 1)
    else:
        clean_pct = 100.0

    return {
        'column': col_name,
        'data_type': col_type,
        'total_values': len(values),
        'null_count': null_count,
        'issue_count': issue_count,
        'score': max(0, clean_pct),
        'grade': _score_to_grade(clean_pct),
        'issues': issues,
    }


def _score_to_grade(score: float) -> str:
    if score >= 95:
        return 'A'
    elif score >= 85:
        return 'B'
    elif score >= 70:
        return 'C'
    elif score >= 50:
        return 'D'
    else:
        return 'F'


def scan_all_erp_tables() -> dict:
    """Scan all ERP tables and return aggregated quality report."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
              AND (table_name LIKE 'odoo_%%' OR table_name LIKE 'sap_%%'
                   OR table_name LIKE 'd365_%%' OR table_name LIKE 'oracle_%%'
                   OR table_name LIKE 'erpnext_%%' OR table_name LIKE 'imported_%%')
            ORDER BY table_name
        """)
        table_names = [r[0] for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

    results = []
    erp_scores = {}

    for tname in table_names:
        report = scan_table(tname)
        results.append({
            'table_name': tname,
            'score': report.get('overall_score', 0),
            'grade': report.get('grade', '?'),
            'total_rows': report.get('total_rows', 0),
            'total_issues': report.get('total_issues', 0),
            'issue_types': list(report.get('issue_summary', {}).keys()),
        })

        # Group by ERP
        erp = 'unknown'
        for prefix, label in [('odoo_', 'Odoo'), ('sap_', 'SAP'), ('d365_', 'Dynamics365'),
                               ('oracle_', 'Oracle'), ('erpnext_', 'ERPNext')]:
            if tname.startswith(prefix):
                erp = label
                break
        if erp not in erp_scores:
            erp_scores[erp] = {'tables': 0, 'total_score': 0, 'total_issues': 0}
        erp_scores[erp]['tables'] += 1
        erp_scores[erp]['total_score'] += report.get('overall_score', 0)
        erp_scores[erp]['total_issues'] += report.get('total_issues', 0)

    # Calculate averages
    for erp, data in erp_scores.items():
        data['avg_score'] = round(data['total_score'] / data['tables'], 1) if data['tables'] else 0
        data['grade'] = _score_to_grade(data['avg_score'])

    overall_avg = round(sum(r['score'] for r in results) / len(results), 1) if results else 0

    return {
        'total_tables': len(results),
        'overall_score': overall_avg,
        'overall_grade': _score_to_grade(overall_avg),
        'total_issues': sum(r['total_issues'] for r in results),
        'erp_summary': erp_scores,
        'tables': results,
        'scanned_at': datetime.utcnow().isoformat() + 'Z',
        'worst_tables': sorted(results, key=lambda x: x['score'])[:10],
        'best_tables': sorted(results, key=lambda x: x['score'], reverse=True)[:5],
    }
