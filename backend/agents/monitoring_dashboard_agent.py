"""
MonitoringDashboardAgent — WF-20 / Phase 4
===========================================
System KPI & Health Monitoring.

Workflows covered
-----------------
WF-20  Procurement System Health & KPI Dashboard (Phase 4)
       Aggregates operational KPIs from multiple adapter sources, computes a
       composite health score (0–100), and raises alerts when key thresholds
       are breached.

Business value
--------------
- Single pane of glass for procurement system health
- Proactive alerting before problems escalate (holds piling up, approvals
  stalling, invoice overdue spikes)
- Agent success-rate tracking surfaces automation breakdowns early
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from backend.agents import AgentDecision, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)

# ── Alert thresholds ──────────────────────────────────────────────────────────
_THRESHOLD_HOLDS_WARN        = 5    # invoice holds count
_THRESHOLD_APPROVALS_WARN    = 10   # pending approvals count
_THRESHOLD_OVERDUE_INV_WARN  = 3    # overdue invoices count
_THRESHOLD_FAILURE_RATE_WARN = 0.20  # agent action failure rate (20%)

# Health score deductions per threshold breach
_DEDUCTION_HOLDS             = 15
_DEDUCTION_APPROVALS         = 10
_DEDUCTION_OVERDUE           = 15
_DEDUCTION_FAILURE_RATE      = 20
_DEDUCTION_PAYMENT_FAILURES  = 10


class MonitoringDashboardAgent(BaseAgent):
    """
    Collects system-wide KPIs and computes a procurement health score.

    Observe  → Query adapter for: payment proposals (pipeline), pending
               approvals, active invoice holds, vendor invoices (overdue),
               and agent_actions (success rate last 24 h).
    Decide   → Compute health_score (0–100), flag threshold breaches.
    Act      → Return dashboard_kpis with health_score, active_holds,
               pending_approvals, payment_pipeline_status, overdue_invoices,
               agent_success_rate, and alerts list.
    Learn    → Log health score and alert count.
    """

    def __init__(self) -> None:
        super().__init__(
            name="MonitoringDashboardAgent",
            description=(
                "Computes a live procurement health score (0–100) by aggregating "
                "KPIs from payment runs, invoice holds, pending approvals, overdue "
                "invoices, and agent action success rates."
            ),
            temperature=0.1,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)

    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.status = AgentStatus.OBSERVING

        payment_proposals: List[Dict[str, Any]] = []
        pending_approvals: List[Dict[str, Any]] = []
        active_holds: List[Dict[str, Any]] = []
        vendor_invoices: List[Dict[str, Any]] = []
        agent_actions: List[Dict[str, Any]] = []

        try:
            from backend.services.adapters.factory import get_adapter
            adapter = get_adapter()

            try:
                payment_proposals = adapter.get_payment_proposals(limit=200)
            except Exception as exc:
                logger.warning("[MonitoringDashboardAgent] payment_proposals failed: %s", exc)

            try:
                pending_approvals = adapter.get_pending_approvals(status="pending")
            except Exception as exc:
                logger.warning("[MonitoringDashboardAgent] pending_approvals failed: %s", exc)

            try:
                active_holds = adapter.get_active_holds()
            except Exception as exc:
                logger.warning("[MonitoringDashboardAgent] active_holds failed: %s", exc)

            try:
                vendor_invoices = adapter.get_vendor_invoices(limit=200)
            except Exception as exc:
                logger.warning("[MonitoringDashboardAgent] vendor_invoices failed: %s", exc)

        except Exception as exc:
            logger.warning("[MonitoringDashboardAgent] Adapter init failed: %s", exc)

        # Agent actions: query directly via nmi_data_service (neutral table)
        try:
            agent_actions = self._load_recent_agent_actions(hours=24)
        except Exception as exc:
            logger.warning("[MonitoringDashboardAgent] agent_actions query failed: %s", exc)

        logger.info(
            "[MonitoringDashboardAgent] Loaded: proposals=%d  approvals=%d  "
            "holds=%d  invoices=%d  actions=%d",
            len(payment_proposals), len(pending_approvals),
            len(active_holds), len(vendor_invoices), len(agent_actions),
        )

        return {
            "payment_proposals": payment_proposals,
            "pending_approvals": pending_approvals,
            "active_holds": active_holds,
            "vendor_invoices": vendor_invoices,
            "agent_actions": agent_actions,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "input_context": context,
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        self.status = AgentStatus.THINKING

        payment_proposals: List[Dict[str, Any]] = observations.get("payment_proposals", [])
        pending_approvals: List[Dict[str, Any]] = observations.get("pending_approvals", [])
        active_holds: List[Dict[str, Any]]       = observations.get("active_holds", [])
        vendor_invoices: List[Dict[str, Any]]    = observations.get("vendor_invoices", [])
        agent_actions: List[Dict[str, Any]]      = observations.get("agent_actions", [])

        # ── KPI: payment pipeline ──────────────────────────────────────────────
        payment_run_count    = len(payment_proposals)
        payment_run_failed   = sum(
            1 for p in payment_proposals
            if str(p.get("status") or p.get("state") or "").lower() in ("failed", "error", "rejected")
        )
        payment_run_success  = payment_run_count - payment_run_failed
        payment_failure_rate = (
            payment_run_failed / payment_run_count if payment_run_count > 0 else 0.0
        )
        payment_pipeline_status = (
            "healthy" if payment_failure_rate < 0.1
            else "degraded" if payment_failure_rate < 0.3
            else "critical"
        )

        # ── KPI: invoice holds ─────────────────────────────────────────────────
        holds_count = len(active_holds)

        # ── KPI: pending approvals ─────────────────────────────────────────────
        approvals_count = len(pending_approvals)

        # ── KPI: overdue invoices ──────────────────────────────────────────────
        today = datetime.now(timezone.utc).date()
        overdue_count = 0
        for inv in vendor_invoices:
            due_raw = inv.get("due_date") or inv.get("payment_due") or inv.get("duedate")
            if due_raw:
                try:
                    due_date = datetime.fromisoformat(str(due_raw)[:10]).date()
                    if due_date < today:
                        overdue_count += 1
                except (ValueError, TypeError):
                    pass

        # ── KPI: agent success rate ────────────────────────────────────────────
        total_actions = len(agent_actions)
        failed_actions = sum(
            1 for a in agent_actions
            if not bool(a.get("success", True))
        )
        success_rate = (
            (total_actions - failed_actions) / total_actions
            if total_actions > 0
            else 1.0
        )
        failure_rate = 1.0 - success_rate

        # ── Health score computation ───────────────────────────────────────────
        health_score = 100
        alerts: List[Dict[str, Any]] = []

        if holds_count > _THRESHOLD_HOLDS_WARN:
            health_score -= _DEDUCTION_HOLDS
            alerts.append({
                "type": "invoice_holds",
                "severity": "warning",
                "message": f"{holds_count} active invoice holds (threshold: {_THRESHOLD_HOLDS_WARN}). Review required.",
                "count": holds_count,
            })

        if approvals_count > _THRESHOLD_APPROVALS_WARN:
            health_score -= _DEDUCTION_APPROVALS
            alerts.append({
                "type": "pending_approvals",
                "severity": "warning",
                "message": f"Approval queue backlog: {approvals_count} pending (threshold: {_THRESHOLD_APPROVALS_WARN}).",
                "count": approvals_count,
            })

        if overdue_count > _THRESHOLD_OVERDUE_INV_WARN:
            health_score -= _DEDUCTION_OVERDUE
            alerts.append({
                "type": "overdue_invoices",
                "severity": "warning" if overdue_count <= 10 else "critical",
                "message": f"{overdue_count} overdue invoices (threshold: {_THRESHOLD_OVERDUE_INV_WARN}).",
                "count": overdue_count,
            })

        if failure_rate > _THRESHOLD_FAILURE_RATE_WARN:
            health_score -= _DEDUCTION_FAILURE_RATE
            alerts.append({
                "type": "agent_failures",
                "severity": "critical" if failure_rate > 0.4 else "warning",
                "message": (
                    f"Agent action failure rate {failure_rate * 100:.1f}% in last 24 h "
                    f"(threshold: {_THRESHOLD_FAILURE_RATE_WARN * 100:.0f}%)."
                ),
                "failure_rate": round(failure_rate, 3),
            })

        if payment_failure_rate > _THRESHOLD_FAILURE_RATE_WARN:
            health_score -= _DEDUCTION_PAYMENT_FAILURES
            alerts.append({
                "type": "payment_failures",
                "severity": "warning",
                "message": (
                    f"Payment run failure rate {payment_failure_rate * 100:.1f}% "
                    f"({payment_run_failed}/{payment_run_count} runs failed)."
                ),
                "failure_rate": round(payment_failure_rate, 3),
            })

        health_score = max(health_score, 0)

        reasoning = (
            f"Health score {health_score}/100. "
            f"Holds={holds_count}  Approvals={approvals_count}  "
            f"Overdue_inv={overdue_count}  AgentFailRate={failure_rate*100:.1f}%  "
            f"Alerts={len(alerts)}."
        )

        return AgentDecision(
            action="compute_dashboard_kpis",
            reasoning=reasoning,
            confidence=0.93,
            context={
                **observations,
                "health_score": health_score,
                "holds_count": holds_count,
                "approvals_count": approvals_count,
                "overdue_count": overdue_count,
                "agent_success_rate": round(success_rate * 100, 1),
                "payment_pipeline_status": payment_pipeline_status,
                "payment_run_count": payment_run_count,
                "payment_run_failed": payment_run_failed,
                "total_agent_actions_24h": total_actions,
                "alerts": alerts,
            },
        )

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        self.status = AgentStatus.ACTING

        ctx = decision.context
        health_score = ctx.get("health_score", 0)

        health_label = (
            "critical" if health_score < 50
            else "degraded" if health_score < 75
            else "good" if health_score < 90
            else "excellent"
        )

        result: Dict[str, Any] = {
            "success": True,
            "agent": self.name,
            "action": decision.action,
            "as_of": ctx.get("as_of", datetime.now().isoformat()),
            "dashboard_kpis": {
                "health_score": health_score,
                "health_label": health_label,
                "active_holds": ctx.get("holds_count", 0),
                "pending_approvals": ctx.get("approvals_count", 0),
                "overdue_invoices": ctx.get("overdue_count", 0),
                "agent_success_rate_pct": ctx.get("agent_success_rate", 100.0),
                "agent_actions_last_24h": ctx.get("total_agent_actions_24h", 0),
                "payment_pipeline_status": ctx.get("payment_pipeline_status", "unknown"),
                "payment_run_total": ctx.get("payment_run_count", 0),
                "payment_run_failed": ctx.get("payment_run_failed", 0),
            },
            "alerts": ctx.get("alerts", []),
            "alert_count": len(ctx.get("alerts", [])),
            "timestamp": datetime.now().isoformat(),
        }

        result["message"] = (
            f"System health: {health_label.upper()} ({health_score}/100). "
            f"{len(ctx.get('alerts', []))} alert(s) active."
        )

        await self._log_action(
            action_type="dashboard_health_check",
            input_data=ctx.get("input_context", {}),
            output_data=result,
            success=True,
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        result = learn_context.get("result", {})
        kpis = result.get("dashboard_kpis", {})
        logger.info(
            "[MonitoringDashboardAgent] Learned: health=%d (%s)  alerts=%d",
            kpis.get("health_score", 0),
            kpis.get("health_label", "?"),
            result.get("alert_count", 0),
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _load_recent_agent_actions(hours: int = 24) -> List[Dict[str, Any]]:
        """
        Load agent_actions rows from the last N hours using the shared DB pool.
        Returns an empty list on any failure — the caller handles the miss.
        """
        try:
            from backend.services.db_pool import get_db_connection, return_db_connection
            from psycopg2.extras import RealDictCursor

            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            conn = get_db_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT agent_name, action_type, success, execution_time_ms, created_at
                        FROM agent_actions
                        WHERE created_at >= %s
                        ORDER BY created_at DESC
                        LIMIT 1000
                        """,
                        (cutoff,),
                    )
                    rows = cur.fetchall()
                return [dict(r) for r in rows]
            finally:
                return_db_connection(conn)
        except Exception as exc:
            logger.warning("[MonitoringDashboardAgent] _load_recent_agent_actions: %s", exc)
            return []


# ── Standalone entry point ─────────────────────────────────────────────────────

async def get_system_health(params: Dict[str, Any]) -> Dict[str, Any]:
    """Standalone async function — call from orchestrator or API route."""
    agent = MonitoringDashboardAgent()
    return await agent.execute(params)
