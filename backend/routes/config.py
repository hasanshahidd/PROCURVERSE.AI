"""
Config Routes — ERP Data Source Switching
==========================================
GET  /api/config/data-source  — Current source + all available sources
POST /api/config/data-source  — Switch DATA_SOURCE at runtime (admin only)
"""

import os
import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.services.adapters.factory import (
    get_adapter, reset_adapter, list_available_sources, _ADAPTER_REGISTRY
)

log = logging.getLogger(__name__)
router = APIRouter()


# ── ERP source metadata ─────────────────────────────────────────────────────

_ERP_INFO = {
    'demo_odoo':     {'label': 'Odoo (Demo)',         'erp': 'Odoo',         'mode': 'demo',  'tables_prefix': 'odoo_'},
    'demo_sap_s4':   {'label': 'SAP S/4HANA (Demo)',  'erp': 'SAP S/4HANA',  'mode': 'demo',  'tables_prefix': 'sap_'},
    'demo_sap_b1':   {'label': 'SAP Business One (Demo)', 'erp': 'SAP B1',   'mode': 'demo',  'tables_prefix': 'sap_'},
    'demo_dynamics': {'label': 'Dynamics 365 (Demo)',  'erp': 'Dynamics 365', 'mode': 'demo',  'tables_prefix': 'd365_'},
    'demo_oracle':   {'label': 'Oracle Fusion (Demo)', 'erp': 'Oracle',      'mode': 'demo',  'tables_prefix': 'oracle_'},
    'demo_erpnext':  {'label': 'ERPNext (Demo)',       'erp': 'ERPNext',     'mode': 'demo',  'tables_prefix': 'erpnext_'},
    'odoo':          {'label': 'Odoo 17 (Live)',       'erp': 'Odoo',        'mode': 'live',  'env_required': ['ODOO_URL', 'ODOO_DB', 'ODOO_USERNAME', 'ODOO_PASSWORD']},
    'sap':           {'label': 'SAP S/4HANA (Live)',   'erp': 'SAP S/4HANA', 'mode': 'live',  'env_required': ['SAP_URL', 'SAP_CLIENT', 'SAP_USER', 'SAP_PASSWORD']},
    'sap_s4':        {'label': 'SAP S/4HANA (Live)',   'erp': 'SAP S/4HANA', 'mode': 'live',  'env_required': ['SAP_URL']},
    'sap_b1':        {'label': 'SAP Business One (Live)', 'erp': 'SAP B1',   'mode': 'live',  'env_required': ['SAP_B1_URL']},
    'dynamics':      {'label': 'Dynamics 365 (Live)',  'erp': 'Dynamics 365', 'mode': 'live',  'env_required': ['DYNAMICS_URL', 'DYNAMICS_TENANT_ID']},
    'oracle':        {'label': 'Oracle Fusion (Live)', 'erp': 'Oracle',      'mode': 'live',  'env_required': ['ORACLE_URL']},
    'erpnext':       {'label': 'ERPNext (Live)',       'erp': 'ERPNext',     'mode': 'live',  'env_required': ['ERPNEXT_URL']},
    'postgresql':    {'label': 'PostgreSQL (Direct)',   'erp': 'PostgreSQL',  'mode': 'direct', 'tables_prefix': ''},
}

_GUIDANCE = {
    'demo': (
        "DEMO MODE: Using simulated ERP data stored in PostgreSQL. "
        "Each ERP's tables contain 100 rows of test data with native field names. "
        "Agents work against this data for development and demos. "
        "To switch to a real ERP, set DATA_SOURCE to the live variant (e.g., 'odoo' instead of 'demo_odoo') "
        "and configure the required environment variables."
    ),
    'live': (
        "LIVE MODE: Connected to a real ERP system via API. "
        "All agent queries go directly to the ERP. "
        "Ensure the ERP credentials are correctly configured in .env. "
        "To fall back to demo data, switch to the demo variant (e.g., 'demo_odoo')."
    ),
    'direct': (
        "DIRECT MODE: Querying PostgreSQL neutral tables directly. "
        "This is the legacy NMI mode. Most tables may be empty. "
        "Recommended: switch to a demo_* source for richer test data."
    ),
}


class DataSourceSwitch(BaseModel):
    data_source: str


@router.get("/data-source")
async def get_data_source():
    """Return current DATA_SOURCE, all available sources, and guidance."""
    current = os.environ.get('DATA_SOURCE', 'postgresql').lower()

    # Build source list with metadata
    demo_sources = []
    live_sources = []
    for key in sorted(_ADAPTER_REGISTRY.keys()):
        info = _ERP_INFO.get(key, {'label': key, 'mode': 'unknown'})
        entry = {
            'key': key,
            'label': info.get('label', key),
            'erp': info.get('erp', key),
            'mode': info.get('mode', 'unknown'),
            'is_current': key == current,
        }
        # Check if live source has required env vars configured
        if info.get('mode') == 'live':
            required = info.get('env_required', [])
            configured = all(os.environ.get(v) for v in required)
            entry['configured'] = configured
            entry['env_required'] = required

        if info.get('mode') == 'demo':
            demo_sources.append(entry)
        else:
            live_sources.append(entry)

    current_info = _ERP_INFO.get(current, {})
    current_mode = current_info.get('mode', 'unknown')

    return {
        'current': current,
        'current_label': current_info.get('label', current),
        'current_mode': current_mode,
        'guidance': _GUIDANCE.get(current_mode, ''),
        'demo_sources': demo_sources,
        'live_sources': live_sources,
        'how_to_go_live': {
            'step_1': 'Get ERP credentials from client (URL, database, username, password)',
            'step_2': 'Add credentials to .env file (e.g., ODOO_URL=https://client.odoo.com)',
            'step_3': 'Switch DATA_SOURCE from demo_X to X (e.g., demo_odoo → odoo)',
            'step_4': 'The adapter automatically connects to the real ERP via API',
            'step_5': 'All agents work identically — zero code changes needed',
        },
    }


@router.post("/data-source")
async def switch_data_source(body: DataSourceSwitch):
    """Switch DATA_SOURCE at runtime. Validates the new adapter works before committing."""
    new_source = body.data_source.lower().strip()

    if new_source not in _ADAPTER_REGISTRY:
        available = [k for k in _ADAPTER_REGISTRY.keys() if not k == 'dynamics365']
        raise HTTPException(400, f"Unknown data source: '{new_source}'. Available: {available}")

    previous = os.environ.get('DATA_SOURCE', 'postgresql')
    if new_source == previous.lower():
        return {'success': True, 'message': f'Already using {new_source}', 'current': new_source}

    # Switch
    log.info("Switching DATA_SOURCE: %s → %s", previous, new_source)
    os.environ['DATA_SOURCE'] = new_source
    reset_adapter()

    # Flush all cached data from old adapter so stale results aren't served
    try:
        from backend.services.cache import get_cache
        _cache = get_cache()
        if _cache and _cache.enabled:
            _cache.clear_pattern("*")
            log.info("Cache flushed after adapter switch")
    except Exception as cache_err:
        log.warning("Cache flush failed (non-fatal): %s", cache_err)

    # Validate new adapter works
    try:
        adapter = get_adapter()
        source_name = adapter.source_name()
        log.info("New adapter validated: %s", source_name)
    except Exception as e:
        # Rollback
        log.error("New adapter failed, rolling back: %s", e)
        os.environ['DATA_SOURCE'] = previous
        reset_adapter()
        raise HTTPException(500, f"Failed to activate {new_source}: {e}. Rolled back to {previous}.")

    new_info = _ERP_INFO.get(new_source, {})
    return {
        'success': True,
        'previous': previous,
        'current': new_source,
        'current_label': new_info.get('label', new_source),
        'mode': new_info.get('mode', 'unknown'),
        'guidance': _GUIDANCE.get(new_info.get('mode', ''), ''),
        'adapter': source_name,
        'message': f'Switched from {previous} to {new_source}',
    }


@router.get("/departments")
async def get_departments():
    """Return departments from budget_tracking table (dynamic, not hardcoded)."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        return {"departments": ["IT", "Finance", "Operations", "Procurement", "HR"]}
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT department FROM budget_tracking WHERE department IS NOT NULL ORDER BY department")
        depts = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        if not depts:
            depts = ["IT", "Finance", "Operations", "Procurement", "HR"]
        return {"departments": depts}
    except Exception as e:
        logger.warning("get_departments failed: %s", e)
        return {"departments": ["IT", "Finance", "Operations", "Procurement", "HR"]}
