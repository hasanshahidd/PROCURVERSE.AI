"""
Duplicate Invoice Detector — G-04 Dev Spec 2.0
================================================
Detects duplicate invoices using 3 methods:
1. Exact hash match (SHA-256)
2. Fuzzy match (vendor + amount +/- 2% + date +/- 7 days + invoice# Levenshtein > 80%)
3. Cross-channel detection (same vendor + amount + date, different source)

Usage:
    from backend.services.duplicate_invoice_detector import DuplicateInvoiceDetector
    detector = DuplicateInvoiceDetector()
    result = detector.check(invoice_data)
"""
import hashlib
import logging
import os
import json
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)
DB_URL = os.environ.get('DATABASE_URL')

# ── Thresholds ──
AMOUNT_TOLERANCE_PCT = 0.02      # ±2%
DATE_WINDOW_DAYS = 7             # ±7 days
LEVENSHTEIN_THRESHOLD = 0.80     # 80% similarity
HASH_FIELDS = ['vendor_id', 'invoice_number', 'amount', 'currency']


def _levenshtein_ratio(s1: str, s2: str) -> float:
    """Compute Levenshtein similarity ratio (0.0 to 1.0)."""
    if not s1 or not s2:
        return 0.0
    s1, s2 = s1.lower().strip(), s2.lower().strip()
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    # DP matrix
    matrix = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        matrix[i][0] = i
    for j in range(len2 + 1):
        matrix[0][j] = j
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            matrix[i][j] = min(
                matrix[i-1][j] + 1,
                matrix[i][j-1] + 1,
                matrix[i-1][j-1] + cost
            )
    distance = matrix[len1][len2]
    max_len = max(len1, len2)
    return 1.0 - (distance / max_len) if max_len > 0 else 1.0


def _compute_hash(vendor_id: str, invoice_number: str, amount: float, currency: str) -> str:
    """Compute SHA-256 hash of normalized invoice fields."""
    normalized = f"{str(vendor_id).strip().lower()}|{str(invoice_number).strip().lower()}|{float(amount):.2f}|{str(currency).strip().upper()}"
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


class DuplicateInvoiceDetector:
    """Detects duplicate invoices using exact hash, fuzzy match, and cross-channel methods."""

    def check(self, invoice_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check an invoice for duplicates.

        Args:
            invoice_data: dict with keys: vendor_id, vendor_name, invoice_number,
                          amount, currency, invoice_date, source_channel

        Returns:
            dict with: is_duplicate, detection_method, match_score, matched_invoice,
                       similarity_details, recommendation
        """
        vendor_id = str(invoice_data.get('vendor_id', '')).strip()
        vendor_name = str(invoice_data.get('vendor_name', '')).strip()
        invoice_number = str(invoice_data.get('invoice_number', '')).strip()
        amount = float(invoice_data.get('amount', 0))
        currency = str(invoice_data.get('currency', 'USD')).strip().upper()
        invoice_date = invoice_data.get('invoice_date')
        source_channel = str(invoice_data.get('source_channel', 'unknown')).strip()

        if isinstance(invoice_date, str):
            try:
                invoice_date = datetime.strptime(invoice_date, '%Y-%m-%d').date()
            except ValueError:
                invoice_date = date.today()
        elif isinstance(invoice_date, datetime):
            invoice_date = invoice_date.date()
        elif not isinstance(invoice_date, date):
            invoice_date = date.today()

        result = {
            'is_duplicate': False,
            'detection_method': None,
            'match_score': 0.0,
            'matched_invoice': None,
            'matched_invoice_number': None,
            'similarity_details': {},
            'recommendation': 'proceed',
            'hash': _compute_hash(vendor_id or vendor_name, invoice_number, amount, currency),
        }

        conn = None
        try:
            conn = psycopg2.connect(DB_URL)
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # ── Method 1: Exact hash match ──
            invoice_hash = result['hash']
            cur.execute("""
                SELECT id, invoice_number, hash_sha256, resolution
                FROM invoice_dedup_log
                WHERE hash_sha256 = %s AND resolution != 'false_positive'
                LIMIT 1
            """, (invoice_hash,))
            exact_match = cur.fetchone()

            if exact_match:
                result.update({
                    'is_duplicate': True,
                    'detection_method': 'exact_hash',
                    'match_score': 1.0,
                    'matched_invoice': exact_match['id'],
                    'matched_invoice_number': exact_match['invoice_number'],
                    'similarity_details': {'hash_match': True, 'hash': invoice_hash},
                    'recommendation': 'block',
                })
                self._log_detection(cur, conn, invoice_data, result)
                return result

            # Also check against existing vendor_invoices table
            cur.execute("""
                SELECT id, invoice_number, vendor_name, total_amount, invoice_date
                FROM vendor_invoices
                WHERE invoice_number = %s
                LIMIT 5
            """, (invoice_number,))
            existing_invoices = cur.fetchall()

            for inv in existing_invoices:
                inv_vendor = str(inv.get('vendor_name', '')).strip().lower()
                if inv_vendor == vendor_name.lower() or inv_vendor == vendor_id.lower():
                    result.update({
                        'is_duplicate': True,
                        'detection_method': 'exact_hash',
                        'match_score': 0.98,
                        'matched_invoice': inv['id'],
                        'matched_invoice_number': inv['invoice_number'],
                        'similarity_details': {
                            'invoice_number_match': True,
                            'vendor_match': True,
                        },
                        'recommendation': 'block',
                    })
                    self._log_detection(cur, conn, invoice_data, result)
                    return result

            # ── Method 2: Fuzzy match ──
            date_from = invoice_date - timedelta(days=DATE_WINDOW_DAYS)
            date_to = invoice_date + timedelta(days=DATE_WINDOW_DAYS)
            amount_low = amount * (1 - AMOUNT_TOLERANCE_PCT)
            amount_high = amount * (1 + AMOUNT_TOLERANCE_PCT)

            cur.execute("""
                SELECT id, invoice_number, vendor_name, total_amount, invoice_date, vendor_id
                FROM vendor_invoices
                WHERE total_amount BETWEEN %s AND %s
                  AND invoice_date BETWEEN %s AND %s
                ORDER BY invoice_date DESC
                LIMIT 50
            """, (amount_low, amount_high, date_from, date_to))
            fuzzy_candidates = cur.fetchall()

            for cand in fuzzy_candidates:
                cand_vendor = str(cand.get('vendor_name', '') or cand.get('vendor_id', '')).lower()
                cand_inv_no = str(cand.get('invoice_number', ''))

                # Check vendor match
                vendor_match = (
                    cand_vendor == vendor_name.lower() or
                    cand_vendor == vendor_id.lower() or
                    _levenshtein_ratio(cand_vendor, vendor_name.lower()) > 0.85
                )
                if not vendor_match:
                    continue

                # Check invoice number similarity
                inv_similarity = _levenshtein_ratio(cand_inv_no, invoice_number)

                # Check amount similarity
                cand_amount = float(cand.get('total_amount', 0))
                amount_diff_pct = abs(cand_amount - amount) / max(amount, 0.01)

                if inv_similarity >= LEVENSHTEIN_THRESHOLD:
                    overall_score = (inv_similarity * 0.4 + (1 - amount_diff_pct) * 0.3 + 0.3)  # 0.3 for vendor+date match
                    result.update({
                        'is_duplicate': True,
                        'detection_method': 'fuzzy_match',
                        'match_score': round(overall_score, 3),
                        'matched_invoice': cand['id'],
                        'matched_invoice_number': cand_inv_no,
                        'similarity_details': {
                            'invoice_number_similarity': round(inv_similarity, 3),
                            'amount_diff_pct': round(amount_diff_pct * 100, 2),
                            'vendor_match': True,
                            'date_within_window': True,
                        },
                        'recommendation': 'review' if overall_score < 0.95 else 'block',
                    })
                    self._log_detection(cur, conn, invoice_data, result)
                    return result

            # ── Method 3: Cross-channel detection ──
            if source_channel and source_channel != 'unknown':
                cur.execute("""
                    SELECT id, invoice_number, vendor_name, total_amount, invoice_date
                    FROM vendor_invoices
                    WHERE vendor_name ILIKE %s
                      AND total_amount BETWEEN %s AND %s
                      AND invoice_date BETWEEN %s AND %s
                    LIMIT 20
                """, (f'%{vendor_name}%', amount_low, amount_high, date_from, date_to))
                cross_candidates = cur.fetchall()

                for cand in cross_candidates:
                    cand_inv_no = str(cand.get('invoice_number', ''))
                    if cand_inv_no != invoice_number:
                        # Different invoice number but same vendor + amount + date range
                        result.update({
                            'is_duplicate': True,
                            'detection_method': 'cross_channel',
                            'match_score': 0.75,
                            'matched_invoice': cand['id'],
                            'matched_invoice_number': cand_inv_no,
                            'similarity_details': {
                                'same_vendor': True,
                                'similar_amount': True,
                                'date_within_window': True,
                                'different_invoice_number': True,
                                'possible_resubmission': True,
                            },
                            'recommendation': 'review',
                        })
                        self._log_detection(cur, conn, invoice_data, result)
                        return result

            # No duplicate found — log the hash for future checks
            self._log_clean_invoice(cur, conn, invoice_data, invoice_hash)
            return result

        except Exception as e:
            logger.error("[DuplicateInvoiceDetector] Error: %s", e)
            result['error'] = str(e)
            return result
        finally:
            if conn:
                conn.close()

    def _log_detection(self, cur, conn, invoice_data: dict, result: dict):
        """Log a duplicate detection to invoice_dedup_log."""
        try:
            cur.execute("""
                INSERT INTO invoice_dedup_log (
                    invoice_number, vendor_id, vendor_name, invoice_amount,
                    invoice_date, detection_method, hash_sha256, match_score,
                    matched_invoice_id, matched_invoice_number, similarity_details,
                    resolution, auto_blocked
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)
            """, (
                invoice_data.get('invoice_number'),
                invoice_data.get('vendor_id'),
                invoice_data.get('vendor_name'),
                invoice_data.get('amount'),
                invoice_data.get('invoice_date'),
                result.get('detection_method'),
                result.get('hash'),
                result.get('match_score'),
                result.get('matched_invoice'),
                result.get('matched_invoice_number'),
                json.dumps(result.get('similarity_details', {})),
                result.get('recommendation') == 'block',
            ))
            conn.commit()
        except Exception as e:
            logger.warning("[DuplicateInvoiceDetector] Could not log detection: %s", e)
            try:
                conn.rollback()
            except:
                pass

    def _log_clean_invoice(self, cur, conn, invoice_data: dict, invoice_hash: str):
        """Log a clean invoice hash for future dedup checks."""
        try:
            cur.execute("""
                INSERT INTO invoice_dedup_log (
                    invoice_number, vendor_id, vendor_name, invoice_amount,
                    invoice_date, detection_method, hash_sha256, match_score,
                    resolution, auto_blocked
                ) VALUES (%s, %s, %s, %s, %s, 'exact_hash', %s, 0, 'false_positive', FALSE)
                ON CONFLICT DO NOTHING
            """, (
                invoice_data.get('invoice_number'),
                invoice_data.get('vendor_id'),
                invoice_data.get('vendor_name'),
                invoice_data.get('amount'),
                invoice_data.get('invoice_date'),
                invoice_hash,
            ))
            conn.commit()
        except Exception as e:
            logger.warning("[DuplicateInvoiceDetector] Could not log clean hash: %s", e)
            try:
                conn.rollback()
            except:
                pass


# ── Singleton ──
_detector_instance: Optional[DuplicateInvoiceDetector] = None

def get_duplicate_detector() -> DuplicateInvoiceDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = DuplicateInvoiceDetector()
    return _detector_instance
