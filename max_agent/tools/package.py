"""Package tool: ``draft_sap_change_package``.

Canonical name per 02 (never ``sap_change_package_drafter``). Draft-only, no write. This tool
assembles the draft package AFTER a gate result exists and enforces the Wave-1 boundaries:

- Never emit a direct-write action. ``max_writes_sap`` is always False.
- Gate BLOCKED -> documentation-only package with remediation, no approval path.
- Gate DRAFT_ONLY -> no approval / submit path.
- Business impact is baseline-only; no projected savings (labor cost actuals are unavailable).
- Synthetic provenance -> synthetic badge on all values.
- Level loading is marked NOT_ASSESSED_WAVE_1; it cannot be used to claim deployment readiness.
- Attachment-K-shaped: the package assembles the Work Strategy Management Worksheet fields where
  a source already exists (see 80 - OXY Current Process/12 - Attachment K Field Map for MAX).
  Every field whose Oxy source is unknown stays deferred / fail-closed / BU_DEFINED - it is never
  fabricated (no invented mandatory tag, MOC threshold, operated/JV field, cost-of-loss, or
  master-data-request field).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import STATUS_BLOCKED, STATUS_SUCCESS, STATUS_WARNING, tool_envelope

LEVEL_LOADING_NOT_ASSESSED = "NOT_ASSESSED_WAVE_1"

# Attachment K / dependent-procedure fields whose Oxy source is not yet confirmed. Static and
# conservative: each carries an explicit posture, never a fabricated value. Maps to the Decision
# Register rows and the Dependent Procedure Request Board.
DEFERRED_FIELDS: List[Dict[str, str]] = [
    {"field": "mandatory_tag_source", "posture": "FAIL_CLOSED",
     "reason": "SAP mandatory / critical-work tag unknown (B2 / C7); protected on the criticality proxy only"},
    {"field": "moc_package", "posture": "REVIEW_REQUIRED",
     "reason": "MOC threshold / evidence / sequence not mapped (C3 / 60.400.304); no invented percentage"},
    {"field": "operated_jv_exemption", "posture": "FAIL_CLOSED",
     "reason": "operated / JV / exemption source field unknown (E1 / 60.400.003)"},
    {"field": "actual_hours_labor_cost_readings", "posture": "BASELINE_ONLY",
     "reason": "actuals / labor cost / measurement readings absent in sample (F1); CBM and variance fail-closed"},
    {"field": "cost_of_loss_probability_of_failure", "posture": "DEFERRED",
     "reason": "production-loss / deferment and probability-of-failure inputs absent (F1 / F2)"},
    {"field": "master_data_request_fields", "posture": "DEFERRED",
     "reason": "MD-request fields / acceptance checks not available (G1 / PGHO-OOG-OOGDMA-00005)"},
    {"field": "level_loading", "posture": "NOT_ASSESSED_WAVE_1",
     "reason": "Stage 7 level loading deferred (E3 / Attachment L)"},
]


def draft_sap_change_package(
    recommendation: Dict[str, Any],
    gate_result: Dict[str, Any],
    evidence: Optional[List[Any]] = None,
    criticality: Optional[Dict[str, Any]] = None,
    readiness: Optional[Dict[str, Any]] = None,
    bu_profile: Optional[Dict[str, Any]] = None,
    current_value: Any = None,
    proposed_value: Any = None,
    provenance: str = "GOVERNED",
    affected_sap_objects: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Assemble the draft SAP change package. Draft-only; MAX never writes SAP."""
    gate_data = gate_result.get("data", {}) if isinstance(gate_result, dict) else {}
    gate_status = gate_data.get("gate_status")
    gate_reason = gate_result.get("blocked_reason") or gate_data.get("review_trigger")

    synthetic = provenance == "SYNTHETIC"
    documentation_only = gate_status == "BLOCKED"

    # Approval / submit paths follow the gate. DRAFT_ONLY and BLOCKED cannot enter approval.
    approval_path_available = gate_status in ("PASS", "REVIEW_REQUIRED")
    submit_path_available = gate_status == "PASS"

    # Emitted actions never include a direct-write / submit-to-SAP action.
    if documentation_only:
        emitted_actions = ["Document only", "Show remediation"]
    elif gate_status == "DRAFT_ONLY":
        emitted_actions = ["Save draft artifact"]
    else:
        emitted_actions = ["Save draft", "Route to human review"]

    package = {
        "package_type": "documentation_only" if documentation_only else "draft_change_package",
        "current_value": _badge(current_value, synthetic),
        "proposed_value": _badge(proposed_value, synthetic),
        "affected_sap_objects": affected_sap_objects or [],
        "evidence": evidence or [],
        "gate_status": gate_status,
        "gate_reason": gate_reason,
        "required_approvers": gate_data.get("required_approvers", []),
        "named_approver": None,  # null until a real approver is named in the workflow
        "approval_path_available": approval_path_available,
        "submit_path_available": submit_path_available,
        "rollback_plan": "Revert to current PM strategy; no SAP object was changed (draft-only).",
        "monitoring_plan": "Track failure-after-PM, corrective burden, and findings at trial review.",
        "level_loading_status": LEVEL_LOADING_NOT_ASSESSED,
        "synthetic_flag": synthetic,
        "business_impact": {
            "basis": "baseline_only",
            "projected_savings": None,  # no realized savings / labor-cost ROI claims
            "note": "Baseline opportunity only; no projected labor savings (labor cost actuals unavailable).",
        },
        "attachment_k": _attachment_k(recommendation, criticality, readiness, bu_profile),
        "deferred_fields": DEFERRED_FIELDS,
        "max_writes_sap": False,  # hard invariant: draft-only, no direct SAP write-back
        "emitted_actions": emitted_actions,
    }

    status = STATUS_BLOCKED if documentation_only else (STATUS_WARNING if gate_status != "PASS" else STATUS_SUCCESS)
    summary = (
        f"Documentation-only package (gate BLOCKED: {gate_reason})."
        if documentation_only
        else f"Draft SAP change package assembled (gate {gate_status}); draft-only, no SAP write."
    )
    return tool_envelope(
        tool="draft_sap_change_package",
        status=status,
        summary=summary,
        data=package,
        evidence=evidence or [],
        confidence="high",
        scope_validated=True,
        blocked_reason=gate_reason if documentation_only else None,
    )


def _badge(value: Any, synthetic: bool) -> Any:
    """Attach a synthetic badge to a value when provenance is synthetic."""
    if value is None:
        return None
    if synthetic:
        return {"value": value, "synthetic": True}
    return {"value": value, "synthetic": False}


def _attachment_k(
    recommendation: Optional[Dict[str, Any]],
    criticality: Optional[Dict[str, Any]],
    readiness: Optional[Dict[str, Any]],
    bu_profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assemble the Attachment K (Work Strategy Management Worksheet) fields from provided inputs.

    Values come from the caller's inputs (validate_scope criticality, the recommendation, and the
    readiness tools) - nothing is invented. Fields whose Oxy source is unknown carry an explicit
    deferred / fail-closed marker (see 80/12 field map and DEFERRED_FIELDS), never a fabricated
    value. The exact p.42 field layout is confirmed with Oxy in Houston (attachment_k_confirmed).
    """
    recommendation = recommendation or {}
    criticality = criticality or {}
    readiness = readiness or {}
    bu_profile = bu_profile or {}
    catalog_codes = {
        item.get("code")
        for item in bu_profile.get("critical_work_code_catalog", [])
        if item.get("code")
    }
    odc = readiness.get("object_dependency_code")
    return {
        # A. Asset identity and criticality (criticality supplied by validate_scope upstream).
        "criticality": {
            "code": criticality.get("code"),
            "validation_status": criticality.get("validation_status"),
        },
        # B. Analysis method and strategy type (from the recommendation).
        "analysis_method": recommendation.get("analysis_method"),
        "strategy_type": recommendation.get("strategy_type"),
        # C. Task list and object dependency. The structure is carried; the mandatory-tag SOURCE
        #    stays BU_DEFINED (B2 / C7) - not invented.
        "object_dependency": {
            "code": odc,
            "critical_work_flag": (odc in catalog_codes) if odc else False,
            "mandatory_tag_source": "BU_DEFINED",
        },
        "task_list": {
            "work_center": readiness.get("work_center"),
            "task_duration": readiness.get("task_duration"),
            "number_of_people": readiness.get("number_of_people"),
            "planned_hours": readiness.get("planned_hours"),
            "single_frequency_per_operation": readiness.get("single_frequency_per_operation"),
            "maintenance_package": readiness.get("maintenance_package"),
        },
        # D. Materials (from materials_component_readiness when available).
        "materials": readiness.get("materials", []),
        # E. Cost / benefit - fail-closed for value (no labor cost, no cost-of-loss, no PoF).
        "cost_benefit": {
            "task_cost_basis": "material_services_partial_only",
            "labor_cost": None,
            "cost_of_loss": None,
            "probability_of_failure": None,
        },
        # F. Final payload and handoff.
        "final_tasks_and_frequencies": "see current_value / proposed_value",
        "moc_linkage": "REVIEW_REQUIRED_ONLY",
        "master_data_request": {
            "status": "STUB",
            "target": "MD Notification to MDC/BPDO",
            "fields": "DEFERRED",
        },
        # The exact Attachment K p.42 layout is confirmed with Oxy in Houston.
        "attachment_k_confirmed": False,
    }
