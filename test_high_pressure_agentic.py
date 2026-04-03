"""
High-pressure agentic streaming test harness.

Covers:
- Single-agent queries (budget, risk, vendor, approval)
- Multi-intent orchestration queries
- Mixed random load with configurable concurrency

Usage examples:
  python test_high_pressure_agentic.py
  python test_high_pressure_agentic.py --total 60 --concurrency 10
  python test_high_pressure_agentic.py --base-url http://localhost:5000 --timeout 45
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import statistics
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import requests


@dataclass
class QueryCase:
    name: str
    category: str
    request: str
    pr_data: Dict[str, Any]


@dataclass
class CaseResult:
    name: str
    category: str
    ok: bool
    elapsed_ms: int
    events: int
    final_status: str
    top_agent: str
    error: Optional[str] = None


SINGLE_AGENT_CASES: List[QueryCase] = [
    QueryCase(
        name="budget_it_small",
        category="single",
        request="Check IT budget for 50000 CAPEX",
        pr_data={"department": "IT", "budget": 50000, "budget_category": "CAPEX"},
    ),
    QueryCase(
        name="risk_vendor_medium",
        category="single",
        request="Assess vendor risk for Office Depot, budget 45000, urgency medium",
        pr_data={"vendor_name": "Office Depot", "budget": 45000, "urgency": "Medium"},
    ),
    QueryCase(
        name="vendor_office_supplies",
        category="single",
        request="Recommend best vendor for office supplies budget 30000",
        pr_data={"category": "Office Supplies", "budget": 30000},
    ),
    QueryCase(
        name="approval_route_only",
        category="single",
        request="Route PR-2026-8899 for Finance department amount 75000",
        pr_data={"pr_number": "PR-2026-8899", "department": "Finance", "budget": 75000},
    ),
]


MULTI_INTENT_CASES: List[QueryCase] = [
    QueryCase(
        name="multi_budget_approval",
        category="multi",
        request="Check budget for IT 50000 CAPEX and route for approval",
        pr_data={"department": "IT", "budget": 50000, "budget_category": "CAPEX"},
    ),
    QueryCase(
        name="multi_all_four",
        category="multi",
        request="IT department needs $45 for office supplies from Office Depot - check budget, assess risk, recommend vendor, and route approval",
        pr_data={"department": "IT", "budget": 45, "budget_category": "OPEX", "category": "Office Supplies"},
    ),
    QueryCase(
        name="multi_risk_vendor_approval",
        category="multi",
        request="Assess risk, pick vendor, and route approval for Operations purchase of 90000",
        pr_data={"department": "Operations", "budget": 90000, "category": "Equipment"},
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="High-pressure test for agentic streaming endpoint")
    parser.add_argument("--base-url", default="http://localhost:5000", help="Backend base URL")
    parser.add_argument("--total", type=int, default=30, help="Total requests to send")
    parser.add_argument("--concurrency", type=int, default=6, help="Concurrent worker count")
    parser.add_argument("--timeout", type=int, default=50, help="Per-request timeout seconds")
    parser.add_argument("--output", default="test_high_pressure_agentic_result.json", help="JSON output report path")
    return parser.parse_args()


def choose_case() -> QueryCase:
    # Slight bias toward multi-intent because they are heavier.
    pool = SINGLE_AGENT_CASES + MULTI_INTENT_CASES + MULTI_INTENT_CASES
    return random.choice(pool)


def run_stream_case(case: QueryCase, stream_url: str, timeout_sec: int) -> CaseResult:
    start = time.time()
    events = 0

    try:
        response = requests.post(
            stream_url,
            json={"request": case.request, "pr_data": case.pr_data},
            stream=True,
            timeout=timeout_sec,
            headers={"Accept": "text/event-stream"},
        )
        response.raise_for_status()

        complete_event: Optional[Dict[str, Any]] = None
        seen_error: Optional[str] = None

        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue

            payload = json.loads(line[5:].strip())
            events += 1
            etype = payload.get("type")

            if etype == "error":
                data = payload.get("data", {})
                seen_error = data.get("message") or data.get("error") or "SSE error event"

            if etype == "complete":
                complete_event = payload
                break

        elapsed_ms = int((time.time() - start) * 1000)

        if complete_event is None:
            return CaseResult(
                name=case.name,
                category=case.category,
                ok=False,
                elapsed_ms=elapsed_ms,
                events=events,
                final_status="missing_complete",
                top_agent="?",
                error=seen_error or "No complete event",
            )

        data = complete_event.get("data", {})
        root = data.get("result", {}) if isinstance(data, dict) else {}
        final_status = str(root.get("status", data.get("status", "unknown")))
        top_agent = str(root.get("agent", "?"))

        ok = seen_error is None and final_status in {"success", "completed", "ok"}

        return CaseResult(
            name=case.name,
            category=case.category,
            ok=ok,
            elapsed_ms=elapsed_ms,
            events=events,
            final_status=final_status,
            top_agent=top_agent,
            error=seen_error,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = int((time.time() - start) * 1000)
        return CaseResult(
            name=case.name,
            category=case.category,
            ok=False,
            elapsed_ms=elapsed_ms,
            events=events,
            final_status="exception",
            top_agent="?",
            error=str(exc),
        )


def summarize(results: List[CaseResult]) -> Dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.ok)
    failed = total - passed
    latencies = [r.elapsed_ms for r in results]

    by_category: Dict[str, Dict[str, int]] = {}
    for r in results:
        entry = by_category.setdefault(r.category, {"total": 0, "passed": 0, "failed": 0})
        entry["total"] += 1
        if r.ok:
            entry["passed"] += 1
        else:
            entry["failed"] += 1

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round((passed / total) * 100, 2) if total else 0.0,
        "latency_ms": {
            "min": min(latencies) if latencies else 0,
            "p50": int(statistics.median(latencies)) if latencies else 0,
            "p95": int(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]) if latencies else 0,
            "max": max(latencies) if latencies else 0,
            "avg": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        },
        "by_category": by_category,
    }


def main() -> None:
    args = parse_args()
    stream_url = f"{args.base_url.rstrip('/')}/api/agentic/execute/stream"

    print("=" * 80)
    print("HIGH-PRESSURE AGENTIC STREAM TEST")
    print("=" * 80)
    print(f"Target URL   : {stream_url}")
    print(f"Total        : {args.total}")
    print(f"Concurrency  : {args.concurrency}")
    print(f"Timeout(sec) : {args.timeout}")

    # Basic health precheck
    try:
        h = requests.get(f"{args.base_url.rstrip('/')}/api/health", timeout=5)
        print(f"Health check : {h.status_code}")
        if not h.ok:
            print("Health endpoint not OK. Continuing anyway...")
    except Exception as exc:  # noqa: BLE001
        print(f"Health check failed: {exc}")
        print("Backend may be down. Start backend first, then rerun this script.")

    planned = [choose_case() for _ in range(args.total)]
    results: List[CaseResult] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(run_stream_case, case, stream_url, args.timeout) for case in planned]

        for idx, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            result = fut.result()
            results.append(result)
            status = "PASS" if result.ok else "FAIL"
            print(
                f"[{idx:03}/{args.total}] {status} | {result.category:<6} | {result.name:<28} "
                f"| {result.elapsed_ms:>5}ms | events={result.events:>3} | agent={result.top_agent}"
            )
            if result.error:
                print(f"          error: {result.error}")

    report = summarize(results)
    report["results"] = [asdict(r) for r in results]

    print("\n" + "-" * 80)
    print("SUMMARY")
    print("-" * 80)
    print(
        f"Total={report['total']}  Passed={report['passed']}  Failed={report['failed']}  "
        f"PassRate={report['pass_rate']}%"
    )
    print(
        "Latency(ms): "
        f"min={report['latency_ms']['min']} p50={report['latency_ms']['p50']} "
        f"p95={report['latency_ms']['p95']} max={report['latency_ms']['max']} avg={report['latency_ms']['avg']}"
    )
    print("By category:")
    for cat, stats in report["by_category"].items():
        print(f"  - {cat}: total={stats['total']} passed={stats['passed']} failed={stats['failed']}")

    failures = [r for r in results if not r.ok]
    if failures:
        print("\nTop failures:")
        for r in failures[:10]:
            print(f"  - {r.name} ({r.category}) -> status={r.final_status}, error={r.error}")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nJSON report written: {args.output}")


if __name__ == "__main__":
    main()
