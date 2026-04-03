"""
VendorOnboardingAgent — WF-15
==============================
New Vendor Registration & Validation.

Workflows covered
-----------------
WF-15  New Vendor Registration & Validation
       Accepts vendor self-registration data, runs automated compliance checks,
       scores the vendor, and routes to approved / conditional / rejected status.

Business value
--------------
- Enforces consistent vendor onboarding quality standards
- Flags high-risk countries automatically so compliance reviews vendors early
- Eliminates duplicate registrations by checking against the existing vendor list
- Produces a clear audit trail of every validation decision
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.agents import AgentDecision, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# Known procurement categories (case-insensitive matching)
_KNOWN_CATEGORIES = {
    "it", "information technology", "office supplies", "facilities",
    "professional services", "logistics", "raw materials", "manufacturing",
    "marketing", "hr", "human resources", "travel", "utilities",
    "construction", "software", "hardware", "consulting", "legal",
    "finance", "medical", "food & beverage", "food and beverage",
    "telecommunications", "telecoms", "energy", "security",
    "maintenance", "mro", "capex", "opex",
}

# High-risk countries (ISO alpha-2 codes, lower-case) — extend as needed
_HIGH_RISK_COUNTRIES = {
    "kp",  # North Korea
    "ir",  # Iran
    "sy",  # Syria
    "cu",  # Cuba
    "ru",  # Russia (sanctions-risk)
    "by",  # Belarus
    "mm",  # Myanmar
    "sd",  # Sudan
    "so",  # Somalia
    "ye",  # Yemen
}

# Compliance thresholds
_SCORE_APPROVED     = 80
_SCORE_CONDITIONAL  = 60


class VendorOnboardingAgent(BaseAgent):
    """
    Validates and onboards new vendor registrations.

    Observe  → Accept vendor_data dict; check required fields completeness.
    Decide   → Run 6 validation checks; compute compliance_score (0–100).
               Query adapter.get_vendors() for duplicate detection.
    Act      → Return onboarding_result: compliance_score, check_results,
               status (approved_for_onboarding / conditional_approval / rejected),
               next_steps list.
    Learn    → Log vendor name, score, and status.
    """

    def __init__(self) -> None:
        super().__init__(
            name="VendorOnboardingAgent",
            description=(
                "Validates new vendor registration data through automated compliance "
                "checks and routes to approved, conditional, or rejected status."
            ),
            temperature=0.1,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)

    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.status = AgentStatus.OBSERVING

        # Accept vendor_data as a sub-dict or flat keys
        vendor_data: Dict[str, Any] = (
            context.get("vendor_data") or context
        )

        # Pull fields with fallbacks
        vendor_name           = str(vendor_data.get("vendor_name") or "").strip()
        contact_email         = str(vendor_data.get("contact_email") or "").strip()
        category              = str(vendor_data.get("category") or "").strip()
        country               = str(vendor_data.get("country") or "").strip()
        registration_number   = str(vendor_data.get("registration_number") or "").strip()
        bank_details_provided = bool(vendor_data.get("bank_details_provided", False))
        tax_id                = str(vendor_data.get("tax_id") or "").strip()

        # Load existing vendors for duplicate check
        existing_vendors: List[Dict[str, Any]] = []
        try:
            from backend.services.adapters.factory import get_adapter
            adapter = get_adapter()
            existing_vendors = adapter.get_vendors(active_only=False, limit=1000)
        except Exception as exc:
            logger.warning("[VendorOnboardingAgent] Could not load existing vendors: %s", exc)

        logger.info(
            "[VendorOnboardingAgent] Validating vendor='%s' category='%s' country='%s'",
            vendor_name, category, country,
        )

        return {
            "vendor_name": vendor_name,
            "contact_email": contact_email,
            "category": category,
            "country": country,
            "registration_number": registration_number,
            "bank_details_provided": bank_details_provided,
            "tax_id": tax_id,
            "existing_vendors": existing_vendors,
            "input_context": context,
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        self.status = AgentStatus.THINKING

        vendor_name           = observations.get("vendor_name", "")
        contact_email         = observations.get("contact_email", "")
        category              = observations.get("category", "")
        country               = observations.get("country", "")
        registration_number   = observations.get("registration_number", "")
        bank_details_provided = observations.get("bank_details_provided", False)
        tax_id                = observations.get("tax_id", "")
        existing_vendors      = observations.get("existing_vendors", [])

        if not vendor_name:
            return AgentDecision(
                action="missing_vendor_name",
                reasoning="vendor_name is required and was not provided.",
                confidence=0.98,
                context={**observations, "check_results": {}, "compliance_score": 0.0, "status": "rejected"},
            )

        # ── Run validation checks ──────────────────────────────────────────────
        check_results: Dict[str, Dict[str, Any]] = {}

        # Check 1: name_valid
        name_valid = (
            len(vendor_name) > 3
            and bool(re.match(r'^[A-Za-z0-9 &,.\'\-()]+$', vendor_name))
        )
        check_results["name_valid"] = {
            "passed": name_valid,
            "detail": (
                "Vendor name is valid."
                if name_valid
                else "Vendor name must be > 3 chars and contain no special characters."
            ),
        }

        # Check 2: email_valid
        email_valid = bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', contact_email))
        check_results["email_valid"] = {
            "passed": email_valid,
            "detail": (
                "Contact email format is valid."
                if email_valid
                else f"Invalid email format: '{contact_email}'."
            ),
        }

        # Check 3: category_valid
        cat_lower = category.lower().strip()
        category_valid = cat_lower in _KNOWN_CATEGORIES
        check_results["category_valid"] = {
            "passed": category_valid,
            "detail": (
                f"Category '{category}' is recognised."
                if category_valid
                else f"Category '{category}' is not in the approved procurement categories list."
            ),
        }

        # Check 4: country_risk
        country_lower = country.lower().strip()
        country_high_risk = country_lower in _HIGH_RISK_COUNTRIES
        country_check_passed = not country_high_risk  # passes if NOT high risk
        check_results["country_risk"] = {
            "passed": country_check_passed,
            "detail": (
                f"Country '{country}' is not on the high-risk list."
                if country_check_passed
                else f"Country '{country}' is on the high-risk/sanctioned country list. Manual compliance review required."
            ),
            "high_risk": country_high_risk,
        }

        # Check 4b: sanctions_screening (Sprint 8 — real-time sanctions check)
        # Uses pluggable sanctions service (local blocklist by default, OFAC/OpenSanctions if configured).
        sanctions_passed = True
        sanctions_detail = "Vendor passed sanctions screening."
        sanctions_data: Dict[str, Any] = {}
        try:
            from backend.services.sanctions_service import get_sanctions_service
            svc = get_sanctions_service()
            # Use ISO alpha-2 country code if short enough, else pass raw value
            country_code = country.upper().strip()[:2] if len(country.strip()) <= 3 else ""
            sanctions_result = svc.check_vendor(
                vendor_name=vendor_name,
                country=country_code or None,
            )
            is_sanctioned = sanctions_result.get("is_sanctioned", False)
            risk_level = sanctions_result.get("risk_level", "clear")
            sanctions_data = {
                "is_sanctioned": is_sanctioned,
                "risk_level": risk_level,
                "source": sanctions_result.get("source", "unknown"),
                "matches": sanctions_result.get("matches", []),
            }
            if is_sanctioned or risk_level in ("blocked", "high"):
                sanctions_passed = False
                sanctions_detail = (
                    f"Vendor '{vendor_name}' flagged by sanctions screening "
                    f"(risk_level={risk_level}, source={sanctions_result.get('source')}). "
                    "Compliance review required."
                )
            elif risk_level == "medium":
                sanctions_detail = (
                    f"Vendor '{vendor_name}' shows a medium-risk sanctions signal. "
                    "Recommend compliance review."
                )
        except Exception as exc:
            logger.warning(
                "[VendorOnboardingAgent] Sanctions check failed (%s); "
                "defaulting to passed.", exc,
            )
            sanctions_detail = f"Sanctions check unavailable ({type(exc).__name__}); manual review recommended."

        check_results["sanctions_screening"] = {
            "passed": sanctions_passed,
            "detail": sanctions_detail,
            **sanctions_data,
        }

        # Check 5: duplicate_check
        existing_names = {
            str(v.get("vendor_name") or v.get("name") or "").strip().lower()
            for v in existing_vendors
        }
        is_duplicate = vendor_name.lower() in existing_names
        duplicate_passed = not is_duplicate
        check_results["duplicate_check"] = {
            "passed": duplicate_passed,
            "detail": (
                "No duplicate vendor found in the system."
                if duplicate_passed
                else f"Vendor '{vendor_name}' already exists in the vendor master."
            ),
        }

        # Check 6: tax_id_present
        tax_id_present = len(tax_id) >= 3
        check_results["tax_id_present"] = {
            "passed": tax_id_present,
            "detail": (
                "Tax ID is present."
                if tax_id_present
                else "Tax ID is missing or too short — required for compliance."
            ),
        }

        # ── Compliance score ───────────────────────────────────────────────────
        total_checks  = len(check_results)
        passed_checks = sum(1 for v in check_results.values() if v["passed"])
        compliance_score = round(passed_checks / total_checks * 100, 1)

        # ── Routing decision ───────────────────────────────────────────────────
        if compliance_score >= _SCORE_APPROVED:
            status = "approved_for_onboarding"
        elif compliance_score >= _SCORE_CONDITIONAL:
            status = "conditional_approval"
        else:
            status = "rejected"

        reasoning = (
            f"Vendor '{vendor_name}' scored {compliance_score:.0f}% "
            f"({passed_checks}/{total_checks} checks passed). "
            f"Status: {status}."
        )
        confidence = 0.92 if total_checks > 0 else 0.5

        return AgentDecision(
            action="evaluate_vendor_onboarding",
            reasoning=reasoning,
            confidence=confidence,
            context={
                **observations,
                "check_results": check_results,
                "compliance_score": compliance_score,
                "passed_checks": passed_checks,
                "total_checks": total_checks,
                "status": status,
            },
        )

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        self.status = AgentStatus.ACTING

        ctx            = decision.context
        vendor_name    = ctx.get("vendor_name", "")
        status         = ctx.get("status", "rejected")
        compliance_score = ctx.get("compliance_score", 0.0)
        check_results  = ctx.get("check_results", {})
        action         = decision.action

        # Build next_steps list based on outcome
        next_steps: List[str] = []
        if status == "approved_for_onboarding":
            next_steps = [
                "Add vendor to vendor master data.",
                "Set up payment terms and bank details.",
                "Issue vendor number and welcome communication.",
                "Schedule initial performance review in 90 days.",
            ]
        elif status == "conditional_approval":
            failed = [k for k, v in check_results.items() if not v.get("passed")]
            next_steps = [
                f"Resolve failed check(s): {', '.join(failed)}.",
                "Submit additional documentation for review.",
                "Compliance team to approve before vendor is activated.",
            ]
        else:  # rejected
            failed = [k for k, v in check_results.items() if not v.get("passed")]
            next_steps = [
                f"Registration rejected due to: {', '.join(failed)}.",
                "Vendor may reapply after resolving the listed issues.",
                "No vendor number will be issued at this time.",
            ]

        # Write approved vendors back via adapter if possible
        write_result = None
        if status == "approved_for_onboarding":
            write_result = await self._persist_vendor(ctx)

        result: Dict[str, Any] = {
            "success": True,
            "agent": self.name,
            "action": action,
            "vendor_name": vendor_name,
            "compliance_score": compliance_score,
            "check_results": check_results,
            "status": status,
            "next_steps": next_steps,
            "vendor_written": write_result is not None,
            "onboarding_result": {
                "vendor_name": vendor_name,
                "compliance_score": compliance_score,
                "status": status,
                "check_results": check_results,
                "next_steps": next_steps,
            },
            "timestamp": datetime.now().isoformat(),
        }

        status_labels = {
            "approved_for_onboarding": "APPROVED",
            "conditional_approval": "CONDITIONAL",
            "rejected": "REJECTED",
        }
        result["message"] = (
            f"Vendor '{vendor_name}' — {status_labels.get(status, status)} "
            f"(score: {compliance_score:.0f}%). "
            f"{len(next_steps)} next step(s) issued."
        )

        await self._log_action(
            action_type=f"vendor_onboarding_{status}",
            input_data=ctx.get("input_context", {}),
            output_data=result,
            success=True,
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        result = learn_context.get("result", {})
        logger.info(
            "[VendorOnboardingAgent] Learned: vendor='%s'  score=%.0f%%  status=%s",
            result.get("vendor_name", "?"),
            result.get("compliance_score", 0),
            result.get("status", "?"),
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _persist_vendor(self, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Attempt to write the newly approved vendor to the vendor list via adapter.
        Returns the persisted row dict on success, None on failure.
        Falls back gracefully — onboarding result is not blocked by write failures.
        """
        try:
            from backend.services.adapters.factory import get_adapter
            from backend.services.nmi_data_service import get_conn
            from psycopg2.extras import RealDictCursor

            adapter = get_adapter()
            suffix = getattr(adapter, '_get_erp_suffix', lambda: '')()
            table = f"vendors_{suffix}" if suffix else "vendors"

            conn = get_conn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    if suffix:
                        # ERP-suffix table insert (minimal neutral fields)
                        cur.execute(
                            f"""
                            INSERT INTO {table} (name, active, erp_source)
                            VALUES (%s, %s, %s)
                            ON CONFLICT DO NOTHING
                            RETURNING *
                            """,
                            (ctx.get("vendor_name"), True, suffix),
                        )
                    else:
                        # Neutral vendors table
                        cur.execute(
                            """
                            INSERT INTO vendors
                                (vendor_name, contact_email, category, country,
                                 registration_number, tax_id, active)
                            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                            ON CONFLICT DO NOTHING
                            RETURNING *
                            """,
                            (
                                ctx.get("vendor_name"),
                                ctx.get("contact_email"),
                                ctx.get("category"),
                                ctx.get("country"),
                                ctx.get("registration_number"),
                                ctx.get("tax_id"),
                            ),
                        )
                    conn.commit()
                    row = cur.fetchone()
                    if row:
                        logger.info(
                            "[VendorOnboardingAgent] Vendor '%s' persisted to %s.",
                            ctx.get("vendor_name"), table,
                        )
                        return dict(row)
                    return None
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "[VendorOnboardingAgent] Could not persist vendor to DB: %s", exc
            )
            return None


# ── Standalone entry point ─────────────────────────────────────────────────────

async def onboard_vendor(params: Dict[str, Any]) -> Dict[str, Any]:
    """Standalone async function — call from orchestrator or API route."""
    agent = VendorOnboardingAgent()
    return await agent.execute(params)
