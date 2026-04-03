"""
Vendor Sanctions Service — Sprint 8 Pluggable Adapter
======================================================
Liztek Procure-AI: Replaces the simple blocklist in payment_readiness_agent.py
with a proper pluggable adapter pattern supporting multiple sanctions data sources.

Architecture
------------
ISanctionsService (ABC)
  ├── LocalBlocklistSanctionsService  — fuzzy substring match against local OFAC list (default)
  ├── OpenSanctionsService            — https://api.opensanctions.org (free, optional key)
  └── WorldBankDebarmentService       — World Bank active debarment list (public CSV/API)

Factory
-------
get_sanctions_service() reads SANCTIONS_PROVIDER env var:
  'local'         → LocalBlocklistSanctionsService (default, no API)
  'opensanctions' → OpenSanctionsService (free API, optional OPENSANCTIONS_API_KEY)
  'worldbank'     → WorldBankDebarmentService (public API, no key)

Environment Variables
---------------------
SANCTIONS_PROVIDER=local    (default — simple blocklist)
SANCTIONS_PROVIDER=opensanctions (free API, optional key)
SANCTIONS_PROVIDER=worldbank (World Bank debarment list)
OPENSANCTIONS_API_KEY=      (optional — free tier works without key)
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Result schema ─────────────────────────────────────────────────────────────

def _make_result(
    is_sanctioned: bool,
    risk_level: str,
    matches: List[dict],
    source: str,
) -> dict:
    """Build a standard sanctions check result dict."""
    return {
        "is_sanctioned": is_sanctioned,
        "risk_level":    risk_level,      # 'clear' | 'low' | 'medium' | 'high' | 'blocked'
        "matches":       matches,         # list of matching sanction entries
        "checked_at":    datetime.utcnow(),
        "source":        source,
    }


# ── Abstract Base ─────────────────────────────────────────────────────────────

class ISanctionsService(ABC):
    """
    Abstract base for all vendor sanctions checking providers.

    All implementations return a standardised result dict so that callers
    (payment_readiness_agent) can use the same logic regardless of provider.
    """

    @abstractmethod
    def check_vendor(
        self,
        vendor_name: str,
        vendor_id: Optional[str] = None,
        country: Optional[str] = None,
    ) -> dict:
        """
        Check if a vendor appears on any sanctions or debarment list.

        Parameters
        ----------
        vendor_name : str  — vendor / company name to check
        vendor_id   : str  — internal vendor ID (optional, for audit trail)
        country     : str  — ISO country code, e.g. 'US', 'IR' (optional)

        Returns
        -------
        {
          'is_sanctioned': bool,
          'risk_level':    'clear' | 'low' | 'medium' | 'high' | 'blocked',
          'matches':       [...],       # list of matching sanction entry dicts
          'checked_at':    datetime,
          'source':        str          # provider name
        }
        """

    @abstractmethod
    def bulk_check(self, vendors: List[Dict[str, Any]]) -> List[dict]:
        """
        Check multiple vendors.

        Each vendor dict should have at minimum: vendor_name (required),
        vendor_id (optional), country (optional).

        Returns a list of result dicts in the same order as the input.
        """


# ── Implementation 1: LocalBlocklistSanctionsService (default) ───────────────

class LocalBlocklistSanctionsService(ISanctionsService):
    """
    Simple local blocklist sanctions check.

    Performs case-insensitive substring matching against a curated list of
    known-bad vendor name fragments, including OFAC designees, World Bank
    debarred entities, and common debarment signals.

    Expanded from the original _SANCTIONS_BLOCKLIST in payment_readiness_agent.py.
    Returns risk_level='blocked' on any match, 'clear' otherwise.
    """

    # Comprehensive local blocklist — supplement with real data from sanctions APIs in prod
    _OFAC_BLOCKLIST: List[str] = [
        # Original blocklist entries
        "ofac blocked",
        "sanctioned corp",
        "debarred vendor",
        "blacklisted supplier",
        # Expanded entries
        "north korea",
        "iran trade",
        "cuba exports",
        "restricted entity",
        "terror finance llc",
        "dprk",
        "islamic republic of iran",
        "al qaeda",
        "al-qaeda",
        "hamas",
        "hezbollah",
        "taliban",
        "isis",
        "isil",
        "wagner group",
        "specially designated nationals",
        "sdn list",
        # Common debarment signals
        "debarred",
        "suspended vendor",
        "blacklisted",
        "excluded supplier",
        "do not pay",
        "blocked vendor",
    ]

    def check_vendor(
        self,
        vendor_name: str,
        vendor_id: Optional[str] = None,
        country: Optional[str] = None,
    ) -> dict:
        """
        Check vendor name against local blocklist using case-insensitive
        substring matching.

        Returns blocked if any blocklist entry is found in vendor_name,
        or if vendor_name is found in any blocklist entry.
        """
        name_lower = (vendor_name or "").lower().strip()

        if not name_lower:
            return _make_result(False, "clear", [], "local_blocklist")

        matches = [
            {"entry": entry, "match_type": "substring"}
            for entry in self._OFAC_BLOCKLIST
            if entry in name_lower or name_lower in entry
        ]

        if matches:
            logger.warning(
                "[LocalBlocklistSanctionsService] BLOCKED: vendor '%s' matches %d entry(ies)",
                vendor_name, len(matches),
            )
            return _make_result(True, "blocked", matches, "local_blocklist")

        return _make_result(False, "clear", [], "local_blocklist")

    def bulk_check(self, vendors: List[Dict[str, Any]]) -> List[dict]:
        """Check all vendors against the local blocklist. Result includes vendor_name."""
        results = []
        for v in vendors:
            result = self.check_vendor(
                vendor_name=v.get("vendor_name", ""),
                vendor_id=v.get("vendor_id"),
                country=v.get("country"),
            )
            result["vendor_name"] = v.get("vendor_name", "")
            result["vendor_id"]   = v.get("vendor_id")
            results.append(result)
        return results


# ── Implementation 2: OpenSanctionsService ───────────────────────────────────

class OpenSanctionsService(ISanctionsService):
    """
    Real-time sanctions screening via OpenSanctions API (https://www.opensanctions.org).

    Free tier available without API key (rate-limited). Paid plans allow
    higher throughput. Set OPENSANCTIONS_API_KEY for authenticated access.

    Uses the /match/default endpoint for fuzzy entity matching against
    the consolidated global sanctions and debarment dataset.

    Features:
    - 24-hour per-vendor result caching
    - 60 req/min rate limiting (1s delay between calls when no API key)
    - Score-based risk classification (score > 0.9 → blocked, > 0.7 → high, > 0.5 → medium)
    - Falls back to local blocklist on API failure

    Env vars:
      OPENSANCTIONS_API_KEY — optional API key (free tier works without it)
    """

    _MATCH_ENDPOINT = "https://api.opensanctions.org/match/default"
    _SCORE_BLOCKED  = 0.9
    _SCORE_HIGH     = 0.7
    _SCORE_MEDIUM   = 0.5
    _CACHE_TTL_S    = 86400  # 24 hours

    def __init__(self) -> None:
        self._api_key = os.environ.get("OPENSANCTIONS_API_KEY", "").strip()
        self._fallback = LocalBlocklistSanctionsService()
        # {vendor_name_lower: (result_dict, cached_at_timestamp)}
        self._cache: Dict[str, tuple] = {}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"ApiKey {self._api_key}"
        return headers

    def _is_cache_valid(self, vendor_key: str) -> bool:
        if vendor_key not in self._cache:
            return False
        _, cached_at = self._cache[vendor_key]
        return (time.time() - cached_at) < self._CACHE_TTL_S

    def _classify_score(self, score: float) -> str:
        """Map a match score to a risk level string."""
        if score >= self._SCORE_BLOCKED:
            return "blocked"
        if score >= self._SCORE_HIGH:
            return "high"
        if score >= self._SCORE_MEDIUM:
            return "medium"
        if score > 0:
            return "low"
        return "clear"

    def _query_api(self, vendor_name: str) -> Optional[dict]:
        """
        POST to OpenSanctions /match/default endpoint.
        Returns the parsed JSON response or None on failure.
        """
        import requests

        payload = {
            "queries": {
                "q1": {
                    "schema": "Organization",
                    "properties": {"name": [vendor_name]},
                }
            }
        }

        try:
            # Rate limiting: add brief delay for free tier (no API key)
            if not self._api_key:
                time.sleep(1)

            response = requests.post(
                self._MATCH_ENDPOINT,
                json=payload,
                headers=self._headers(),
                timeout=30,
            )

            if response.status_code == 200:
                return response.json()

            logger.warning(
                "[OpenSanctionsService] API returned %s: %s",
                response.status_code,
                response.text[:200],
            )
            return None

        except Exception as exc:
            logger.warning("[OpenSanctionsService] API call failed: %s", exc)
            return None

    def _parse_response(self, api_response: dict, vendor_name: str) -> dict:
        """
        Parse OpenSanctions API response into a standardised result.

        Response structure:
          {"responses": {"q1": {"results": [{"id": ..., "score": 0.95, "caption": ...}]}}}
        """
        responses = api_response.get("responses", {})
        q1 = responses.get("q1", {})
        results = q1.get("results", [])

        if not results:
            return _make_result(False, "clear", [], "opensanctions")

        # Find highest-scoring result
        best_score = max((r.get("score", 0) for r in results), default=0)
        risk_level = self._classify_score(best_score)
        is_sanctioned = risk_level in ("blocked", "high")

        matches = [
            {
                "id":       r.get("id"),
                "caption":  r.get("caption"),
                "score":    r.get("score"),
                "datasets": r.get("datasets", []),
                "schema":   r.get("schema"),
            }
            for r in results
            if r.get("score", 0) >= self._SCORE_MEDIUM
        ]

        if is_sanctioned:
            logger.warning(
                "[OpenSanctionsService] MATCH: vendor '%s' risk=%s score=%.2f",
                vendor_name, risk_level, best_score,
            )

        return _make_result(is_sanctioned, risk_level, matches, "opensanctions")

    # ── Public interface ──────────────────────────────────────────────────────

    def check_vendor(
        self,
        vendor_name: str,
        vendor_id: Optional[str] = None,
        country: Optional[str] = None,
    ) -> dict:
        """Check vendor via OpenSanctions API with 24-hour caching."""
        name_clean = (vendor_name or "").strip()
        if not name_clean:
            return _make_result(False, "clear", [], "opensanctions")

        cache_key = name_clean.lower()

        # Return cached result if fresh
        if self._is_cache_valid(cache_key):
            cached_result, _ = self._cache[cache_key]
            logger.debug(
                "[OpenSanctionsService] Cache hit for '%s'", vendor_name
            )
            return cached_result

        # Query API
        api_response = self._query_api(name_clean)

        if api_response is None:
            # API failed — fall back to local blocklist
            logger.warning(
                "[OpenSanctionsService] API unavailable; using local blocklist for '%s'",
                vendor_name,
            )
            result = self._fallback.check_vendor(vendor_name, vendor_id, country)
            result["source"] = "opensanctions_fallback_local"
            return result

        result = self._parse_response(api_response, name_clean)

        # Cache the result
        self._cache[cache_key] = (result, time.time())

        return result

    def bulk_check(self, vendors: List[Dict[str, Any]]) -> List[dict]:
        """Check multiple vendors via OpenSanctions with per-vendor caching."""
        return [
            self.check_vendor(
                vendor_name=v.get("vendor_name", ""),
                vendor_id=v.get("vendor_id"),
                country=v.get("country"),
            )
            for v in vendors
        ]


# ── Implementation 3: WorldBankDebarmentService ───────────────────────────────

class WorldBankDebarmentService(ISanctionsService):
    """
    Checks vendors against the World Bank Group Listing of Ineligible Firms
    and Individuals (actively debarred entities).

    Uses the World Bank public debarment API — no API key required.
    Results are cached for 24 hours to avoid repeated API calls.

    API endpoint:
      GET https://apigwext.worldbank.org/dvsvc/v1.0/json/APPLICATION/
          ADOBE_EXPRNC_MGR_ROLE/FIRM?SANCTION_STATUS=Active

    Falls back to LocalBlocklistSanctionsService on API failure.
    """

    _WB_API_URL = (
        "https://apigwext.worldbank.org/dvsvc/v1.0/json/APPLICATION/"
        "ADOBE_EXPRNC_MGR_ROLE/FIRM?SANCTION_STATUS=Active"
    )
    _CACHE_TTL_S = 86400  # 24 hours

    def __init__(self) -> None:
        self._fallback = LocalBlocklistSanctionsService()
        self._debarment_list: Optional[List[dict]] = None
        self._cache_time: Optional[float] = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _is_list_fresh(self) -> bool:
        if self._debarment_list is None or self._cache_time is None:
            return False
        return (time.time() - self._cache_time) < self._CACHE_TTL_S

    def _fetch_debarment_list(self) -> List[dict]:
        """
        Fetch the World Bank active debarment list.
        Returns list of firm dicts, or [] on failure.
        """
        import requests

        try:
            response = requests.get(self._WB_API_URL, timeout=30)
            if response.status_code == 200:
                data = response.json()
                # API returns: {"COLLATERAL_SANCTION_LIST": {"SANCTION_LIST": [...]}}
                # or a flat list depending on the response format
                firms: List[dict] = (
                    data.get("COLLATERAL_SANCTION_LIST", {}).get("SANCTION_LIST", [])
                    or data.get("SANCTION_LIST", [])
                    or (data if isinstance(data, list) else [])
                )
                self._debarment_list = firms
                self._cache_time = time.time()
                logger.info(
                    "[WorldBankDebarmentService] Loaded %d debarment entries",
                    len(firms),
                )
                return firms

            logger.warning(
                "[WorldBankDebarmentService] API returned %s",
                response.status_code,
            )
            return []

        except Exception as exc:
            logger.warning(
                "[WorldBankDebarmentService] Failed to fetch debarment list: %s", exc
            )
            return []

    def _get_list(self) -> List[dict]:
        """Return cached debarment list, refreshing if stale."""
        if not self._is_list_fresh():
            self._fetch_debarment_list()
        return self._debarment_list or []

    def _match_name(self, vendor_name: str, debarment_list: List[dict]) -> List[dict]:
        """
        Case-insensitive substring match of vendor_name against firm names
        in the World Bank debarment list.

        Checks the following fields in each entry:
          FIRM_NAME, ADDRESS (for additional context)
        """
        name_lower = vendor_name.lower().strip()
        matches = []

        for entry in debarment_list:
            firm_name = (
                entry.get("FIRM_NAME") or entry.get("name") or ""
            ).lower().strip()

            if not firm_name:
                continue

            # Bidirectional substring check
            if name_lower in firm_name or firm_name in name_lower:
                matches.append({
                    "firm_name":   entry.get("FIRM_NAME") or entry.get("name"),
                    "country":     entry.get("COUNTRY_CODE") or entry.get("country"),
                    "sanction_type": entry.get("SANCTION_TYPE") or "debarred",
                    "from_date":   entry.get("SANCTION_FROM") or entry.get("from_date"),
                    "to_date":     entry.get("SANCTION_TO") or entry.get("to_date"),
                    "grounds":     entry.get("GROUNDS") or entry.get("grounds"),
                    "source":      "world_bank",
                })

        return matches

    # ── Public interface ──────────────────────────────────────────────────────

    def check_vendor(
        self,
        vendor_name: str,
        vendor_id: Optional[str] = None,
        country: Optional[str] = None,
    ) -> dict:
        """Check vendor against World Bank active debarment list."""
        name_clean = (vendor_name or "").strip()
        if not name_clean:
            return _make_result(False, "clear", [], "worldbank_debarment")

        debarment_list = self._get_list()

        if not debarment_list:
            # List unavailable — fall back to local blocklist
            logger.warning(
                "[WorldBankDebarmentService] List unavailable; using local blocklist for '%s'",
                vendor_name,
            )
            result = self._fallback.check_vendor(vendor_name, vendor_id, country)
            result["source"] = "worldbank_fallback_local"
            return result

        matches = self._match_name(name_clean, debarment_list)

        if matches:
            logger.warning(
                "[WorldBankDebarmentService] DEBARRED: vendor '%s' found in WB list (%d match(es))",
                vendor_name, len(matches),
            )
            return _make_result(True, "blocked", matches, "worldbank_debarment")

        return _make_result(False, "clear", [], "worldbank_debarment")

    def bulk_check(self, vendors: List[Dict[str, Any]]) -> List[dict]:
        """
        Check multiple vendors against World Bank list.
        Loads the list once and reuses it for all checks.
        """
        # Pre-load list once
        _ = self._get_list()

        return [
            self.check_vendor(
                vendor_name=v.get("vendor_name", ""),
                vendor_id=v.get("vendor_id"),
                country=v.get("country"),
            )
            for v in vendors
        ]


# ── Factory function ──────────────────────────────────────────────────────────

def get_sanctions_service() -> ISanctionsService:
    """
    Return the configured vendor sanctions service implementation.

    Reads the SANCTIONS_PROVIDER environment variable:
      'local'         → LocalBlocklistSanctionsService (default, no API key)
      'opensanctions' → OpenSanctionsService (free API, optional OPENSANCTIONS_API_KEY)
      'worldbank'     → WorldBankDebarmentService (public API, no key)

    Falls back to LocalBlocklistSanctionsService if the provider name is
    unrecognised.

    Environment Variables
    ---------------------
    SANCTIONS_PROVIDER      : provider selection (default: 'local')
    OPENSANCTIONS_API_KEY   : optional key for OpenSanctions (free tier works without it)
    """
    provider = os.environ.get("SANCTIONS_PROVIDER", "local").strip().lower()

    if provider == "opensanctions":
        logger.info("[get_sanctions_service] Using OpenSanctionsService")
        return OpenSanctionsService()

    if provider == "worldbank":
        logger.info("[get_sanctions_service] Using WorldBankDebarmentService")
        return WorldBankDebarmentService()

    if provider != "local":
        logger.warning(
            "[get_sanctions_service] Unknown SANCTIONS_PROVIDER '%s'; falling back to local.",
            provider,
        )

    logger.info("[get_sanctions_service] Using LocalBlocklistSanctionsService (default)")
    return LocalBlocklistSanctionsService()
