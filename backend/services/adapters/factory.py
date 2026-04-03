"""
DataSourceFactory — returns the correct IDataSourceAdapter based on DATA_SOURCE in .env

Usage (anywhere in the codebase):
    from backend.services.adapters.factory import get_adapter
    adapter = get_adapter()
    vendors = adapter.get_vendors()

Switch ERP:
    .env:  DATA_SOURCE=postgresql   →  PostgreSQLAdapter  (demo / build phase)
    .env:  DATA_SOURCE=odoo         →  OdooAdapter        (client using Odoo)
    .env:  DATA_SOURCE=sap          →  SAPAdapter         (client using SAP)
    .env:  DATA_SOURCE=netsuite     →  NetSuiteAdapter    (client using NetSuite)
"""

import os
import logging
from functools import lru_cache
from backend.services.adapters.base_adapter import IDataSourceAdapter

logger = logging.getLogger(__name__)

# Registry of available adapters — add new ERPs here only
_ADAPTER_REGISTRY = {
    # ── Live ERP connectors ──────────────────────────────────────────────────
    "postgresql": "backend.services.adapters.postgresql_adapter.PostgreSQLAdapter",
    "odoo":       "backend.services.adapters.odoo_adapter.OdooAdapter",
    "sap":        "backend.services.adapters.sap_adapter.SAPAdapter",
    "sap_s4":     "backend.services.adapters.sap_adapter.SAPAdapter",
    "sap_b1":     "backend.services.adapters.sap_b1_adapter.SAPB1Adapter",
    "dynamics":   "backend.services.adapters.dynamics_adapter.DynamicsAdapter",
    "oracle":     "backend.services.adapters.oracle_adapter.OracleAdapter",
    "erpnext":    "backend.services.adapters.erpnext_adapter.ERPNextAdapter",
    # ── Demo / build-phase — ERP-format data stored in PostgreSQL ────────────
    # Use DATA_SOURCE=demo_odoo to work with Odoo-format tables in local PG DB
    # (no live Odoo server required). Each ERP adapter auto-detects demo mode
    # when the live ERP URL is not set, and falls back to PG demo tables.
    "demo_odoo":     "backend.services.adapters.odoo_adapter.OdooAdapter",
    "demo_sap_s4":   "backend.services.adapters.sap_adapter.SAPAdapter",
    "demo_sap_b1":   "backend.services.adapters.sap_b1_adapter.SAPB1Adapter",
    "demo_dynamics": "backend.services.adapters.dynamics_adapter.DynamicsAdapter",
    "demo_oracle":   "backend.services.adapters.oracle_adapter.OracleAdapter",
    "demo_erpnext":  "backend.services.adapters.erpnext_adapter.ERPNextAdapter",
    # Alternate names
    "dynamics365":   "backend.services.adapters.dynamics_adapter.DynamicsAdapter",
}

# Default when DATA_SOURCE is not set
_DEFAULT_SOURCE = "postgresql"


@lru_cache(maxsize=1)
def get_adapter() -> IDataSourceAdapter:
    """
    Return the singleton adapter instance for the configured data source.
    Cached after first call — adapter is shared across all agents.
    """
    source = os.environ.get("DATA_SOURCE", _DEFAULT_SOURCE).lower().strip()

    if source not in _ADAPTER_REGISTRY:
        logger.warning(
            "Unknown DATA_SOURCE='%s'. Available: %s. Falling back to postgresql.",
            source, list(_ADAPTER_REGISTRY.keys())
        )
        source = _DEFAULT_SOURCE

    class_path = _ADAPTER_REGISTRY[source]
    module_path, class_name = class_path.rsplit(".", 1)

    import importlib
    module = importlib.import_module(module_path)
    adapter_class = getattr(module, class_name)
    adapter = adapter_class()

    logger.info("DataSourceFactory: activated %s (%s)", class_name, adapter.source_name())
    return adapter


def reset_adapter():
    """
    Clear the cached adapter instance.
    Call this after changing DATA_SOURCE in tests or config reload.
    """
    get_adapter.cache_clear()
    logger.info("DataSourceFactory: adapter cache cleared")


def list_available_sources() -> dict:
    """Return all registered data sources with their class paths."""
    return dict(_ADAPTER_REGISTRY)
