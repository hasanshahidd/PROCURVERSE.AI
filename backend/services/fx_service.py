"""
FX Rates Service — Sprint 8 Pluggable Adapter
==============================================
Liztek Procure-AI: Replaces hardcoded / missing FX logic in
payment_calculation_agent.py with a proper pluggable adapter pattern.

Architecture
------------
IFXService (ABC)
  ├── StaticFXService           — hardcoded AED-based rates (default, no API)
  ├── OpenExchangeRatesService  — OpenExchangeRates API (OPENEXCHANGERATES_APP_ID)
  └── DatabaseFXService         — reads from exchange_rates table via adapter

Factory
-------
get_fx_service() reads FX_PROVIDER env var:
  'static'            → StaticFXService (default)
  'database'          → DatabaseFXService
  'openexchangerates' → OpenExchangeRatesService

Environment Variables
---------------------
FX_PROVIDER=static             (default — hardcoded AED rates)
FX_PROVIDER=database           (reads exchange_rates table)
FX_PROVIDER=openexchangerates  (requires OPENEXCHANGERATES_APP_ID)
OPENEXCHANGERATES_APP_ID=      (OpenExchangeRates app ID)
FX_BASE_CURRENCY=AED           (base currency for all conversions, default: AED)
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default base currency for the Liztek UAE-based deployment
_DEFAULT_BASE_CURRENCY = "AED"


# ── Abstract Base ─────────────────────────────────────────────────────────────

class IFXService(ABC):
    """
    Abstract base for all foreign exchange rate providers.

    All rates are expressed relative to a base currency (default: AED).
    A rate of 3.6725 for USD means: 1 USD = 3.6725 AED.
    """

    @property
    def base_currency(self) -> str:
        """The base currency all rates are quoted in."""
        return os.environ.get("FX_BASE_CURRENCY", _DEFAULT_BASE_CURRENCY).upper()

    @abstractmethod
    def get_rate(self, from_currency: str, to_currency: str) -> float:
        """
        Return exchange rate: 1 from_currency = N to_currency.

        Example: get_rate('USD', 'AED') → 3.6725
        Example: get_rate('AED', 'USD') → 0.2723
        """

    @abstractmethod
    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """
        Convert amount from one currency to another.

        Example: convert(100, 'USD', 'AED') → 367.25
        """

    @abstractmethod
    def get_all_rates(self, base_currency: str = "AED") -> Dict[str, float]:
        """
        Return all known exchange rates relative to base_currency.

        Returns dict: {currency_code: rate_in_base_units}
        Example (base=AED): {'USD': 3.6725, 'EUR': 4.02, ...}
        """


# ── Implementation 1: StaticFXService (default / fallback) ───────────────────

class StaticFXService(IFXService):
    """
    Hardcoded exchange rates relative to AED.

    All rates mean: 1 foreign_currency = N AED.
    Inverse rates are computed on-the-fly for AED→foreign conversions.

    Used as the default fallback when no FX API is configured, and as the
    offline fallback when OpenExchangeRatesService fails.

    Rates are indicative (Apr 2025) and should be updated via a real provider
    in production. Set FX_PROVIDER=openexchangerates to get live rates.
    """

    # Rates: 1 foreign_currency = N AED
    _STATIC_RATES: Dict[str, float] = {
        "AED": 1.0,
        "USD": 3.6725,    # 1 USD = 3.6725 AED (USD/AED peg, very stable)
        "EUR": 4.02,
        "GBP": 4.68,
        "SAR": 0.9792,    # 1 SAR = 0.9792 AED (SAR/AED near-peg)
        "INR": 0.04408,
        "JPY": 0.0248,
        "CNY": 0.5078,
        "CAD": 2.70,
        "AUD": 2.37,
        "CHF": 4.13,
        "SGD": 2.72,
        "QAR": 1.0082,
        "KWD": 11.92,
        "BHD": 9.75,
        "OMR": 9.54,
        "EGP": 0.0755,
        "PKR": 0.0132,
        "MYR": 0.843,
    }

    def get_rate(self, from_currency: str, to_currency: str) -> float:
        """
        Return exchange rate: 1 from_currency = N to_currency.

        Strategy:
          1. from → AED: look up _STATIC_RATES[from_currency]
          2. AED → to: divide by _STATIC_RATES[to_currency]
          Combined: rate = _STATIC_RATES[from] / _STATIC_RATES[to]
        """
        fc = from_currency.upper()
        tc = to_currency.upper()

        if fc == tc:
            return 1.0

        from_rate = self._STATIC_RATES.get(fc)
        to_rate   = self._STATIC_RATES.get(tc)

        if from_rate is None:
            logger.warning(
                "[StaticFXService] No rate for %s; using 1.0", fc
            )
            return 1.0
        if to_rate is None:
            logger.warning(
                "[StaticFXService] No rate for %s; using 1.0", tc
            )
            return 1.0

        # Both rates are "N AED per 1 unit of currency"
        # from_currency → AED: multiply by from_rate
        # AED → to_currency: divide by to_rate
        # So: from → to = from_rate / to_rate
        return round(from_rate / to_rate, 6)

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """Convert amount using static rates."""
        rate = self.get_rate(from_currency, to_currency)
        return round(amount * rate, 2)

    def get_all_rates(self, base_currency: str = "AED") -> Dict[str, float]:
        """
        Return all rates relative to base_currency.
        Computes: 1 base_currency = N other_currency (inverts the storage convention).
        """
        bc = base_currency.upper()
        base_rate = self._STATIC_RATES.get(bc, 1.0)
        return {
            currency: round(base_rate / rate, 6)
            for currency, rate in self._STATIC_RATES.items()
            if rate > 0
        }


# ── Implementation 2: OpenExchangeRatesService ───────────────────────────────

class OpenExchangeRatesService(IFXService):
    """
    Live exchange rates from OpenExchangeRates (https://openexchangerates.org).

    Fetches rates with USD as base (free plan limitation), then cross-calculates
    to AED or any other target currency.

    Rates are cached in memory for 1 hour to avoid redundant API calls.

    On API failure, falls back to StaticFXService and logs a warning.

    Env vars required:
      OPENEXCHANGERATES_APP_ID — App ID from openexchangerates.org

    Rate structure from API:
      {"base": "USD", "rates": {"AED": 3.6725, "EUR": 0.93, ...}}
    """

    _API_URL = "https://openexchangerates.org/api/latest.json"
    _CACHE_TTL_SECONDS = 3600  # 1 hour

    def __init__(self) -> None:
        self._app_id = os.environ.get("OPENEXCHANGERATES_APP_ID", "").strip()
        if not self._app_id:
            raise ValueError(
                "OPENEXCHANGERATES_APP_ID not configured. "
                "Set FX_PROVIDER=static to use hardcoded rates, "
                "or set OPENEXCHANGERATES_APP_ID in your .env file."
            )
        self._fallback = StaticFXService()
        self._cached_rates: Optional[Dict[str, float]] = None   # USD-based rates
        self._cache_time: Optional[datetime] = None

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _is_cache_valid(self) -> bool:
        if self._cached_rates is None or self._cache_time is None:
            return False
        return (datetime.utcnow() - self._cache_time).total_seconds() < self._CACHE_TTL_SECONDS

    def _fetch_rates_from_api(self) -> Optional[Dict[str, float]]:
        """
        Fetch USD-based rates from OpenExchangeRates API.
        Returns dict {currency_code: rate_vs_USD} or None on failure.
        """
        import requests

        url = f"{self._API_URL}?app_id={self._app_id}&base=USD"
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                rates = data.get("rates", {})
                if rates:
                    self._cached_rates = {k.upper(): float(v) for k, v in rates.items()}
                    self._cache_time = datetime.utcnow()
                    logger.info(
                        "[OpenExchangeRatesService] Fetched %d rates (cached for 1h)",
                        len(self._cached_rates),
                    )
                    return self._cached_rates
                logger.warning("[OpenExchangeRatesService] API returned empty rates")
                return None
            logger.warning(
                "[OpenExchangeRatesService] API returned %s: %s",
                response.status_code,
                response.text[:200],
            )
            return None
        except Exception as exc:
            logger.warning("[OpenExchangeRatesService] API call failed: %s", exc)
            return None

    def _get_usd_rates(self) -> Optional[Dict[str, float]]:
        """Return cached USD-based rates, refreshing if expired."""
        if not self._is_cache_valid():
            self._fetch_rates_from_api()
        return self._cached_rates

    # ── Rate calculation ──────────────────────────────────────────────────────

    def _rate_via_usd(self, from_currency: str, to_currency: str) -> Optional[float]:
        """
        Cross-rate calculation via USD:
          from → USD: divide by usd_rates[from]
          USD → to: multiply by usd_rates[to]
        """
        usd_rates = self._get_usd_rates()
        if not usd_rates:
            return None

        fc = from_currency.upper()
        tc = to_currency.upper()

        # usd_rates[X] = "1 USD = X units of currency X"
        # So: 1 unit of X = (1 / usd_rates[X]) USD
        #     1 USD = usd_rates[Y] units of Y
        # Therefore: 1 X = (usd_rates[Y] / usd_rates[X]) Y

        from_rate = usd_rates.get(fc)
        to_rate   = usd_rates.get(tc)

        if from_rate is None or to_rate is None or from_rate == 0:
            return None

        return round(to_rate / from_rate, 6)

    # ── Public interface ──────────────────────────────────────────────────────

    def get_rate(self, from_currency: str, to_currency: str) -> float:
        """Return rate from live API, with static fallback."""
        if from_currency.upper() == to_currency.upper():
            return 1.0

        rate = self._rate_via_usd(from_currency, to_currency)
        if rate is not None:
            return rate

        logger.warning(
            "[OpenExchangeRatesService] Falling back to static rates for %s→%s",
            from_currency, to_currency,
        )
        return self._fallback.get_rate(from_currency, to_currency)

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """Convert amount using live API rates."""
        rate = self.get_rate(from_currency, to_currency)
        return round(amount * rate, 2)

    def get_all_rates(self, base_currency: str = "AED") -> Dict[str, float]:
        """Return all rates relative to base_currency using live data."""
        usd_rates = self._get_usd_rates()
        if not usd_rates:
            logger.warning("[OpenExchangeRatesService] Using static fallback for get_all_rates")
            return self._fallback.get_all_rates(base_currency)

        bc = base_currency.upper()
        base_usd_rate = usd_rates.get(bc)  # 1 USD = N base_currency
        if not base_usd_rate:
            return self._fallback.get_all_rates(base_currency)

        # Compute: 1 base_currency = ? other_currency
        # 1 BC = (1/base_usd_rate) USD = (other_usd_rate / base_usd_rate) other
        return {
            currency: round(usd_rate / base_usd_rate, 6)
            for currency, usd_rate in usd_rates.items()
        }


# ── Implementation 3: DatabaseFXService ──────────────────────────────────────

class DatabaseFXService(IFXService):
    """
    Exchange rates loaded from the exchange_rates database table via the
    pluggable data source adapter (ZERO hardcoded SQL).

    Expects the adapter to return rows with fields:
      currency_code   — ISO currency code (e.g. 'USD')
      rate_to_aed     — rate vs AED: 1 unit of currency_code = N AED
        OR
      from_currency   — source currency code
      to_currency     — target currency code
      rate            — exchange rate

    Uses the same adapter pattern as all agents (no direct DB access).
    Falls back to StaticFXService if the database has no rates.
    """

    def __init__(self) -> None:
        self._fallback = StaticFXService()
        self._rates_cache: Optional[Dict[str, float]] = None  # currency → AED rate

    def _load_rates(self) -> Dict[str, float]:
        """Load rates from the database adapter, returning {currency: aed_rate}."""
        if self._rates_cache is not None:
            return self._rates_cache

        try:
            from backend.services.adapters.factory import get_adapter
            rows = get_adapter().get_exchange_rates()

            rates: Dict[str, float] = {"AED": 1.0}

            for row in (rows or []):
                # Support multiple possible column layouts
                code = (
                    row.get("currency_code")
                    or row.get("from_currency")
                    or row.get("currency")
                    or ""
                ).upper()

                rate = float(
                    row.get("rate_to_aed")
                    or row.get("rate")
                    or row.get("exchange_rate")
                    or 0
                )

                if code and rate > 0:
                    rates[code] = rate

            if len(rates) > 1:
                self._rates_cache = rates
                logger.info(
                    "[DatabaseFXService] Loaded %d exchange rates from database", len(rates)
                )
                return rates

        except Exception as exc:
            logger.warning(
                "[DatabaseFXService] Failed to load rates from database: %s", exc
            )

        # No rates in DB — fall back to static
        logger.warning("[DatabaseFXService] Using static fallback rates")
        return self._fallback._STATIC_RATES.copy()  # type: ignore[attr-defined]

    def get_rate(self, from_currency: str, to_currency: str) -> float:
        """Return rate using database-loaded rates."""
        fc = from_currency.upper()
        tc = to_currency.upper()

        if fc == tc:
            return 1.0

        rates = self._load_rates()
        from_rate = rates.get(fc)
        to_rate   = rates.get(tc)

        if from_rate is None or to_rate is None:
            logger.warning(
                "[DatabaseFXService] Missing rate for %s or %s; using static fallback",
                fc, tc,
            )
            return self._fallback.get_rate(fc, tc)

        # Both are "N AED per 1 unit of currency"
        return round(from_rate / to_rate, 6)

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """Convert amount using database-loaded rates."""
        rate = self.get_rate(from_currency, to_currency)
        return round(amount * rate, 2)

    def get_all_rates(self, base_currency: str = "AED") -> Dict[str, float]:
        """Return all rates relative to base_currency."""
        rates = self._load_rates()
        bc = base_currency.upper()
        base_rate = rates.get(bc, 1.0)
        return {
            currency: round(base_rate / rate, 6)
            for currency, rate in rates.items()
            if rate > 0
        }


# ── Factory function ──────────────────────────────────────────────────────────

def get_fx_service() -> IFXService:
    """
    Return the configured FX rates service implementation.

    Reads the FX_PROVIDER environment variable:
      'static'            → StaticFXService (default, no API key needed)
      'database'          → DatabaseFXService (reads exchange_rates table)
      'openexchangerates' → OpenExchangeRatesService (OPENEXCHANGERATES_APP_ID required)

    Falls back to StaticFXService if the provider name is unrecognised.

    Environment Variables
    ---------------------
    FX_PROVIDER               : provider selection (default: 'static')
    OPENEXCHANGERATES_APP_ID  : required for 'openexchangerates' provider
    FX_BASE_CURRENCY          : base currency code (default: 'AED')
    """
    provider = os.environ.get("FX_PROVIDER", "static").strip().lower()

    if provider == "database":
        logger.info("[get_fx_service] Using DatabaseFXService")
        return DatabaseFXService()

    if provider == "openexchangerates":
        logger.info("[get_fx_service] Using OpenExchangeRatesService")
        return OpenExchangeRatesService()

    if provider != "static":
        logger.warning(
            "[get_fx_service] Unknown FX_PROVIDER '%s'; falling back to static.",
            provider,
        )

    logger.info("[get_fx_service] Using StaticFXService (default)")
    return StaticFXService()
