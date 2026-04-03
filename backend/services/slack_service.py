"""
Slack Service — Sprint 9
Sends procurement notifications to Slack and handles approval button callbacks.

Configuration (env vars):
SLACK_BOT_TOKEN      — Bot token (xoxb-...)
SLACK_SIGNING_SECRET — For verifying webhook signatures
SLACK_APPROVAL_CHANNEL — Default channel, e.g. #procurement-approvals
SLACK_FINANCE_CHANNEL  — Finance alerts channel, e.g. #finance-alerts
SLACK_ENABLED        — "true"/"false" (default false)

When SLACK_ENABLED=false: log the message content and return success (demo mode).
"""

import os
import hmac
import hashlib
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ─── Configuration helpers ────────────────────────────────────────────────────

def _is_enabled() -> bool:
    return os.getenv("SLACK_ENABLED", "false").lower() == "true"


def _bot_token() -> str:
    return os.getenv("SLACK_BOT_TOKEN", "")


def _signing_secret() -> str:
    return os.getenv("SLACK_SIGNING_SECRET", "")


def _approval_channel() -> str:
    return os.getenv("SLACK_APPROVAL_CHANNEL", "#procurement-approvals")


def _finance_channel() -> str:
    return os.getenv("SLACK_FINANCE_CHANNEL", "#finance-alerts")


# ─── Core API call ────────────────────────────────────────────────────────────

def _post_to_slack(method: str, body: dict) -> dict:
    """
    POST to https://slack.com/api/<method> using the bot token.
    Returns the parsed JSON response dict.
    """
    token = _bot_token()
    url = f"https://slack.com/api/{method}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                logger.warning("Slack API %s returned ok=false: %s", method, data.get("error"))
            return data
    except httpx.HTTPStatusError as exc:
        logger.error("Slack HTTP error for %s: %s", method, exc)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Slack request failed for %s: %s", method, exc)
        return {"ok": False, "error": str(exc)}


# ─── Demo mode helper ─────────────────────────────────────────────────────────

_DEMO_RESPONSE = {
    "ok": True,
    "mode": "demo",
    "message": "Slack message logged (SLACK_ENABLED=false)",
}


def _demo_log(label: str, payload: dict) -> dict:
    logger.info("[Slack DEMO] %s | payload=%s", label, json.dumps(payload, ensure_ascii=False))
    return _DEMO_RESPONSE.copy()


# ─── Public functions ─────────────────────────────────────────────────────────

def send_message(channel: str, text: str, blocks: Optional[list] = None) -> dict:
    """
    POST to https://slack.com/api/chat.postMessage.

    Returns: {ok, ts, channel, error}
    """
    body: dict = {"channel": channel, "text": text}
    if blocks:
        body["blocks"] = blocks

    if not _is_enabled():
        return _demo_log("send_message", body)

    result = _post_to_slack("chat.postMessage", body)
    return {
        "ok": result.get("ok", False),
        "ts": result.get("ts"),
        "channel": result.get("channel"),
        "error": result.get("error"),
    }


def send_approval_request(pr_data: dict, approver_slack_id: str = "") -> dict:
    """
    Send a rich Block Kit message for a PR approval request.

    pr_data keys used:
      pr_number, description, budget, department, requester,
      priority (low/medium/high), created_date
    """
    pr_number   = pr_data.get("pr_number", "N/A")
    description = pr_data.get("description", "No description")
    budget      = pr_data.get("budget", 0)
    department  = pr_data.get("department", "Unknown")
    requester   = pr_data.get("requester", "Unknown")
    priority    = pr_data.get("priority", "medium").lower()
    created_date = pr_data.get("created_date", "Today")

    # Priority badge
    priority_icons = {"high": "🔴 High", "medium": "🟡 Medium", "low": "🟢 Low"}
    priority_label = priority_icons.get(priority, f"🟡 {priority.capitalize()}")

    # Optional @mention
    mention_text = f" — <@{approver_slack_id}>" if approver_slack_id else ""
    header_text  = f"🔔 New PR Approval Required{mention_text}"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*PR Number:*\n{pr_number}"},
                {"type": "mrkdwn", "text": f"*Amount:*\nAED {budget:,.2f}"},
                {"type": "mrkdwn", "text": f"*Requestor:*\n{requester}"},
                {"type": "mrkdwn", "text": f"*Department:*\n{department}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Description:*\n{description}"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Priority: {priority_label}"},
                {"type": "mrkdwn", "text": f"Created: {created_date}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
                    "style": "primary",
                    "value": pr_number,
                    "action_id": "approve_pr",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                    "style": "danger",
                    "value": pr_number,
                    "action_id": "reject_pr",
                },
            ],
        },
    ]

    channel = _approval_channel()
    fallback_text = f"New approval request for {pr_number} — AED {budget:,.2f} from {department}"

    if not _is_enabled():
        return _demo_log("send_approval_request", {"channel": channel, "blocks": blocks})

    body = {"channel": channel, "text": fallback_text, "blocks": blocks}
    result = _post_to_slack("chat.postMessage", body)
    return {
        "ok": result.get("ok", False),
        "ts": result.get("ts"),
        "channel": result.get("channel"),
        "error": result.get("error"),
    }


def send_payment_alert(payment_data: dict) -> dict:
    """
    Alert the finance channel when a payment run is created.

    payment_data keys used:
      payment_run_number, vendor, amount, scheduled_date, dashboard_url
    """
    run_number     = payment_data.get("payment_run_number", "N/A")
    vendor         = payment_data.get("vendor", "Unknown Vendor")
    amount         = payment_data.get("amount", 0)
    scheduled_date = payment_data.get("scheduled_date", "TBD")
    dashboard_url  = payment_data.get("dashboard_url", "#")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "💳 New Payment Run Created", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Payment Run:*\n{run_number}"},
                {"type": "mrkdwn", "text": f"*Amount:*\nAED {amount:,.2f}"},
                {"type": "mrkdwn", "text": f"*Vendor:*\n{vendor}"},
                {"type": "mrkdwn", "text": f"*Scheduled Date:*\n{scheduled_date}"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📊 View Dashboard", "emoji": True},
                    "url": dashboard_url,
                    "action_id": "view_payment_dashboard",
                }
            ],
        },
    ]

    channel = _finance_channel()
    fallback_text = f"Payment run {run_number} — AED {amount:,.2f} to {vendor} scheduled {scheduled_date}"

    if not _is_enabled():
        return _demo_log("send_payment_alert", {"channel": channel, "blocks": blocks})

    body = {"channel": channel, "text": fallback_text, "blocks": blocks}
    result = _post_to_slack("chat.postMessage", body)
    return {
        "ok": result.get("ok", False),
        "ts": result.get("ts"),
        "channel": result.get("channel"),
        "error": result.get("error"),
    }


def send_anomaly_alert(anomaly: dict) -> dict:
    """
    Alert when a spend anomaly is detected.
    Color-coded attachment: danger=red, warning=yellow, good=green.

    anomaly keys used:
      title, description, severity (danger/warning/good),
      vendor, amount, detected_at, channel (optional override)
    """
    title       = anomaly.get("title", "Spend Anomaly Detected")
    description = anomaly.get("description", "An unusual spend pattern was detected.")
    severity    = anomaly.get("severity", "warning")  # danger | warning | good
    vendor      = anomaly.get("vendor", "Unknown")
    amount      = anomaly.get("amount", 0)
    detected_at = anomaly.get("detected_at", "Now")
    channel     = anomaly.get("channel") or _approval_channel()

    # Severity icon
    severity_icons = {"danger": "🚨", "warning": "⚠️", "good": "✅"}
    icon = severity_icons.get(severity, "⚠️")

    # Slack legacy attachment for color coding (Block Kit doesn't support sidebar color)
    attachments = [
        {
            "color": severity,  # "danger" → red, "warning" → yellow, "good" → green
            "title": f"{icon} {title}",
            "text": description,
            "fields": [
                {"title": "Vendor",      "value": vendor,         "short": True},
                {"title": "Amount (AED)","value": f"{amount:,.2f}", "short": True},
                {"title": "Detected At", "value": detected_at,    "short": True},
                {"title": "Severity",    "value": severity.upper(), "short": True},
            ],
            "footer": "Procure AI — Anomaly Detection",
        }
    ]

    fallback_text = f"{icon} Anomaly: {title} — {vendor} AED {amount:,.2f}"

    if not _is_enabled():
        return _demo_log(
            "send_anomaly_alert",
            {"channel": channel, "attachments": attachments},
        )

    body = {"channel": channel, "text": fallback_text, "attachments": attachments}
    result = _post_to_slack("chat.postMessage", body)
    return {
        "ok": result.get("ok", False),
        "ts": result.get("ts"),
        "channel": result.get("channel"),
        "error": result.get("error"),
    }


def verify_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """
    Verify Slack's request signature using HMAC-SHA256.

    Slack signs requests with: v0:{timestamp}:{body}
    Docs: https://api.slack.com/authentication/verifying-requests-from-slack
    """
    secret = _signing_secret()
    if not secret:
        logger.warning("SLACK_SIGNING_SECRET not set — skipping signature verification")
        return True  # No secret configured; allow (caller should decide policy)

    if not timestamp or not signature:
        logger.warning("Missing Slack timestamp or signature headers")
        return False

    base_string = f"v0:{timestamp}:{request_body.decode('utf-8', errors='replace')}"
    computed = (
        "v0="
        + hmac.new(
            secret.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(computed, signature)


def handle_interactive_payload(payload: dict) -> dict:
    """
    Process button-click callbacks from Slack interactive components.

    - Extracts action_id (approve_pr / reject_pr)
    - Extracts PR number from the button value
    - Returns updated message blocks replacing buttons with a status line
    """
    actions   = payload.get("actions", [])
    user_info = payload.get("user", {})
    username  = user_info.get("username") or user_info.get("name", "unknown")

    if not actions:
        logger.warning("Slack interactive payload has no actions: %s", payload)
        return {"ok": False, "error": "No actions in payload"}

    action    = actions[0]
    action_id = action.get("action_id", "")
    pr_number = action.get("value", "")

    logger.info(
        "[Slack] Interactive action: action_id=%s pr_number=%s user=%s",
        action_id, pr_number, username,
    )

    # Attempt to call the internal approval/rejection endpoint
    _call_approval_endpoint(action_id, pr_number, username)

    # Build updated blocks (replace buttons with status text)
    if action_id == "approve_pr":
        status_text = f"✅ *Approved* by @{username}"
    elif action_id == "reject_pr":
        status_text = f"❌ *Rejected* by @{username}"
    else:
        status_text = f"Action `{action_id}` recorded by @{username}"

    updated_blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*PR {pr_number}* — {status_text}"},
        }
    ]

    # Replace the original message via response_url if present
    response_url = payload.get("response_url")
    if response_url:
        _update_slack_message(response_url, status_text, updated_blocks)

    return {
        "ok": True,
        "action_id": action_id,
        "pr_number": pr_number,
        "actor": username,
        "status_text": status_text,
        "blocks": updated_blocks,
    }


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _call_approval_endpoint(action_id: str, pr_number: str, username: str) -> None:
    """
    Fire-and-forget HTTP call to the internal approval/rejection endpoint.
    Non-fatal — logs errors but does not raise.
    """
    if not pr_number:
        logger.warning("[Slack] Cannot call approval endpoint: pr_number is empty")
        return

    base_url = os.getenv("INTERNAL_API_BASE_URL", "http://localhost:5000")

    if action_id == "approve_pr":
        url    = f"{base_url}/api/agentic/approve/{pr_number}"
        method = "POST"
    elif action_id == "reject_pr":
        url    = f"{base_url}/api/agentic/reject/{pr_number}"
        method = "POST"
    else:
        logger.info("[Slack] Unknown action_id %s — skipping internal call", action_id)
        return

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.request(
                method,
                url,
                json={"actor": username, "source": "slack"},
                headers={"X-Internal-Call": "slack-interactive"},
            )
            logger.info(
                "[Slack] Internal %s %s → %s", method, url, resp.status_code
            )
    except Exception as exc:
        logger.warning("[Slack] Internal call failed (non-fatal): %s", exc)


def _update_slack_message(response_url: str, status_text: str, blocks: list) -> None:
    """
    Update the original Slack message using the response_url from the payload.
    """
    try:
        body = {
            "replace_original": True,
            "text": status_text,
            "blocks": blocks,
        }
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(response_url, json=body)
            logger.info("[Slack] Message update via response_url → %s", resp.status_code)
    except Exception as exc:
        logger.warning("[Slack] response_url update failed (non-fatal): %s", exc)
