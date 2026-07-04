"""Portfolio-health tools (Wave B): pm_portfolio_triage, pm_health_dashboard_metrics.

Find the PMs that need attention first and summarize PM health across the scoped population. These
aggregate deterministic per-asset results; they invent no Oxy value and make no savings claim.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from ..schemas import STATUS_SUCCESS, tool_envelope

# Higher score = higher triage priority.
_GATE_PRIORITY = {"BLOCKED": 40, "DRAFT_ONLY": 20, "REVIEW_REQUIRED": 30, "PASS": 5}
_LABEL_PRIORITY = {"Governance Review Required": 15, "Missing Evidence": 10, "Ineffective": 25, "Needs Improvement": 12, "Effective": 0}


def _priority(row: Dict[str, Any]) -> int:
    score = _GATE_PRIORITY.get(row.get("gate_status"), 0) + _LABEL_PRIORITY.get(row.get("label"), 0)
    if row.get("do_not_optimize"):
        score += 5  # surface do-not-optimize assets so they are not accidentally reduced
    return score


def pm_portfolio_triage(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rank the scoped PM population by attention priority (blocked / governance / review first)."""
    ranked = sorted(rows or [], key=_priority, reverse=True)
    queue = [
        {
            "rank": i + 1, "equipment_id": r.get("equipment_id"), "criticality": r.get("criticality"),
            "label": r.get("label"), "gate_status": r.get("gate_status"), "reason": r.get("gate_reason"),
            "do_not_optimize": r.get("do_not_optimize"), "priority_score": _priority(r),
        }
        for i, r in enumerate(ranked)
    ]
    return tool_envelope(
        tool="pm_portfolio_triage", status=STATUS_SUCCESS,
        summary=f"Triaged {len(queue)} PMs; {sum(1 for q in queue if q['gate_status'] == 'BLOCKED')} blocked.",
        data={"queue": queue, "population_count": len(queue)}, confidence="medium",
    )


def pm_health_dashboard_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate PM-health distribution across the scoped population for the PM Health artifact."""
    rows = rows or []
    gate = Counter(r.get("gate_status") for r in rows)
    labels = Counter(r.get("label") for r in rows)
    crit = Counter(str(r.get("criticality")) for r in rows)
    provenance = Counter(r.get("provenance") for r in rows)
    return tool_envelope(
        tool="pm_health_dashboard_metrics", status=STATUS_SUCCESS,
        summary=f"{len(rows)} PMs; {gate.get('BLOCKED', 0)} blocked, {gate.get('REVIEW_REQUIRED', 0)} review-required.",
        data={
            "population_count": len(rows),
            "by_gate_status": dict(gate), "by_label": dict(labels), "by_criticality": dict(crit),
            "do_not_optimize_count": sum(1 for r in rows if r.get("do_not_optimize")),
            "blocked_count": gate.get("BLOCKED", 0),
            "provenance": dict(provenance),
            "value_note": "counts only; no realized-savings or effectiveness score implied (thresholds null / value baseline-only)",
        },
        confidence="medium",
    )
