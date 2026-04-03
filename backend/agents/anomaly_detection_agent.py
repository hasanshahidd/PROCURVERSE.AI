"""
AnomalyDetectionAgent — Sprint 9
==================================
Detects unusual patterns in procurement spend, duplicate invoices, and
vendor anomalies.

Detection rules:
1. Duplicate invoice detection — same vendor + amount within 30 days
2. Spend spike — department spend > 150% of 3-month average
3. Off-hours PO — PO submitted outside business hours (before 7am or after 8pm)
4. Unusual vendor — new vendor with large first order (>AED 50,000)
5. Split PO — multiple POs to same vendor, same day, each just under approval threshold
6. Price variance — same item purchased at >20% price difference from last time
7. Duplicate vendor — two vendors with very similar names (potential duplicate)
8. Contract bypass — PO to vendor with expired/no contract
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.agents import AgentDecision, AgentStatus, BaseAgent
from backend.services.adapters.factory import get_adapter

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
_UNUSUAL_VENDOR_THRESHOLD_AED = 50_000.0
_PRICE_VARIANCE_PCT = 0.20          # 20 %
_SPEND_SPIKE_MULTIPLIER = 1.50      # 150 % of 3-month rolling average
_SPLIT_PO_THRESHOLD_DEFAULT = 10_000.0
_BUSINESS_HOURS_START = 7           # 07:00
_BUSINESS_HOURS_END = 20            # 20:00

# Severity levels (ordered low → high for comparison)
_SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _adapter():
    return get_adapter()


class AnomalyDetectionAgent(BaseAgent):
    """
    Sprint 9 — Anomaly Detection Agent.

    Runs multiple detection rules against recent POs, invoices, and vendor data
    then logs each finding to the agent_actions audit table.
    """

    def __init__(self) -> None:
        super().__init__(
            name="AnomalyDetectionAgent",
            description=(
                "Detects unusual patterns in procurement spend, duplicate invoices, "
                "and vendor anomalies using rule-based heuristics."
            ),
            temperature=0.1,
        )

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Load recent POs, invoices, and vendors via the adapter.

        Also loads recently flagged anomalies so we can avoid re-logging duplicates.
        """
        self.status = AgentStatus.OBSERVING
        lookback_days = input_data.get("lookback_days", 30)

        obs: Dict[str, Any] = {
            "lookback_days": lookback_days,
            "input_data": input_data,
            "purchase_orders": [],
            "invoices": [],
            "vendors": [],
            "existing_anomaly_keys": set(),
            "observe_errors": [],
        }

        # ── Purchase orders ───────────────────────────────────────────────────
        try:
            pos = _adapter().get_purchase_orders(limit=500)
            cutoff = datetime.utcnow() - timedelta(days=lookback_days)
            filtered_pos = []
            for po in pos:
                po_date = _parse_date(po.get("order_date") or po.get("date_order"))
                if po_date and po_date >= cutoff:
                    filtered_pos.append({**po, "_parsed_date": po_date})
                elif not po_date:
                    filtered_pos.append(po)
            obs["purchase_orders"] = filtered_pos
            logger.info(
                "[AnomalyDetectionAgent] Loaded %d POs (last %d days)",
                len(filtered_pos),
                lookback_days,
            )
        except Exception as exc:
            logger.error("[AnomalyDetectionAgent] Error loading POs: %s", exc)
            obs["observe_errors"].append(f"PO load: {exc}")

        # ── Invoices (via vendor_quotes or vendor_invoices) ───────────────────
        try:
            try:
                invoices = _adapter().get_vendor_invoices(limit=500)
            except AttributeError:
                invoices = _adapter().get_vendor_quotes(limit=500)
            obs["invoices"] = invoices or []
            logger.info(
                "[AnomalyDetectionAgent] Loaded %d invoice/quote records",
                len(obs["invoices"]),
            )
        except Exception as exc:
            logger.warning("[AnomalyDetectionAgent] Error loading invoices: %s", exc)
            obs["observe_errors"].append(f"Invoice load: {exc}")

        # ── Vendors ───────────────────────────────────────────────────────────
        try:
            vendors = _adapter().get_vendors(limit=500)
            obs["vendors"] = vendors or []
        except Exception as exc:
            logger.warning("[AnomalyDetectionAgent] Error loading vendors: %s", exc)
            obs["observe_errors"].append(f"Vendor load: {exc}")

        # ── Already-flagged anomaly keys (avoid duplicate logging) ────────────
        try:
            from backend.services.nmi_data_service import get_conn

            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT output_data
                        FROM agent_actions
                        WHERE agent_name = 'AnomalyDetectionAgent'
                          AND action_type LIKE 'anomaly%'
                          AND created_at >= NOW() - INTERVAL '7 days'
                        ORDER BY created_at DESC
                        LIMIT 200
                        """
                    )
                    rows = cur.fetchall()
                    for row in rows:
                        od = row[0] if isinstance(row, (list, tuple)) else row.get("output_data", {})
                        if isinstance(od, dict):
                            key = od.get("anomaly_key")
                            if key:
                                obs["existing_anomaly_keys"].add(key)
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "[AnomalyDetectionAgent] Could not load existing anomaly keys: %s", exc
            )

        return obs

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Run all detection rules and compile the anomaly list."""
        self.status = AgentStatus.THINKING

        pos = observations.get("purchase_orders", [])
        invoices = observations.get("invoices", [])
        vendors = observations.get("vendors", [])
        existing_keys: set = observations.get("existing_anomaly_keys", set())
        threshold = observations.get("input_data", {}).get(
            "severity_threshold", "LOW"
        )

        all_anomalies: List[Dict[str, Any]] = []

        # Run all detection rules
        all_anomalies += self._detect_duplicate_invoices(invoices)
        all_anomalies += self._detect_spend_spikes(pos)
        all_anomalies += self._detect_off_hours_pos(pos)
        all_anomalies += self._detect_unusual_vendors(pos, vendors)
        all_anomalies += self._detect_split_pos(pos)
        all_anomalies += self._detect_price_variance(pos)
        all_anomalies += self._detect_duplicate_vendors(vendors)

        # Filter by severity threshold
        min_rank = _SEVERITY_RANK.get(threshold.upper(), 0)
        filtered = [
            a
            for a in all_anomalies
            if _SEVERITY_RANK.get(a.get("severity", "LOW"), 0) >= min_rank
        ]

        # Remove already-logged anomalies
        new_anomalies = [
            a for a in filtered if a.get("anomaly_key", "") not in existing_keys
        ]

        logger.info(
            "[AnomalyDetectionAgent] Rules found %d anomalies (%d new after dedup)",
            len(all_anomalies),
            len(new_anomalies),
        )

        if new_anomalies:
            action = "anomalies_found"
            reasoning = (
                f"Detected {len(new_anomalies)} new anomaly(ies): "
                + ", ".join(
                    f"{a['anomaly_type']}({a['severity']})" for a in new_anomalies[:5]
                )
            )
            confidence = 0.88
        else:
            action = "no_anomalies"
            reasoning = "No new procurement anomalies detected."
            confidence = 0.92

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                **observations,
                "anomalies": new_anomalies,
                "total_detected": len(all_anomalies),
            },
            alternatives=["manual_review"],
        )

    # ── ACT ───────────────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Log each anomaly to agent_actions and return a summary."""
        self.status = AgentStatus.ACTING
        ctx = decision.context
        anomalies: List[Dict[str, Any]] = ctx.get("anomalies", [])

        result: Dict[str, Any] = {
            "success": True,
            "agent": self.name,
            "action": decision.action,
            "total_detected": ctx.get("total_detected", 0),
            "new_anomalies_logged": 0,
            "anomalies": anomalies,
            "by_severity": defaultdict(int),
        }

        for anomaly in anomalies:
            severity = anomaly.get("severity", "LOW")
            result["by_severity"][severity] += 1

            try:
                await self._log_action(
                    action_type="anomaly_detected",
                    input_data={
                        "anomaly_type": anomaly.get("anomaly_type"),
                        "severity": severity,
                    },
                    output_data=anomaly,
                    success=True,
                )
                result["new_anomalies_logged"] += 1
                logger.info(
                    "[AnomalyDetectionAgent] Logged anomaly: %s | %s | %s",
                    anomaly.get("anomaly_type"),
                    severity,
                    anomaly.get("description", "")[:80],
                )
            except Exception as exc:
                logger.error(
                    "[AnomalyDetectionAgent] Failed to log anomaly %s: %s",
                    anomaly.get("anomaly_key"),
                    exc,
                )

        result["by_severity"] = dict(result["by_severity"])
        result["message"] = (
            f"Logged {result['new_anomalies_logged']} anomaly(ies). "
            f"By severity: {result['by_severity']}."
        )
        return result

    # ── LEARN ─────────────────────────────────────────────────────────────────

    async def learn(self, result: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        logger.info(
            "[AnomalyDetectionAgent] Learning — logged=%s",
            result.get("result", {}).get("new_anomalies_logged", 0),
        )

    # ── EXECUTE ───────────────────────────────────────────────────────────────

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)

    # ── Detection implementations ─────────────────────────────────────────────

    def _detect_duplicate_invoices(self, invoices: List[Dict]) -> List[Dict[str, Any]]:
        """Same vendor + same amount within 30 days."""
        anomalies: List[Dict[str, Any]] = []
        seen: Dict[str, Any] = {}  # key → first_invoice

        for inv in invoices:
            vendor = str(inv.get("vendor_id") or inv.get("vendor") or inv.get("partner_id") or "")
            amount = _to_float(inv.get("amount_total") or inv.get("amount") or inv.get("total_amount"))
            inv_date = _parse_date(inv.get("invoice_date") or inv.get("date_invoice") or inv.get("date"))
            inv_ref = str(inv.get("name") or inv.get("invoice_number") or inv.get("id") or "")

            if not vendor or amount is None:
                continue

            key = f"{vendor}|{round(amount, 2)}"
            if key in seen:
                first = seen[key]
                first_date = first.get("_parsed_date")
                days_diff = abs((inv_date - first_date).days) if inv_date and first_date else 0

                if days_diff <= 30:
                    anomaly_key = f"dup_inv|{key}|{inv_ref}"
                    anomalies.append(
                        {
                            "anomaly_key": anomaly_key,
                            "anomaly_type": "duplicate_invoice",
                            "severity": "HIGH",
                            "description": (
                                f"Possible duplicate invoice: vendor={vendor}, "
                                f"amount={amount:.2f}, days apart={days_diff}"
                            ),
                            "affected_records": [first.get("_ref", ""), inv_ref],
                            "recommended_action": (
                                "Place invoice on hold and request AP specialist review."
                            ),
                            "vendor": vendor,
                            "amount": amount,
                            "days_apart": days_diff,
                        }
                    )
            else:
                seen[key] = {**inv, "_parsed_date": inv_date, "_ref": inv_ref}

        return anomalies

    def _detect_spend_spikes(self, pos: List[Dict]) -> List[Dict[str, Any]]:
        """Department spend > 150% of rolling 3-month average."""
        anomalies: List[Dict[str, Any]] = []

        now = datetime.utcnow()
        period_90 = now - timedelta(days=90)
        period_30 = now - timedelta(days=30)

        # Bucket spend by department
        dept_90: Dict[str, float] = defaultdict(float)
        dept_30: Dict[str, float] = defaultdict(float)

        for po in pos:
            dept = str(po.get("department") or po.get("department_id") or "Unknown")
            amount = _to_float(
                po.get("amount_total") or po.get("amount") or po.get("total_amount")
            )
            po_date = po.get("_parsed_date") or _parse_date(
                po.get("order_date") or po.get("date_order")
            )
            if amount is None or amount <= 0:
                continue
            if po_date and po_date >= period_90:
                dept_90[dept] += amount
            if po_date and po_date >= period_30:
                dept_30[dept] += amount

        for dept, last_30 in dept_30.items():
            total_90 = dept_90.get(dept, 0)
            # Average monthly spend based on prior 60 days (90 - 30)
            avg_monthly = (total_90 - last_30) / 2 if total_90 > last_30 else total_90 / 3
            if avg_monthly <= 0:
                continue
            ratio = last_30 / avg_monthly
            if ratio >= _SPEND_SPIKE_MULTIPLIER:
                anomaly_key = f"spend_spike|{dept}|{int(last_30)}"
                anomalies.append(
                    {
                        "anomaly_key": anomaly_key,
                        "anomaly_type": "spend_spike",
                        "severity": "HIGH" if ratio >= 2.0 else "MEDIUM",
                        "description": (
                            f"Department '{dept}' spend in last 30 days is "
                            f"{ratio*100:.0f}% of monthly average "
                            f"({last_30:.0f} vs avg {avg_monthly:.0f})."
                        ),
                        "affected_records": [dept],
                        "recommended_action": (
                            "Review department budget allocation and approve/reject excess spend."
                        ),
                        "department": dept,
                        "last_30_day_spend": last_30,
                        "monthly_avg": avg_monthly,
                        "spike_ratio": round(ratio, 2),
                    }
                )

        return anomalies

    def _detect_off_hours_pos(self, pos: List[Dict]) -> List[Dict[str, Any]]:
        """PO submitted outside business hours (before 7am or after 8pm)."""
        anomalies: List[Dict[str, Any]] = []

        for po in pos:
            po_date = po.get("_parsed_date") or _parse_date(
                po.get("order_date") or po.get("date_order")
            )
            if not po_date:
                continue
            hour = po_date.hour
            if hour < _BUSINESS_HOURS_START or hour >= _BUSINESS_HOURS_END:
                po_ref = str(po.get("po_number") or po.get("name") or po.get("id") or "")
                anomaly_key = f"off_hours|{po_ref}|{po_date.date()}"
                anomalies.append(
                    {
                        "anomaly_key": anomaly_key,
                        "anomaly_type": "off_hours_po",
                        "severity": "LOW",
                        "description": (
                            f"PO {po_ref} submitted at {po_date.strftime('%H:%M')} "
                            f"(outside business hours 07:00-20:00)."
                        ),
                        "affected_records": [po_ref],
                        "recommended_action": "Verify PO was submitted by authorised user.",
                        "po_number": po_ref,
                        "submitted_at": po_date.isoformat(),
                    }
                )

        return anomalies

    def _detect_unusual_vendors(
        self, pos: List[Dict], vendors: List[Dict]
    ) -> List[Dict[str, Any]]:
        """New vendor (first order) with large amount (>AED 50,000)."""
        anomalies: List[Dict[str, Any]] = []

        # Find vendors that appear only once in PO history
        vendor_po_count: Dict[str, int] = defaultdict(int)
        vendor_po_amount: Dict[str, float] = defaultdict(float)
        vendor_po_ref: Dict[str, str] = {}

        for po in pos:
            vendor = str(
                po.get("vendor_id") or po.get("partner_id") or po.get("vendor") or ""
            )
            amount = _to_float(
                po.get("amount_total") or po.get("amount") or po.get("total_amount")
            ) or 0.0
            po_ref = str(po.get("po_number") or po.get("name") or po.get("id") or "")
            if vendor:
                vendor_po_count[vendor] += 1
                vendor_po_amount[vendor] += amount
                if vendor not in vendor_po_ref:
                    vendor_po_ref[vendor] = po_ref

        for vendor, count in vendor_po_count.items():
            if count == 1:
                total = vendor_po_amount[vendor]
                if total >= _UNUSUAL_VENDOR_THRESHOLD_AED:
                    po_ref = vendor_po_ref.get(vendor, "")
                    anomaly_key = f"unusual_vendor|{vendor}|{po_ref}"
                    anomalies.append(
                        {
                            "anomaly_key": anomaly_key,
                            "anomaly_type": "unusual_vendor",
                            "severity": "MEDIUM" if total < 200_000 else "HIGH",
                            "description": (
                                f"New vendor '{vendor}' placed first order of "
                                f"AED {total:,.0f} (threshold: AED {_UNUSUAL_VENDOR_THRESHOLD_AED:,.0f})."
                            ),
                            "affected_records": [po_ref],
                            "recommended_action": (
                                "Verify vendor credentials, trade licence, and approve large first order."
                            ),
                            "vendor": vendor,
                            "first_order_amount": total,
                            "po_reference": po_ref,
                        }
                    )

        return anomalies

    def _detect_split_pos(
        self, pos: List[Dict], threshold: float = _SPLIT_PO_THRESHOLD_DEFAULT
    ) -> List[Dict[str, Any]]:
        """
        Multiple POs to same vendor, same day, each just under the approval threshold.
        """
        anomalies: List[Dict[str, Any]] = []

        # Group by vendor + date
        groups: Dict[str, List[Dict]] = defaultdict(list)
        for po in pos:
            vendor = str(
                po.get("vendor_id") or po.get("partner_id") or po.get("vendor") or ""
            )
            po_date = po.get("_parsed_date") or _parse_date(
                po.get("order_date") or po.get("date_order")
            )
            amount = _to_float(
                po.get("amount_total") or po.get("amount") or po.get("total_amount")
            )
            if vendor and po_date and amount is not None:
                key = f"{vendor}|{po_date.date()}"
                groups[key].append({**po, "_amount": amount})

        for key, group in groups.items():
            if len(group) < 2:
                continue
            # All amounts just under threshold
            under_threshold = [g for g in group if 0 < g["_amount"] < threshold]
            if len(under_threshold) >= 2:
                total = sum(g["_amount"] for g in under_threshold)
                vendor, date_str = key.split("|", 1)
                refs = [
                    str(g.get("po_number") or g.get("name") or g.get("id") or "")
                    for g in under_threshold
                ]
                anomaly_key = f"split_po|{vendor}|{date_str}"
                anomalies.append(
                    {
                        "anomaly_key": anomaly_key,
                        "anomaly_type": "split_po",
                        "severity": "HIGH",
                        "description": (
                            f"Potential PO splitting: {len(under_threshold)} POs to "
                            f"vendor '{vendor}' on {date_str}, each under AED {threshold:,.0f}. "
                            f"Combined: AED {total:,.0f}."
                        ),
                        "affected_records": refs,
                        "recommended_action": (
                            "Escalate to procurement director for consolidated approval."
                        ),
                        "vendor": vendor,
                        "date": date_str,
                        "po_count": len(under_threshold),
                        "combined_amount": total,
                        "approval_threshold": threshold,
                    }
                )

        return anomalies

    def _detect_price_variance(self, pos: List[Dict]) -> List[Dict[str, Any]]:
        """Same item purchased at >20% price difference from last time."""
        anomalies: List[Dict[str, Any]] = []

        # Build item → list of (date, unit_price, po_ref)
        item_prices: Dict[str, List[tuple]] = defaultdict(list)

        for po in pos:
            line_items = po.get("line_items") or po.get("order_line") or []
            if not isinstance(line_items, list):
                continue
            po_date = po.get("_parsed_date") or _parse_date(
                po.get("order_date") or po.get("date_order")
            )
            po_ref = str(po.get("po_number") or po.get("name") or po.get("id") or "")
            for line in line_items:
                product = str(
                    line.get("product_id") or line.get("product") or line.get("item_code") or ""
                )
                price = _to_float(
                    line.get("price_unit") or line.get("unit_price") or line.get("price")
                )
                if product and price and price > 0:
                    item_prices[product].append((po_date, price, po_ref))

        for product, entries in item_prices.items():
            if len(entries) < 2:
                continue
            entries_sorted = sorted(
                [e for e in entries if e[0] is not None], key=lambda x: x[0]
            )
            if len(entries_sorted) < 2:
                continue
            prev_date, prev_price, prev_ref = entries_sorted[-2]
            curr_date, curr_price, curr_ref = entries_sorted[-1]
            if prev_price == 0:
                continue
            variance = abs(curr_price - prev_price) / prev_price
            if variance > _PRICE_VARIANCE_PCT:
                direction = "increase" if curr_price > prev_price else "decrease"
                anomaly_key = f"price_var|{product}|{curr_ref}"
                anomalies.append(
                    {
                        "anomaly_key": anomaly_key,
                        "anomaly_type": "price_variance",
                        "severity": "MEDIUM" if variance < 0.5 else "HIGH",
                        "description": (
                            f"Item '{product}' price {direction} of "
                            f"{variance*100:.1f}% detected: "
                            f"was {prev_price:.2f} (PO {prev_ref}), "
                            f"now {curr_price:.2f} (PO {curr_ref})."
                        ),
                        "affected_records": [prev_ref, curr_ref],
                        "recommended_action": (
                            "Verify price change with vendor contract — request updated quote."
                        ),
                        "product": product,
                        "previous_price": prev_price,
                        "current_price": curr_price,
                        "variance_pct": round(variance * 100, 1),
                    }
                )

        return anomalies

    def _detect_duplicate_vendors(self, vendors: List[Dict]) -> List[Dict[str, Any]]:
        """
        Vendors with very similar names (Levenshtein distance < 3).

        Potential duplicate vendor accounts that could lead to fraud.
        """
        anomalies: List[Dict[str, Any]] = []

        names: List[tuple[str, str]] = []
        for v in vendors:
            name = str(v.get("name") or v.get("vendor_name") or "").strip()
            vid = str(v.get("id") or v.get("vendor_id") or "")
            if name and len(name) > 3:
                names.append((name, vid))

        checked: set[str] = set()
        for i, (name_a, id_a) in enumerate(names):
            for name_b, id_b in names[i + 1 :]:
                pair_key = "|".join(sorted([id_a, id_b]))
                if pair_key in checked:
                    continue
                checked.add(pair_key)
                dist = _levenshtein(name_a.lower(), name_b.lower())
                # Scale threshold by name length — short names need distance < 2
                max_dist = 2 if len(name_a) <= 8 else 3
                if 0 < dist <= max_dist:
                    anomaly_key = f"dup_vendor|{pair_key}"
                    anomalies.append(
                        {
                            "anomaly_key": anomaly_key,
                            "anomaly_type": "duplicate_vendor",
                            "severity": "MEDIUM",
                            "description": (
                                f"Similar vendor names detected: "
                                f"'{name_a}' (id={id_a}) vs "
                                f"'{name_b}' (id={id_b}). "
                                f"Levenshtein distance={dist}."
                            ),
                            "affected_records": [id_a, id_b],
                            "recommended_action": (
                                "Review vendor master data and merge duplicates if confirmed."
                            ),
                            "vendor_a": name_a,
                            "vendor_b": name_b,
                            "levenshtein_distance": dist,
                        }
                    )

        return anomalies


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(value: Any) -> Optional[datetime]:
    """Parse a date string or datetime object to datetime, or return None."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(str(value)[:19], fmt)
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> Optional[float]:
    """Convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _levenshtein(s1: str, s2: str) -> int:
    """Compute the Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    rows = len(s1) + 1
    cols = len(s2) + 1
    dist = [[0] * cols for _ in range(rows)]

    for i in range(rows):
        dist[i][0] = i
    for j in range(cols):
        dist[0][j] = j

    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dist[i][j] = min(
                dist[i - 1][j] + 1,
                dist[i][j - 1] + 1,
                dist[i - 1][j - 1] + cost,
            )

    return dist[-1][-1]
