"""Classification tools: ``pm_effectiveness_classifier`` and ``data_readiness_gate``.

``pm_effectiveness_classifier`` implements the rubric, five labels, label precedence,
low-findings guard, mandatory/regulatory carve-out, and missing-evidence handling from
``70 - MAX Agent Build/09 - pm_effectiveness_classifier Specification and Unit Tests``.

Two invariants the classifier must never break (09):
- Mandatory / regulatory / HSE / compliance / criticality-2/3/4 PMs are do-not-optimize:
  they are labelled ``Governance Review Required``, never ``Ineffective``.
- Numeric cut-offs are BU_DEFINED. Until Oxy confirms them, the classifier describes and
  flags but does not pass final judgment - it will not assert ``Effective`` / ``Ineffective``
  against a null threshold.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..config import classifier_thresholds_are_set
from ..schemas import STATUS_SUCCESS, STATUS_WARNING, tool_envelope
from .governance import critical_work_catalog_codes, resolve_pm_requirement

# Labels
LABEL_EFFECTIVE = "Effective"
LABEL_NEEDS_IMPROVEMENT = "Needs Improvement"
LABEL_INEFFECTIVE = "Ineffective"
LABEL_MISSING_EVIDENCE = "Missing Evidence"
LABEL_GOVERNANCE_REVIEW = "Governance Review Required"


def _is_protected(
    pm_governance: Dict[str, Any],
    criticality: Dict[str, Any],
    overrides: Dict[str, Any],
    catalog_codes: set,
) -> Tuple[bool, Optional[str]]:
    """Do-not-optimize carve-out. This is the classifier twin of the gate mandatory-PM block."""
    if pm_governance.get("mandatory_pm") is True:
        return True, "PER_PM_MANDATORY"
    if resolve_pm_requirement(criticality.get("code"), overrides) == "MANDATORY":
        return True, "CRITICALITY_MANDATE"
    odc = pm_governance.get("object_dependency_code")
    if odc and odc in catalog_codes:
        return True, "OBJECT_DEPENDENCY_MANDATE"
    return False, None


def _missing_evidence_reason(
    criticality: Dict[str, Any],
    signals: Dict[str, Any],
    evidence: Dict[str, Any],
    thresholds: Dict[str, Any],
    context: Dict[str, Any],
) -> Optional[str]:
    """Return a reason code when a confident score is not possible, else None (09)."""
    # Unvalidated criticality defers to the gate; do not judge the asset here.
    if criticality.get("code") in (None, "", "0") or criticality.get("validation_status") != "VALIDATED":
        return "CRITICALITY_UNVALIDATED"
    # Primary label-driving signal null.
    if signals.get("failure_after_pm_rate") is None:
        return "FAILURE_SIGNAL_NULL"
    # Confidence below the floor.
    if evidence.get("signal_confidence") == "LOW":
        return "SIGNAL_CONFIDENCE_LOW"
    # Findings coding absent and the label depends on finding/damage/cause coding.
    if evidence.get("notification_coding_present") is False:
        return "NOTIFICATION_CODING_ABSENT"
    # Cost actuals absent and the label depends on cost-per-finding.
    if evidence.get("cost_actuals_present") is False and thresholds.get("cost_per_finding_max") is not None:
        return "COST_ACTUALS_ABSENT"
    # Condition-based PM without a reading time-series (mirrors the gate's fail-closed CBM rule).
    if context.get("pm_strategy_type") == "CONDITION_BASED" and evidence.get("measurement_readings_present") is False:
        return "MEASUREMENT_READINGS_ABSENT"
    return None


def _score_dimensions(signals: Dict[str, Any], thresholds: Dict[str, Any]) -> Tuple[Dict[str, str], bool]:
    """Score the three procedure effectiveness dimensions, applying the low-findings guard."""
    guard_applied = False

    far = signals.get("failure_after_pm_rate")
    mtbf = signals.get("mtbf_trend")
    repeat = signals.get("repeat_failure_rate")
    finding_rate = signals.get("finding_rate")
    variance = signals.get("planned_vs_actual_variance")

    # (i) Failure elimination.
    failure_elimination = "PASS"
    if far is not None and thresholds.get("failure_after_pm_rate_max") is not None and far > thresholds["failure_after_pm_rate_max"]:
        failure_elimination = "FAIL"
    if mtbf == "DECLINING":
        failure_elimination = "FAIL"

    # (ii) Reliability improvement.
    reliability_improvement = "PASS"
    if mtbf == "DECLINING":
        reliability_improvement = "FAIL"
    if repeat is not None and thresholds.get("repeat_failure_rate_max") is not None and repeat > thresholds["repeat_failure_rate_max"]:
        reliability_improvement = "FAIL"

    # (iii) Performance metrics, with the low-findings-is-not-waste guard.
    performance_metrics = "PASS"
    low_floor = thresholds.get("finding_rate_low_floor")
    eff_min = thresholds.get("finding_rate_effective_min")
    if finding_rate is not None and low_floor is not None and finding_rate <= low_floor:
        # A quiet PM that is quietly working is not waste.
        if failure_elimination == "PASS" and reliability_improvement == "PASS":
            performance_metrics = "LOW_FINDINGS_GUARDED"
            guard_applied = True
        else:
            performance_metrics = "FAIL"
    elif finding_rate is not None and eff_min is not None and finding_rate < eff_min:
        performance_metrics = "SOFT_FAIL"

    variance_max = thresholds.get("planned_vs_actual_variance_max")
    if variance is not None and variance_max is not None and variance > variance_max:
        if performance_metrics in ("PASS", "LOW_FINDINGS_GUARDED"):
            performance_metrics = "SOFT_FAIL"

    return {
        "failure_elimination": failure_elimination,
        "reliability_improvement": reliability_improvement,
        "performance_metrics": performance_metrics,
    }, guard_applied


def _needs_improvement(
    attributes: Dict[str, Any],
    signals: Dict[str, Any],
    thresholds: Dict[str, Any],
    dimensions: Dict[str, str],
) -> Tuple[bool, Optional[str]]:
    """One thing off: a failed attribute, variance out of band, or a single soft/failed dimension."""
    for name, value in attributes.items():
        if value is False:
            return True, f"ATTRIBUTE_{name.upper()}_FALSE"
    variance = signals.get("planned_vs_actual_variance")
    variance_max = thresholds.get("planned_vs_actual_variance_max")
    if variance is not None and variance_max is not None and variance > variance_max:
        return True, "PLANNED_VS_ACTUAL_VARIANCE"
    # A single failed effectiveness dimension (both-failed already returned Ineffective upstream).
    if dimensions["failure_elimination"] == "FAIL" or dimensions["reliability_improvement"] == "FAIL":
        return True, "DIMENSION_SOFT_FAIL"
    if dimensions["performance_metrics"] in ("SOFT_FAIL", "FAIL"):
        return True, "PERFORMANCE_METRICS_OUT_OF_BAND"
    return False, None


def pm_effectiveness_classifier(
    context: Dict[str, Any],
    bu_profile: Dict[str, Any],
    criticality: Dict[str, Any],
    pm_governance: Dict[str, Any],
    pm_attributes: Dict[str, Any],
    effectiveness_signals: Dict[str, Any],
    evidence_readiness: Dict[str, Any],
) -> Dict[str, Any]:
    """Assign one of five PM-effectiveness labels. See 09 for the full rubric.

    Label precedence (highest wins): Governance Review Required > Missing Evidence >
    Ineffective > Needs Improvement > Effective.
    """
    overrides = bu_profile.get("criticality_pm_requirement_overrides", {})
    thresholds = bu_profile.get("classifier_thresholds", {}) or {}
    catalog_codes = critical_work_catalog_codes(bu_profile)

    params_used = {
        "pm_id": context.get("pm_id"),
        "time_window": context.get("time_window"),
    }

    def _emit(label: str, summary: str, extra: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {
            LABEL_EFFECTIVE: ["Keep PM"],
            LABEL_NEEDS_IMPROVEMENT: ["Improve task list / frequency / data quality (route through gate)"],
            LABEL_INEFFECTIVE: ["Propose reduce/retire/RTF (still gated by oxy_gate_check)"],
            LABEL_MISSING_EVIDENCE: ["Route to data remediation"],
            LABEL_GOVERNANCE_REVIEW: ["Route to governance/MOC review", "Keep PM"],
        }[label]
        blocked_next = (
            ["Reduce PM", "Retire PM", "Move to RTF"]
            if label in (LABEL_GOVERNANCE_REVIEW, LABEL_MISSING_EVIDENCE)
            else []
        )
        data = {
            "label": label,
            "thresholds_status": thresholds.get("status"),
            "allowed_next_actions": allowed,
            "blocked_next_actions": blocked_next,
        }
        data.update(extra)
        status = STATUS_SUCCESS if label in (LABEL_EFFECTIVE, LABEL_GOVERNANCE_REVIEW) else STATUS_WARNING
        return tool_envelope(
            tool="pm_effectiveness_classifier",
            status=status,
            summary=summary,
            data=data,
            params_used=params_used,
            confidence="high" if label in (LABEL_GOVERNANCE_REVIEW, LABEL_EFFECTIVE) else "medium",
            scope_validated=True,
        )

    # 1. Governance Review Required - highest precedence, overrides every evidence-based label.
    protected, basis = _is_protected(pm_governance, criticality, overrides, catalog_codes)
    if protected:
        return _emit(
            LABEL_GOVERNANCE_REVIEW,
            "Do-not-optimize PM (mandatory / criticality mandate); low finding rate is not treated as waste.",
            {
                "protected": True,
                "protection_basis": basis,
                "low_findings_guard_applied": True,
            },
        )

    # 2. Thresholds unset -> describe-and-flag (must not assert Effective / Ineffective).
    if not classifier_thresholds_are_set(bu_profile):
        return _emit(
            LABEL_MISSING_EVIDENCE,
            "Classifier thresholds are BU_DEFINED (unset); describe-and-flag only, no final judgment.",
            {
                "protected": False,
                "describe_and_flag": True,
                "missing_evidence_reason": "THRESHOLDS_UNSET",
            },
        )

    # 3. Missing Evidence (evidence-based) - precedence over Ineffective.
    me_reason = _missing_evidence_reason(criticality, effectiveness_signals, evidence_readiness, thresholds, context)
    if me_reason:
        return _emit(
            LABEL_MISSING_EVIDENCE,
            f"Insufficient evidence to score ({me_reason}); describe and flag, route to data remediation.",
            {"protected": False, "describe_and_flag": True, "missing_evidence_reason": me_reason},
        )

    # 4. Score dimensions with the low-findings guard.
    dimensions, guard_applied = _score_dimensions(effectiveness_signals, thresholds)

    # 5. Ineffective (non-mandatory) requires genuinely failed effectiveness dimensions.
    if dimensions["failure_elimination"] == "FAIL" and dimensions["reliability_improvement"] == "FAIL":
        return _emit(
            LABEL_INEFFECTIVE,
            "Non-mandatory PM fails failure-elimination and reliability-improvement with sufficient evidence.",
            {"protected": False, "dimension_results": dimensions, "low_findings_guard_applied": guard_applied},
        )

    # 6. Needs Improvement - one thing off.
    ni, ni_reason = _needs_improvement(pm_attributes, effectiveness_signals, thresholds, dimensions)
    if ni:
        return _emit(
            LABEL_NEEDS_IMPROVEMENT,
            f"PM is fundamentally sound but one attribute/dimension is off ({ni_reason}).",
            {"protected": False, "dimension_results": dimensions, "needs_improvement_reason": ni_reason},
        )

    # 7. Effective.
    return _emit(
        LABEL_EFFECTIVE,
        "PM meets the good-PM attributes and effectiveness dimensions at or above thresholds.",
        {"protected": False, "dimension_results": dimensions, "low_findings_guard_applied": guard_applied},
    )


# ---------------------------------------------------------------------------
# data_readiness_gate
# ---------------------------------------------------------------------------

# Required data domains per recommendation type (Data Readiness Scorecard "Minimum gate").
_REQUIRED_DOMAINS = {
    "PM_EFFECTIVENESS_CLASSIFICATION": ["equipment", "pm_plans", "work_orders", "task_lists"],
    "PM_FREQUENCY_CHANGE": ["pm_plans", "work_orders", "notifications_failures", "risk_scorecard", "criticality"],
    "TASK_LIST_CLEANUP": ["task_lists", "work_centers", "planned_hours", "package_assignments"],
    "PARTS_COMPONENT_CHANGE": ["task_lists", "bom_components", "material_availability"],
    "ADD_COMPONENT": ["task_lists", "bom_components", "material_availability"],
    "CONTRACTOR_SERVICE": ["task_list_service", "procurement_service"],
    "CBM": ["measurement_points", "characteristic_unit", "recent_readings"],
    "ADD_CBM": ["measurement_points", "characteristic_unit", "recent_readings"],
    "CBM_CONVERSION": ["measurement_points", "characteristic_unit", "recent_readings"],
    "SAP_PACKAGE_DRAFT": ["current_value", "proposed_value", "evidence", "approver", "gate_status"],
}

_CBM_TYPES = {"CBM", "ADD_CBM", "CBM_CONVERSION"}


def data_readiness_gate(
    recommendation_type: str,
    domain_status: Dict[str, str],
    criticality: Optional[Dict[str, Any]] = None,
    provenance: Optional[str] = None,
) -> Dict[str, Any]:
    """Score required data domains for a recommendation type -> GREEN / YELLOW / RED.

    RED for a strong-data recommendation is a hard block at ``oxy_gate_check``. CBM without a
    reading time-series is RED (fail closed), mirroring the gate.
    """
    required = _REQUIRED_DOMAINS.get(recommendation_type, [])
    per_domain = {d: domain_status.get(d, "MISSING") for d in required}

    red_or_missing = [d for d, s in per_domain.items() if s in (None, "MISSING", "RED")]
    yellow = [d for d, s in per_domain.items() if s == "YELLOW"]

    # CBM fail-closed rule: a reading time-series must be GREEN, not just present.
    cbm_red = recommendation_type in _CBM_TYPES and per_domain.get("recent_readings") != "GREEN"

    if red_or_missing or cbm_red:
        readiness, action, confidence = "RED", "blocked", "low"
    elif yellow:
        readiness, action, confidence = "YELLOW", "down_ranked", "medium"
    else:
        readiness, action, confidence = "GREEN", "allowed", "high"

    status = {"GREEN": STATUS_SUCCESS, "YELLOW": STATUS_WARNING, "RED": STATUS_WARNING}[readiness]
    summary = f"Data readiness {readiness} for {recommendation_type}."
    data = {
        "data_readiness": readiness,
        "action": action,
        "missing_domains": sorted(set(red_or_missing) | ({"recent_readings"} if cbm_red else set())),
        "per_domain": per_domain,
        "provenance": provenance,
    }
    return tool_envelope(
        tool="data_readiness_gate",
        status=status,
        summary=summary,
        data=data,
        params_used={"recommendation_type": recommendation_type},
        confidence=confidence,
        scope_validated=True,
    )
