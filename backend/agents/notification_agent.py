"""
NotificationAgent — Sprint 8
Dispatches multi-channel notifications (email, in-app) for procurement events.

Workflows covered: All (notification dispatch for WF-01 to WF-20)
Events handled:
- approval_requested: when PR needs approval
- approval_decided: when PR approved/rejected
- payment_scheduled: when payment run created
- low_stock_alert: when inventory below threshold
- contract_expiry: when contract expiring in 30 days
- anomaly_detected: when spend anomaly found
"""

from typing import Dict, Any, List
import logging
from datetime import datetime

from backend.agents import BaseAgent, AgentDecision, AgentStatus

logger = logging.getLogger(__name__)

# Supported event types
EVENT_TYPES = {
    "approval_requested",
    "approval_decided",
    "payment_scheduled",
    "low_stock_alert",
    "contract_expiry",
    "anomaly_detected",
}


class NotificationAgent(BaseAgent):
    """
    Routes procurement events to the appropriate notification channels.

    Channels:
    - email   : always attempted when send_email=True in context
    - in_app  : always logged to agent_actions (no dedicated table yet)
    - slack   : enabled when SLACK_BOT_TOKEN env var is set (Sprint 9)
    """

    def __init__(self):
        super().__init__(
            name="NotificationAgent",
            description=(
                "Dispatches multi-channel notifications (email, in-app) for all "
                "procurement events across WF-01 to WF-20."
            ),
            tools=[],
            temperature=0.0,  # deterministic dispatch
        )
        logger.info("NotificationAgent initialized")

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Main entry point — follows full observe → decide → act → learn cycle."""
        return await self.execute_with_recovery(input_data)

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Load event data from context and validate required fields."""
        self.status = AgentStatus.OBSERVING
        observations = await super().observe(context)

        event_type = context.get("event_type", "")
        recipients = context.get("recipients", [])
        payload = context.get("payload", {})
        send_email_flag = context.get("send_email", True)

        # Normalise recipients to a list of dicts: [{email, name, role}]
        normalised: List[Dict[str, Any]] = []
        for r in recipients:
            if isinstance(r, str):
                normalised.append({"email": r, "name": r.split("@")[0], "role": "recipient"})
            elif isinstance(r, dict):
                normalised.append(r)

        observations.update({
            "event_type": event_type,
            "recipients": normalised,
            "payload": payload,
            "send_email": send_email_flag,
            "valid": event_type in EVENT_TYPES,
        })

        if not observations["valid"]:
            logger.warning(
                "[NotificationAgent] Unknown event_type '%s'. Valid: %s",
                event_type,
                ", ".join(sorted(EVENT_TYPES)),
            )

        logger.info(
            "[NotificationAgent] Observed event_type=%s recipients=%d",
            event_type,
            len(normalised),
        )
        return observations

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Determine which channels to activate for this event."""
        event_type = observations.get("event_type", "")
        valid = observations.get("valid", False)

        if not valid:
            return AgentDecision(
                action="noop",
                reasoning=f"Unknown event type: {event_type}",
                confidence=0.0,
                context=observations,
            )

        import os
        channels = ["email", "in_app"]
        if os.getenv("SLACK_BOT_TOKEN", ""):
            channels.append("slack")

        return AgentDecision(
            action="dispatch_notification",
            reasoning=f"Dispatching '{event_type}' via {', '.join(channels)}",
            confidence=1.0,
            context=observations,
        )

    # ── EXECUTE ACTION ────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Call the right email template and log in-app notification."""
        if decision.action == "noop":
            return {
                "success": False,
                "status": "skipped",
                "reason": decision.reasoning,
            }

        ctx = decision.context
        event_type: str = ctx.get("event_type", "")
        recipients: List[Dict[str, Any]] = ctx.get("recipients", [])
        payload: Dict[str, Any] = ctx.get("payload", {})
        send_email_flag: bool = ctx.get("send_email", True)

        results: List[Dict[str, Any]] = []
        errors: List[str] = []

        if send_email_flag:
            email_results = await self._dispatch_email(event_type, recipients, payload)
            results.extend(email_results)
            errors.extend([r.get("error") for r in email_results if r.get("error")])

        # In-app logging — use _log_action (no dedicated notification_log table yet)
        in_app_entry = {
            "event_type": event_type,
            "recipients": [r.get("email") for r in recipients],
            "payload_summary": {k: str(v)[:100] for k, v in payload.items()},
            "dispatched_at": datetime.now().isoformat(),
            "channels": ["email" if send_email_flag else None, "in_app"],
        }
        await self._log_action(
            action_type=f"notification_{event_type}",
            input_data={"event_type": event_type, "recipients": len(recipients)},
            output_data=in_app_entry,
            success=len(errors) == 0,
            execution_time_ms=0,
        )

        logger.info(
            "[NotificationAgent] Dispatched event=%s to %d recipient(s). errors=%d",
            event_type,
            len(recipients),
            len(errors),
        )

        return {
            "success": len(errors) == 0,
            "status": "dispatched",
            "event_type": event_type,
            "recipients_count": len(recipients),
            "channels_used": in_app_entry["channels"],
            "email_results": results,
            "errors": errors,
            "dispatched_at": in_app_entry["dispatched_at"],
        }

    async def _dispatch_email(
        self,
        event_type: str,
        recipients: List[Dict[str, Any]],
        payload: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Route to the correct email template function based on event_type.
        Returns a list of send results (one per recipient where applicable).
        """
        try:
            from backend.services.email_service import (
                send_approval_request_email,
                send_approval_decision_email,
                send_payment_notification_email,
                send_low_stock_alert_email,
                send_contract_expiry_alert_email,
                send_email,
            )
        except ImportError as exc:
            logger.error("[NotificationAgent] email_service import error: %s", exc)
            return [{"success": False, "error": str(exc)}]

        results: List[Dict[str, Any]] = []

        if event_type == "approval_requested":
            # One email per approver
            for r in recipients:
                try:
                    res = send_approval_request_email(
                        approver_email=r.get("email", ""),
                        approver_name=r.get("name", "Approver"),
                        pr_data=payload,
                    )
                    results.append(res)
                except Exception as exc:
                    results.append({"success": False, "error": str(exc)})

        elif event_type == "approval_decided":
            decision_val = payload.get("decision", payload.get("status", "approved"))
            approver_name = payload.get("approver_name", "Approver")
            for r in recipients:
                try:
                    res = send_approval_decision_email(
                        requester_email=r.get("email", ""),
                        pr_data=payload,
                        decision=decision_val,
                        approver_name=approver_name,
                    )
                    results.append(res)
                except Exception as exc:
                    results.append({"success": False, "error": str(exc)})

        elif event_type == "payment_scheduled":
            for r in recipients:
                try:
                    res = send_payment_notification_email(
                        finance_email=r.get("email", ""),
                        payment_data=payload,
                    )
                    results.append(res)
                except Exception as exc:
                    results.append({"success": False, "error": str(exc)})

        elif event_type == "low_stock_alert":
            items = payload.get("items", [payload] if payload else [])
            for r in recipients:
                try:
                    res = send_low_stock_alert_email(
                        manager_email=r.get("email", ""),
                        items=items,
                    )
                    results.append(res)
                except Exception as exc:
                    results.append({"success": False, "error": str(exc)})

        elif event_type == "contract_expiry":
            contracts = payload.get("contracts", [payload] if payload else [])
            for r in recipients:
                try:
                    res = send_contract_expiry_alert_email(
                        manager_email=r.get("email", ""),
                        contracts=contracts,
                    )
                    results.append(res)
                except Exception as exc:
                    results.append({"success": False, "error": str(exc)})

        elif event_type == "anomaly_detected":
            # Generic alert email for spend anomalies
            anomaly_desc = payload.get("description", "A spend anomaly has been detected.")
            vendor = payload.get("vendor_name", payload.get("vendor", "N/A"))
            amount = payload.get("amount", 0)
            currency = payload.get("currency", "AED")
            html_body = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#f3f4f6;padding:24px;">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;">
  <div style="background:linear-gradient(135deg,#1e40af,#2563eb);padding:28px 32px;">
    <h1 style="margin:0;color:#fff;font-size:22px;">Procure AI</h1>
    <p style="margin:4px 0 0;color:#bfdbfe;font-size:13px;">Spend Anomaly Detected</p>
  </div>
  <div style="padding:32px;">
    <p style="color:#374151;font-size:15px;">A spend anomaly has been flagged for your review.</p>
    <table width="100%" style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">
      <tr><td style="padding:10px 16px;color:#6b7280;font-size:13px;width:40%;">Vendor</td>
          <td style="padding:10px 16px;color:#111827;font-size:13px;font-weight:700;">{vendor}</td></tr>
      <tr style="background:#fafafa;">
          <td style="padding:10px 16px;color:#6b7280;font-size:13px;">Amount</td>
          <td style="padding:10px 16px;color:#dc2626;font-size:14px;font-weight:700;">{currency} {float(amount):,.2f}</td></tr>
      <tr><td style="padding:10px 16px;color:#6b7280;font-size:13px;">Details</td>
          <td style="padding:10px 16px;color:#374151;font-size:13px;">{anomaly_desc}</td></tr>
    </table>
  </div>
  <div style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:20px 32px;text-align:center;">
    <p style="margin:0;color:#94a3b8;font-size:12px;">This is an automated notification from Procure AI</p>
  </div>
</div>
</body></html>"""
            for r in recipients:
                try:
                    res = send_email(
                        to=r.get("email", ""),
                        subject=f"[Procure AI] Spend Anomaly Detected \u2014 {vendor}",
                        html_body=html_body,
                        text_body=f"Spend Anomaly Detected\n\nVendor: {vendor}\nAmount: {currency} {float(amount):,.2f}\n{anomaly_desc}",
                    )
                    results.append(res)
                except Exception as exc:
                    results.append({"success": False, "error": str(exc)})

        else:
            logger.warning("[NotificationAgent] No email template for event_type=%s", event_type)

        return results

    # ── LEARN ─────────────────────────────────────────────────────────────────

    async def learn(self, result: Dict[str, Any]) -> None:
        """Update delivery stats — track success/failure rates per event type."""
        await super().learn(result)

        status = "success" if result.get("success") else "failure"
        event_type = result.get("event_type", "unknown")
        logger.info(
            "[NotificationAgent] learn — event=%s status=%s recipients=%s",
            event_type,
            status,
            result.get("recipients_count", 0),
        )
        # Future: persist delivery stats to a notification_log table for analytics
