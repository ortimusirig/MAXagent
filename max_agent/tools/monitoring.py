"""Monitoring / value tools (Wave D): trial_monitor, value_kpi_tracker.

value_kpi_tracker is BASELINE-ONLY for savings: it never claims avoided labor hours, avoided cost,
or realized value from drafts, synthetic data, or unapproved packages (labor cost is 0 in the SOAR
sample). trial_monitor decides continue/stop/permanent deterministically from trial evidence.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..schemas import STATUS_SUCCESS, STATUS_WARNING, tool_envelope


def trial_monitor(trial: Dict[str, Any]) -> Dict[str, Any]:
    """Track a temporary trial and recommend continue / stop / make-permanent from evidence only."""
    trial = trial or {}
    cycles = trial.get("cycles_completed", 0)
    target_cycles = trial.get("target_cycles", 3)
    failures = trial.get("failures_after_pm", 0)
    corrective = trial.get("corrective_work_orders", 0)
    new_findings = trial.get("new_findings", 0)

    if failures > 0:
        decision, reason = "STOP", "failure(s) after PM during the trial; revert to prior strategy"
    elif cycles < target_cycles:
        decision, reason = "CONTINUE", f"trial in progress ({cycles}/{target_cycles} cycles)"
    else:
        decision, reason = "MAKE_PERMANENT_CANDIDATE", "trial complete with no failures; candidate for permanent (still gated + human-approved)"

    return tool_envelope(
        tool="trial_monitor", status=STATUS_WARNING if decision == "STOP" else STATUS_SUCCESS,
        summary=f"Trial {decision}: {reason}.",
        data={"decision": decision, "reason": reason, "cycles_completed": cycles, "target_cycles": target_cycles,
              "failures_after_pm": failures, "corrective_work_orders": corrective, "new_findings": new_findings,
              "note": "trial outcome is evidence for a human decision; MAX does not auto-make-permanent"},
        confidence="medium",
    )


# The eight core KPIs (60/07). Savings-oriented KPIs stay baseline-only until F1/F2 close.
_KPI_DEFS = [
    ("pms_classified", "count", "computable"),
    ("low_value_pm_reduction", "count of approved reductions", "baseline_only"),
    ("first_time_right_pms", "count", "baseline_only"),
    ("frequency_changes_approved", "count", "computable"),
    ("avoided_work_hours", "hours", "not_computable_labor_actuals_absent"),
    ("failure_after_pm_rate", "rate", "computable_partial"),
    ("data_readiness_improvement", "RAG movement", "computable"),
    ("planner_adoption", "reviewer actions", "computable"),
]


def value_kpi_tracker(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Baseline-only benefits tracker across the scoped population. No realized-savings claim."""
    rows = rows or []
    classified = sum(1 for r in rows if r.get("label") not in (None, "Not classified (out of analysis scope)"))
    kpis = []
    for name, unit, basis in _KPI_DEFS:
        value = None
        if name == "pms_classified":
            value = classified
        kpis.append({
            "kpi": name, "unit": unit, "basis": basis, "value": value,
            "cadence": "weekly during pilot",
            "savings_claim_allowed": False,
        })
    return tool_envelope(
        tool="value_kpi_tracker", status=STATUS_SUCCESS,
        summary=f"{len(kpis)} KPIs, baseline-only (no realized-savings claim).",
        data={"kpis": kpis, "population_count": len(rows),
              "value_note": "labor cost is 0 in the sample (F1); avoided hours/cost are not computable and are not claimed"},
        confidence="medium",
    )
