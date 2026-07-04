"""Recommendation tools: ``pm_strategy_comparator``, ``risk_business_justification``,
``recommend_strategy_change``.

``recommend_strategy_change`` never authorizes an action - every recommendation it forms is
passed to ``oxy_gate_check``. It is specified deterministically (10) because determinism on
the safety rails prevents an unsafe recommendation from ever being formed:

- A do-not-optimize PM (Governance Review Required / mandatory / criticality mandate) is
  never sent toward reduce / retire / RTF on evidence alone; only keep-coverage improvements,
  routed through governance review.
- RED data -> recommend remediation, not a strong change.
- Unvalidated criticality -> governance review, not "low risk".
- Add-CBM only with real readings; else measurement-readiness first.
- Prefer the least-invasive fix (data / task list / component) over a frequency change.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import STATUS_SUCCESS, STATUS_WARNING, tool_envelope
from .governance import criticality_not_validated, mandatory_pm, resolve_pm_requirement


def pm_strategy_comparator(
    current_strategy: Dict[str, Any],
    candidate_strategies: Optional[List[Dict[str, Any]]] = None,
    evidence: Optional[List[Any]] = None,
    bu_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare the current strategy with candidate strategy types (time / condition / risk /
    RTF / design-out / retain). It reports a comparison; it does not authorize a change."""
    candidate_strategies = candidate_strategies or []
    enabled = set((bu_profile or {}).get("enabled_strategy_types", []))
    comparisons = []
    for cand in candidate_strategies:
        st = cand.get("strategy_type")
        comparisons.append(
            {
                "candidate_strategy_type": st,
                "enabled_in_bu_profile": (st in enabled) if enabled else None,
                "rationale": cand.get("rationale"),
            }
        )
    return tool_envelope(
        tool="pm_strategy_comparator",
        status=STATUS_SUCCESS,
        summary="Compared current strategy against candidate strategy types.",
        data={
            "current_strategy": current_strategy,
            "candidate_comparisons": comparisons,
        },
        evidence=evidence or [],
        confidence="medium",
        scope_validated=True,
    )


def risk_business_justification(
    evidence: Optional[List[Any]] = None,
    cost_actuals_present: bool = False,
    material_cost_present: bool = False,
) -> Dict[str, Any]:
    """Convert evidence into qualitative safety / reliability / production / cost rationale.

    Cost-and-value honesty (04): actual labor cost is unavailable for value claims (SOAR Cost
    sheet is 100 percent zero actual labor cost), so this tool never emits a labor-cost or
    labor-savings figure. Material / services cost may be shown only as partial evidence.
    """
    cost_view = "not_available"
    if material_cost_present:
        cost_view = "material_services_partial_only"
    data = {
        "safety_reliability_rationale": "Qualitative; derived from evidence only.",
        "cost_view": cost_view,
        "labor_cost_claim_allowed": False,  # invariant: no labor-cost / labor-savings claim
        "savings_claim_allowed": False,     # baseline-only until F1/F2 close
        "notes": [
            "Actual labor cost is unavailable for value claims (SOAR Cost sheet = 0 labor cost).",
            "Material / services cost is partial evidence only where source rows are populated.",
        ],
    }
    return tool_envelope(
        tool="risk_business_justification",
        status=STATUS_SUCCESS if cost_actuals_present or material_cost_present else STATUS_WARNING,
        summary="Business justification is qualitative plus partial material cost only; no savings claim.",
        data=data,
        evidence=evidence or [],
        confidence="medium",
        scope_validated=True,
    )


# Recommendation output types (fed to oxy_gate_check as recommendation.type where applicable).
REC_REQUEST_CRITICALITY_VALIDATION = "REQUEST_CRITICALITY_VALIDATION"
REC_DATA_REMEDIATION = "DATA_REMEDIATION"
REC_MEASUREMENT_READINESS_FIRST = "MEASUREMENT_READINESS_FIRST"
REC_IMPROVE_TASK_LIST = "IMPROVE_TASK_LIST"
REC_DATA_CLEANUP = "DATA_CLEANUP"
REC_ADD_COMPONENT = "ADD_COMPONENT"
REC_SHORTEN_INTERVAL = "SHORTEN_INTERVAL"
REC_ADD_CBM = "ADD_CBM"
REC_RETAIN_PM = "RETAIN_PM"
REC_REDUCE_OR_RETIRE_CANDIDATE = "REDUCE_OR_RETIRE_CANDIDATE"


def _least_invasive_keep_coverage(readiness: Dict[str, Any], comparison: Dict[str, Any]) -> str:
    """Choose the least-invasive keep-coverage improvement (data -> task list -> component -> shorten)."""
    if readiness.get("data_quality_gap"):
        return REC_DATA_CLEANUP
    if readiness.get("task_list_readiness") in ("YELLOW", "RED") or readiness.get("task_list_gap"):
        return REC_IMPROVE_TASK_LIST
    if readiness.get("component_gap"):
        return REC_ADD_COMPONENT
    return REC_SHORTEN_INTERVAL


def recommend_strategy_change(
    classifier_label: str,
    data_readiness: str,
    risk: Optional[Dict[str, Any]] = None,
    comparison: Optional[Dict[str, Any]] = None,
    criticality: Optional[Dict[str, Any]] = None,
    pm_governance: Optional[Dict[str, Any]] = None,
    readiness: Optional[Dict[str, Any]] = None,
    bu_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Form the main recommendation. Never authorizes; always routes to ``oxy_gate_check``."""
    risk = risk or {}
    comparison = comparison or {}
    criticality = criticality or {}
    pm_governance = pm_governance or {}
    readiness = readiness or {}
    overrides = (bu_profile or {}).get("criticality_pm_requirement_overrides", {})

    mandate = resolve_pm_requirement(criticality.get("code"), overrides) if overrides else "BU_DISCRETION"
    do_not_optimize = (
        classifier_label == "Governance Review Required"
        or mandatory_pm(pm_governance, mandate)
    )

    def _rec(rtype: str, rationale: str, next_action: str, direction: Optional[str] = None) -> Dict[str, Any]:
        return tool_envelope(
            tool="recommend_strategy_change",
            status=STATUS_WARNING if do_not_optimize or data_readiness == "RED" else STATUS_SUCCESS,
            summary=rationale,
            data={
                "recommendation": {
                    "type": rtype,
                    "direction": direction,
                    "rationale": rationale,
                    "next_action": next_action,
                },
                "do_not_optimize": do_not_optimize,
            },
            confidence="high",
            scope_validated=True,
        )

    # 1. Unvalidated criticality -> governance review (do not treat as low risk).
    if criticality_not_validated(criticality):
        return _rec(
            REC_REQUEST_CRITICALITY_VALIDATION,
            "Criticality is unvalidated (0 / blank / stale / conflicting); validate before any strategy change.",
            "Route to governance review",
        )

    # 2. RED data -> remediation, not a strong change.
    if data_readiness == "RED":
        return _rec(
            REC_DATA_REMEDIATION,
            "Data readiness is RED for this recommendation type; remediate data / request evidence first.",
            "Request evidence / remediate data domain",
        )

    # 3. Do-not-optimize -> keep-coverage improvement only, routed through governance review.
    if do_not_optimize:
        improvement = _least_invasive_keep_coverage(readiness, comparison)
        return _rec(
            improvement,
            "Mandatory / criticality-mandated PM: coverage is not reduced on evidence alone; propose a keep-coverage improvement.",
            "Route to governance review (keep-coverage improvement)",
            direction="KEEP_OR_INCREASE",
        )

    # 4. CBM only with real readings.
    if comparison.get("suggests_cbm"):
        if readiness.get("cbm_real_readings_available") is not True:
            return _rec(
                REC_MEASUREMENT_READINESS_FIRST,
                "CBM needs a real measurement reading time-series; establish measurement readiness first.",
                "Establish measurement readings before CBM",
            )
        return _rec(REC_ADD_CBM, "Real readings available; CBM is a candidate.", "Draft CBM package (gated)")

    # 5. Prefer the least-invasive fix over a frequency change.
    least_invasive = _least_invasive_keep_coverage(readiness, comparison)
    if least_invasive != REC_SHORTEN_INTERVAL:
        return _rec(
            least_invasive,
            "A data / task-list / component fix addresses the issue with less risk than a frequency change.",
            "Draft least-invasive improvement (gated)",
        )

    # 6. Fall through to the classifier label.
    if classifier_label == "Ineffective":
        return _rec(
            REC_REDUCE_OR_RETIRE_CANDIDATE,
            "Non-mandatory PM classified Ineffective with sufficient evidence; a reduce/retire is a candidate (still gated).",
            "Draft reduce/retire candidate (gated by oxy_gate_check)",
            direction="EXTEND",
        )
    if classifier_label == "Needs Improvement":
        return _rec(REC_IMPROVE_TASK_LIST, "PM is sound but one thing is off; improve it.", "Draft improvement (gated)")
    if classifier_label == "Missing Evidence":
        return _rec(REC_DATA_REMEDIATION, "Insufficient evidence to score; remediate data.", "Request evidence")
    return _rec(REC_RETAIN_PM, "PM is effective; retain it.", "Keep PM; review on cadence")
