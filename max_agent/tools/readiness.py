"""Execution-readiness tools (Wave C, 60/07 layer 7).

A recommendation is not useful if Oxy cannot execute it through task lists, materials,
contractors, procurement, planned hours, and CBM setup. These tools check that. They return the
standard envelope; they never authorize an action. Safety-critical behaviors (70/04):

- task_list_bom_readiness asserts an object dependency from the BU Table 2 catalog for ABC-4
  equipment, carries the critical-work flag / WO User Status CRW, one-frequency-per-operation,
  and PPE-beyond-minimum. These are real-SAP data dependencies (the SOAR sample does not expose
  the task-list object-dependency / CRW field).
- cbm_measurement_readiness FAILS CLOSED: an add-CBM path needs a real measurement reading
  time-series; measurement-point master data alone is not enough (mirrors oxy_gate_check).
- planned_hours_calibration does not penalize on absent actuals (SOAR AFRU actuals are empty);
  it flags low confidence and routes to SME validation instead.
- Value/cost stays baseline-only; no invented Oxy value.
"""

from __future__ import annotations

from typing import Any, Dict

from ..schemas import STATUS_BLOCKED, STATUS_SUCCESS, STATUS_WARNING, tool_envelope
from .governance import critical_work_catalog_codes

_RAG_RANK = {"GREEN": 0, "YELLOW": 1, "RED": 2, "NOT_REQUIRED": -1, None: 0}


def _status_for(color: str) -> str:
    return {"RED": STATUS_WARNING, "YELLOW": STATUS_WARNING, "GREEN": STATUS_SUCCESS}.get(color, STATUS_SUCCESS)


def task_list_bom_readiness(readiness: Dict[str, Any], criticality: Dict[str, Any], bu_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Task-list / object-dependency / package readiness. ABC-4 requires a Table 2 object dependency."""
    readiness = readiness or {}
    missing = []
    for field in ("work_center", "planned_hours", "number_of_people", "task_duration"):
        if readiness.get(field) in (None, "", 0):
            missing.append(field)

    catalog = critical_work_catalog_codes(bu_profile or {})
    odc = readiness.get("object_dependency_code")
    is_abc4 = criticality.get("code") == "4"
    object_dependency_ok = (not is_abc4) or (odc in catalog)
    if is_abc4 and not object_dependency_ok:
        missing.append("object_dependency_code (Table 2, ABC-4)")

    single_freq_ok = readiness.get("single_frequency_per_operation", True) is True
    if not single_freq_ok:
        missing.append("single_frequency_per_operation")
    ppe_ok = readiness.get("ppe_beyond_minimum_present", True) is True

    color = "GREEN"
    if is_abc4 and not object_dependency_ok:
        color = "RED"
    elif missing or not single_freq_ok:
        color = "YELLOW"

    return tool_envelope(
        tool="task_list_bom_readiness", status=_status_for(color),
        summary=f"Task-list readiness {color}.",
        data={
            "task_list_readiness": color, "missing_fields": missing,
            "object_dependency_ok": object_dependency_ok,
            "critical_work_required_flag": is_abc4, "wo_user_status": "CRW" if is_abc4 else None,
            "single_frequency_per_operation": single_freq_ok, "ppe_beyond_minimum_present": ppe_ok,
            "real_sap_dependency": "object-dependency / CRW field not in SOAR sample; confirm in production",
        },
        confidence="medium",
    )


def materials_component_readiness(readiness: Dict[str, Any]) -> Dict[str, Any]:
    """Spare parts / BOM / material availability and component owner."""
    readiness = readiness or {}
    color = readiness.get("component_readiness", "NOT_REQUIRED")
    blockers = []
    if color == "RED":
        blockers.append("component/material owner or availability missing")
    if not readiness.get("materials"):
        blockers.append("BOM/materials not linked (real-SAP dependency)")
    status = STATUS_WARNING if color == "RED" else STATUS_SUCCESS
    return tool_envelope(
        tool="materials_component_readiness", status=status,
        summary=f"Material/component readiness {color}.",
        data={"material_readiness": color, "blockers": blockers, "materials": readiness.get("materials", [])},
        confidence="medium",
    )


def procurement_readiness(readiness: Dict[str, Any]) -> Dict[str, Any]:
    """PR/PO status and lead-time risk for a required part or service."""
    readiness = readiness or {}
    status_field = readiness.get("procurement_status", "NOT_REQUIRED")
    lead_time = readiness.get("lead_time_days")
    lead_time_risk = "unknown" if lead_time is None else ("high" if lead_time > 60 else "low")
    color = "RED" if status_field == "BLOCKED" else ("YELLOW" if lead_time_risk in ("unknown", "high") and status_field != "NOT_REQUIRED" else "GREEN")
    return tool_envelope(
        tool="procurement_readiness", status=_status_for(color),
        summary=f"Procurement readiness {color}.",
        data={"procurement_readiness": color, "procurement_status": status_field, "lead_time_days": lead_time, "lead_time_risk": lead_time_risk},
        confidence="low" if lead_time is None else "medium",
    )


def contractor_service_readiness(readiness: Dict[str, Any]) -> Dict[str, Any]:
    """Contractor / OEM / inspection-provider readiness. Readiness + dependency + blockers only.

    Reframed from the old demo's free-form supplier selection: this checks whether a service
    dependency exists and an approved provider is identified; it does NOT pick vendors.
    """
    readiness = readiness or {}
    color = readiness.get("contractor_service_readiness", "NOT_REQUIRED")
    blockers = []
    if color == "RED":
        blockers.append("no approved contractor/service source identified")
    return tool_envelope(
        tool="contractor_service_readiness", status=STATUS_WARNING if color == "RED" else STATUS_SUCCESS,
        summary=f"Contractor/service readiness {color}.",
        data={"contractor_readiness": color, "blockers": blockers,
              "note": "readiness/dependency/blocker check only; not free-form vendor selection"},
        confidence="medium",
    )


def planned_hours_calibration(readiness: Dict[str, Any]) -> Dict[str, Any]:
    """Compare planned hours to actuals when available; else route to SME validation (do not penalize)."""
    readiness = readiness or {}
    planned = readiness.get("planned_hours")
    actual = readiness.get("actual_hours")
    if planned is None:
        return tool_envelope(
            tool="planned_hours_calibration", status=STATUS_WARNING,
            summary="Planned hours not available.",
            data={"calibration": "unavailable", "confidence_flag": "LOW", "route": "SME validation"},
            confidence="low",
        )
    if actual in (None, 0):
        # SOAR AFRU actuals are empty - do NOT penalize; flag low confidence and route to SME.
        return tool_envelope(
            tool="planned_hours_calibration", status=STATUS_WARNING,
            summary="Actual hours absent; planned-vs-actual cannot be computed.",
            data={"planned_hours": planned, "actual_hours": actual, "calibration": "not_computable",
                  "confidence_flag": "LOW", "route": "SME validation", "reason": "actuals empty (F1)"},
            confidence="low",
        )
    variance = (actual - planned) / planned if planned else None
    candidate = round(actual, 2) if variance is not None and abs(variance) > 0.25 else None
    return tool_envelope(
        tool="planned_hours_calibration", status=STATUS_SUCCESS,
        summary="Planned-vs-actual computed.",
        data={"planned_hours": planned, "actual_hours": actual, "variance": variance,
              "adjustment_candidate_hours": candidate},
        confidence="medium",
    )


def cbm_measurement_readiness(readiness: Dict[str, Any]) -> Dict[str, Any]:
    """CBM readiness - FAILS CLOSED. Real reading time-series required; point master alone is not enough."""
    readiness = readiness or {}
    real_readings = readiness.get("cbm_real_readings_available") is True
    synthetic = readiness.get("cbm_synthetic_data_flag") is True
    has_points = readiness.get("measurement_points_present", False) or readiness.get("cbm_readiness") not in (None, "NOT_REQUIRED")
    missing = []
    if not real_readings:
        missing.append("measurement reading time-series")
    if not readiness.get("trigger_threshold_present", False):
        missing.append("trigger threshold / limits")

    if real_readings:
        color, status, note = "GREEN", STATUS_SUCCESS, "real readings available"
    elif synthetic:
        color, status, note = "YELLOW", STATUS_WARNING, "synthetic readings only - demo/draft-only"
    else:
        color, status, note = "RED", STATUS_BLOCKED, "no real readings - CBM fails closed (point master alone is insufficient)"

    return tool_envelope(
        tool="cbm_measurement_readiness", status=status,
        summary=f"CBM measurement readiness {color}: {note}.",
        data={"cbm_readiness": color, "real_readings_available": real_readings, "synthetic_flag": synthetic,
              "measurement_points_present": has_points, "missing_measurement_setup": missing, "note": note},
        confidence="high" if real_readings else "low",
    )
