"""
Sprint 7 UAT Fixes Migration
============================
Fixes:
  UAT-002a — Populate approval_rules.approver_email from users table by role
  UAT-002b — Add PAYMENT document_type approval rules (separate from PR/INVOICE)
  UAT-003a — Ensure pr_approval_workflows has request_data column (persistent DDL,
              removes the inline ALTER TABLE from approval_routing.py)
"""

import logging
import sys
import os

# Allow running as a module from project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from backend.services.nmi_data_service import get_conn

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def run():
    conn = get_conn()
    try:
        with conn.cursor() as cur:

            # ── UAT-003a: Add request_data column to pr_approval_workflows ────
            logger.info("UAT-003a: Ensuring pr_approval_workflows.request_data exists …")
            cur.execute("""
                ALTER TABLE pr_approval_workflows
                ADD COLUMN IF NOT EXISTS request_data JSONB DEFAULT '{}'::jsonb
            """)

            # ── UAT-002a: Copy approver email from users by role ──────────────
            logger.info("UAT-002a: Updating approval_rules.approver_email from users …")
            cur.execute("""
                UPDATE approval_rules ar
                SET approver_email = u.email
                FROM users u
                WHERE LOWER(ar.approver_role) = LOWER(u.role)
                  AND (ar.approver_email IS NULL OR ar.approver_email = '')
            """)
            updated = cur.rowcount
            logger.info("  → %d approval_rules rows updated with email", updated)

            # ── UAT-002b: Add PAYMENT approval rules ──────────────────────────
            # Check if already seeded
            cur.execute("SELECT COUNT(*) FROM approval_rules WHERE document_type='PAYMENT'")
            existing = cur.fetchone()[0]

            if existing == 0:
                logger.info("UAT-002b: Seeding PAYMENT approval rules …")
                cur.execute("""
                    INSERT INTO approval_rules
                      (document_type, amount_min, amount_max, approval_level,
                       approver_name, approver_role, approver_email,
                       sla_hours, escalate_after, status)
                    VALUES
                      -- Level 1: Finance Manager approves payments up to 50k
                      ('PAYMENT', 0,      50000,   1, 'Finance Manager',
                       'finance',  NULL, 24, 48, 'active'),
                      -- Level 2: Finance Director approves 50k–250k
                      ('PAYMENT', 50000,  250000,  2, 'Finance Director',
                       'finance',  NULL, 24, 48, 'active'),
                      -- Level 3: CFO / Treasury approves >250k
                      ('PAYMENT', 250000, 99999999, 3, 'CFO / Treasury',
                       'admin',    NULL, 48, 96, 'active')
                """)
                logger.info("  → 3 PAYMENT approval rules inserted")

                # Fill emails for newly inserted PAYMENT rules
                cur.execute("""
                    UPDATE approval_rules ar
                    SET approver_email = u.email
                    FROM users u
                    WHERE ar.document_type = 'PAYMENT'
                      AND LOWER(ar.approver_role) = LOWER(u.role)
                      AND (ar.approver_email IS NULL OR ar.approver_email = '')
                """)
                logger.info("  → PAYMENT rules emails filled: %d rows", cur.rowcount)
            else:
                logger.info("UAT-002b: PAYMENT rules already exist (%d rows) — skipping.", existing)

        conn.commit()
        logger.info("Sprint 7 UAT fixes migration completed successfully.")

    except Exception as e:
        conn.rollback()
        logger.error("Migration failed: %s", e)
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
