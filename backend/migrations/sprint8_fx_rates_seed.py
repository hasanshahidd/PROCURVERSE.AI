"""
Sprint 8 Migration: FX Rates Table Seed
========================================
Liztek Procure-AI — Sprint 8

Creates the exchange_rates table if it does not exist, then upserts
the standard AED-based rates so that DatabaseFXService has data to work with.

Run this migration once after deploying Sprint 8 code:
  python -m backend.migrations.sprint8_fx_rates_seed

What it does
------------
1. Creates the exchange_rates table (if not exists) with a standard schema
2. Adds missing columns to an existing exchange_rates table (safe ALTER)
3. Upserts all standard AED-based rates (matching StaticFXService._STATIC_RATES)
4. Prints a summary of what was seeded / already present

Table schema created
---------------------
  id              SERIAL PRIMARY KEY
  currency_code   VARCHAR(10) NOT NULL UNIQUE
  rate_to_aed     NUMERIC(20,6) NOT NULL    -- 1 unit of currency = N AED
  rate_to_usd     NUMERIC(20,6)             -- 1 unit of currency = N USD (optional)
  source          VARCHAR(50) DEFAULT 'static_seed'
  effective_date  DATE DEFAULT CURRENT_DATE
  created_at      TIMESTAMP DEFAULT NOW()
  updated_at      TIMESTAMP DEFAULT NOW()

Dependencies
------------
- psycopg2 (already in requirements.txt)
- DATABASE_URL env var (set in .env)
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# ── AED-based exchange rates (mirrors StaticFXService._STATIC_RATES) ─────────
# Key: ISO currency code
# Value: (rate_to_aed, rate_to_usd)
#   rate_to_aed: 1 unit of key currency = N AED
#   rate_to_usd: 1 unit of key currency = N USD (AED/USD peg: 1 USD = 3.6725 AED)

_SEED_RATES: Dict[str, Tuple[float, float]] = {
    "AED": (1.0,       0.272),    # base currency
    "USD": (3.6725,    1.0),      # USD/AED peg (very stable)
    "EUR": (4.02,      1.0952),
    "GBP": (4.68,      1.2748),
    "SAR": (0.9792,    0.2667),   # SAR/AED near-peg
    "INR": (0.04408,   0.01201),
    "JPY": (0.0248,    0.00676),
    "CNY": (0.5078,    0.1383),
    "CAD": (2.70,      0.7355),
    "AUD": (2.37,      0.6453),
    "CHF": (4.13,      1.1247),
    "SGD": (2.72,      0.7409),
    "QAR": (1.0082,    0.2746),   # QAR/AED near-peg
    "KWD": (11.92,     3.2468),
    "BHD": (9.75,      2.6553),
    "OMR": (9.54,      2.5983),
    "EGP": (0.0755,    0.02056),
    "PKR": (0.0132,    0.003595),
    "MYR": (0.843,     0.2296),
    "TRY": (0.108,     0.02942),
    "ZAR": (0.197,     0.05366),
    "BRL": (0.706,     0.19226),
    "MXN": (0.181,     0.04931),
    "NOK": (0.343,     0.09341),
    "SEK": (0.348,     0.09477),
    "DKK": (0.539,     0.14679),
    "PLN": (0.927,     0.25243),
    "CZK": (0.167,     0.04548),
    "HUF": (0.01012,   0.002756),
    "RUB": (0.0404,    0.011),    # approximate, subject to sanctions
    "NZD": (2.22,      0.6046),
    "HKD": (0.470,     0.12799),
    "KRW": (0.00270,   0.000735),
    "THB": (0.1022,    0.02784),
    "IDR": (0.000228,  0.0000621),
    "PHP": (0.0641,    0.01746),
    "VND": (0.000146,  0.0000397),
    "BDT": (0.0333,    0.009071),
    "NPR": (0.02753,   0.007498),
    "LKR": (0.01239,   0.003375),
    "JOD": (5.18,      1.4110),   # JOD/AED stable
    "BHD": (9.75,      2.6553),
    "KWD": (11.92,     3.2468),
}

# Effective date for this seed
_SEED_DATE = date(2025, 4, 1)


# ── DDL ───────────────────────────────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS exchange_rates (
    id              SERIAL PRIMARY KEY,
    currency_code   VARCHAR(10) NOT NULL,
    rate_to_aed     NUMERIC(20, 6) NOT NULL DEFAULT 1.0,
    rate_to_usd     NUMERIC(20, 6),
    source          VARCHAR(50) DEFAULT 'static_seed',
    effective_date  DATE DEFAULT CURRENT_DATE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT exchange_rates_currency_code_key UNIQUE (currency_code)
);
"""

_ADD_COLUMN_SQLS = [
    "ALTER TABLE exchange_rates ADD COLUMN IF NOT EXISTS rate_to_usd NUMERIC(20, 6);",
    "ALTER TABLE exchange_rates ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'static_seed';",
    "ALTER TABLE exchange_rates ADD COLUMN IF NOT EXISTS effective_date DATE DEFAULT CURRENT_DATE;",
    "ALTER TABLE exchange_rates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();",
]

_UPSERT_SQL = """
INSERT INTO exchange_rates
    (currency_code, rate_to_aed, rate_to_usd, source, effective_date, updated_at)
VALUES
    (%(currency_code)s, %(rate_to_aed)s, %(rate_to_usd)s,
     %(source)s, %(effective_date)s, NOW())
ON CONFLICT (currency_code) DO UPDATE SET
    rate_to_aed    = EXCLUDED.rate_to_aed,
    rate_to_usd    = EXCLUDED.rate_to_usd,
    source         = EXCLUDED.source,
    effective_date = EXCLUDED.effective_date,
    updated_at     = NOW();
"""


# ── Migration runner ──────────────────────────────────────────────────────────

def run_migration(verbose: bool = True) -> Dict[str, int]:
    """
    Execute the Sprint 8 FX rates migration.

    Steps:
      1. Create exchange_rates table if it doesn't exist
      2. Add missing columns (safe ALTER IF NOT EXISTS)
      3. Upsert all seed rates
      4. Return summary: {created_table, columns_added, rates_seeded}

    Parameters
    ----------
    verbose : bool — if True, print progress to stdout

    Returns
    -------
    dict with keys: created_table (0/1), columns_added (N), rates_seeded (N)
    """
    import psycopg2

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise EnvironmentError(
            "DATABASE_URL environment variable is not set. "
            "Check your .env file."
        )

    summary = {"created_table": 0, "columns_added": 0, "rates_seeded": 0}

    conn = None
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = False

        with conn.cursor() as cur:

            # ── Step 1: Create table ───────────────────────────────────────────
            _log(verbose, "Checking / creating exchange_rates table...")
            cur.execute(_CREATE_TABLE_SQL)

            # Check if we just created it by counting rows before seeding
            cur.execute("SELECT COUNT(*) FROM exchange_rates;")
            row_count_before = cur.fetchone()[0]
            if row_count_before == 0:
                summary["created_table"] = 1
                _log(verbose, "  [+] Table created (was empty)")
            else:
                _log(verbose, f"  [=] Table exists ({row_count_before} rows)")

            # ── Step 2: Add missing columns ───────────────────────────────────
            _log(verbose, "Adding missing columns (safe ALTER IF NOT EXISTS)...")
            for alter_sql in _ADD_COLUMN_SQLS:
                try:
                    cur.execute(alter_sql)
                    summary["columns_added"] += 1
                except Exception as e:
                    # Column may already exist — psycopg2 raises ProgrammingError
                    # IF NOT EXISTS makes this safe, but log anyway
                    logger.debug("ALTER skipped: %s", e)
                    conn.rollback()
                    # Re-open transaction after rollback
                    with conn.cursor() as cur2:
                        cur2.execute("SELECT 1")  # noop to reopen

            # ── Step 3: Upsert rates ──────────────────────────────────────────
            _log(verbose, f"Upserting {len(_SEED_RATES)} exchange rates...")

            # Re-acquire cursor after potential rollbacks above
            with conn.cursor() as upsert_cur:
                for currency_code, (rate_to_aed, rate_to_usd) in _SEED_RATES.items():
                    upsert_cur.execute(_UPSERT_SQL, {
                        "currency_code":  currency_code,
                        "rate_to_aed":    rate_to_aed,
                        "rate_to_usd":    rate_to_usd,
                        "source":         "sprint8_static_seed",
                        "effective_date": _SEED_DATE,
                    })
                    summary["rates_seeded"] += 1

                conn.commit()

            # ── Verification ──────────────────────────────────────────────────
            with conn.cursor() as ver_cur:
                ver_cur.execute("SELECT COUNT(*) FROM exchange_rates;")
                final_count = ver_cur.fetchone()[0]
                _log(verbose, f"  [] exchange_rates table now has {final_count} rows")

    except Exception as exc:
        logger.error("[sprint8_fx_rates_seed] Migration failed: %s", exc)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return summary


def _log(verbose: bool, msg: str) -> None:
    """Print if verbose, always log. Strips non-ASCII for Windows console safety."""
    logger.info(msg)
    if verbose:
        # Replace unicode symbols with ASCII equivalents for Windows cp1252 consoles
        safe_msg = msg.replace('\u2713', 'OK').replace('\u2714', 'OK').replace(
            '\u2717', 'FAIL').replace('\u2718', 'FAIL').replace('\u2192', '->')
        try:
            print(safe_msg)
        except UnicodeEncodeError:
            print(safe_msg.encode('ascii', errors='replace').decode('ascii'))


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    # Load .env if python-dotenv is available
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(
            os.path.dirname(__file__), "..", "..", ".env"
        )
        if os.path.isfile(env_path):
            load_dotenv(env_path)
            print(f"[sprint8_fx_rates_seed] Loaded .env from {env_path}")
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Sprint 8 FX Rates Migration — seed exchange_rates table",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress stdout output (logs still written)"
    )
    args = parser.parse_args()

    print("\n=== Sprint 8: FX Rates Migration ===\n")
    try:
        result = run_migration(verbose=not args.quiet)
        print(f"\nMigration complete: {result}")
        sys.exit(0)
    except Exception as e:
        print(f"\nMigration FAILED: {e}", file=sys.stderr)
        sys.exit(1)
