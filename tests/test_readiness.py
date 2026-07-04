"""Execution-readiness tools (Wave C) - fail-closed and no-penalize behaviors.

These assert the safety-critical properties from 70/04: ABC-4 requires a Table 2 object
dependency (else RED), CBM fails closed without real readings, and planned-hours calibration
does NOT penalize absent AFRU actuals (it flags LOW confidence and routes to SME).
"""

from __future__ import annotations

from max_agent.schemas import STATUS_BLOCKED
from max_agent.tools import (
    cbm_measurement_readiness,
    contractor_service_readiness,
    materials_component_readiness,
    planned_hours_calibration,
    procurement_readiness,
    task_list_bom_readiness,
)

_ABC4 = {"code": "4"}
_ABC2 = {"code": "2"}


def _base_readiness(**over):
    r = {
        "work_center": "MECH01", "planned_hours": 4.0, "number_of_people": 2, "task_duration": 4.0,
        "single_frequency_per_operation": True, "ppe_beyond_minimum_present": True,
    }
    r.update(over)
    return r


# --- task_list_bom_readiness --------------------------------------------------

def test_abc4_requires_table2_object_dependency_else_red(bu_profile):
    # ABC-4 with no object-dependency code fails closed to RED.
    env = task_list_bom_readiness(_base_readiness(), _ABC4, bu_profile)
    assert env["data"]["task_list_readiness"] == "RED"
    assert env["data"]["object_dependency_ok"] is False
    assert env["data"]["critical_work_required_flag"] is True
    assert env["data"]["wo_user_status"] == "CRW"


def test_abc4_with_valid_catalog_code_is_green(bu_profile):
    env = task_list_bom_readiness(_base_readiness(object_dependency_code="PM_REG"), _ABC4, bu_profile)
    assert env["data"]["task_list_readiness"] == "GREEN"
    assert env["data"]["object_dependency_ok"] is True


def test_non_abc4_complete_task_list_is_green(bu_profile):
    env = task_list_bom_readiness(_base_readiness(), _ABC2, bu_profile)
    assert env["data"]["task_list_readiness"] == "GREEN"
    assert env["data"]["critical_work_required_flag"] is False


def test_missing_work_center_is_yellow(bu_profile):
    env = task_list_bom_readiness(_base_readiness(work_center=None), _ABC2, bu_profile)
    assert env["data"]["task_list_readiness"] == "YELLOW"
    assert "work_center" in env["data"]["missing_fields"]


# --- materials_component_readiness --------------------------------------------

def test_materials_red_lists_blocker():
    env = materials_component_readiness({"component_readiness": "RED", "materials": []})
    assert env["data"]["material_readiness"] == "RED"
    assert any("owner" in b or "availability" in b for b in env["data"]["blockers"])


def test_materials_missing_bom_is_flagged_even_when_not_red():
    env = materials_component_readiness({"component_readiness": "NOT_REQUIRED", "materials": []})
    assert any("BOM" in b or "materials" in b for b in env["data"]["blockers"])


# --- procurement_readiness ----------------------------------------------------

def test_procurement_not_required_is_green():
    env = procurement_readiness({"procurement_status": "NOT_REQUIRED"})
    assert env["data"]["procurement_readiness"] == "GREEN"


def test_procurement_blocked_is_red():
    env = procurement_readiness({"procurement_status": "BLOCKED"})
    assert env["data"]["procurement_readiness"] == "RED"


def test_procurement_long_lead_time_is_yellow():
    env = procurement_readiness({"procurement_status": "PR_OPEN", "lead_time_days": 90})
    assert env["data"]["procurement_readiness"] == "YELLOW"
    assert env["data"]["lead_time_risk"] == "high"


# --- contractor_service_readiness ---------------------------------------------

def test_contractor_red_lists_blocker():
    env = contractor_service_readiness({"contractor_service_readiness": "RED"})
    assert env["data"]["contractor_readiness"] == "RED"
    assert env["data"]["blockers"]


def test_contractor_not_required_is_success():
    env = contractor_service_readiness({"contractor_service_readiness": "NOT_REQUIRED"})
    assert env["data"]["contractor_readiness"] == "NOT_REQUIRED"
    assert env["data"]["blockers"] == []


# --- planned_hours_calibration (does NOT penalize absent actuals) -------------

def test_absent_actuals_do_not_penalize_route_to_sme():
    env = planned_hours_calibration({"planned_hours": 4.0, "actual_hours": 0})
    d = env["data"]
    assert d["calibration"] == "not_computable"
    assert d["confidence_flag"] == "LOW"
    assert d["route"] == "SME validation"
    # No RED / blocked status: absent AFRU actuals must not be scored as a failure.
    assert env["status"] != STATUS_BLOCKED


def test_planned_hours_missing_is_unavailable():
    env = planned_hours_calibration({"planned_hours": None})
    assert env["data"]["calibration"] == "unavailable"


def test_planned_vs_actual_computes_variance_when_actuals_present():
    env = planned_hours_calibration({"planned_hours": 4.0, "actual_hours": 6.0})
    assert env["data"]["variance"] == (6.0 - 4.0) / 4.0
    assert env["data"]["adjustment_candidate_hours"] == 6.0  # variance > 0.25


# --- cbm_measurement_readiness (FAILS CLOSED) ---------------------------------

def test_cbm_no_real_readings_fails_closed_red_blocked():
    env = cbm_measurement_readiness({"measurement_points_present": True})
    assert env["data"]["cbm_readiness"] == "RED"
    assert env["status"] == STATUS_BLOCKED  # point master alone is insufficient


def test_cbm_synthetic_only_is_yellow_draft_only():
    env = cbm_measurement_readiness({"cbm_synthetic_data_flag": True})
    assert env["data"]["cbm_readiness"] == "YELLOW"


def test_cbm_real_readings_is_green():
    env = cbm_measurement_readiness({"cbm_real_readings_available": True, "trigger_threshold_present": True})
    assert env["data"]["cbm_readiness"] == "GREEN"
    assert env["data"]["missing_measurement_setup"] == []
