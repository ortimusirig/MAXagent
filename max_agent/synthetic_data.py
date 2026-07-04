"""Oxy-like SYNTHETIC preventive-maintenance fleet.

Every record here is MANUFACTURED and clearly flagged synthetic (`synthetic_data_flag = True`,
`provenance = SYNTHETIC`). It exists so the MAX Agent app runs end-to-end with NO Databricks
connection, per the synthetic-first build posture (70/03). It invents NO Oxy policy value - the
BU profile thresholds stay null and the gate/classifier behave fail-closed.

The fleet is hand-authored (no RNG) so the demo is deterministic and each governance outcome is
reproducible. It is designed to exercise every gate status - PASS, REVIEW_REQUIRED, BLOCKED,
DRAFT_ONLY - plus the scope fail-closed paths (non-operated/JV, exempt), mirroring the real SOAR
sample shape: rotating-only, labor cost 0, measurement readings absent, mandatory-PM tag absent.

Cutover to real Oxy data replaces this module with governed Databricks views (see views.sql);
nothing downstream changes because the tools read the same record shape.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

# Rotating-only sample (Equipment_Category = R), matching the SOAR profiling.
_EQUIPMENT_CATEGORY = "R"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _base(equipment_id: str, **overrides: Any) -> Dict[str, Any]:
    """A healthy, in-scope, criticality-1 rotating asset (resolves to PASS by default)."""
    base = {
        "equipment_id": equipment_id,
        "functional_location_id": f"FLOC-{equipment_id}",
        "plant": "HOUSTON",
        "business_unit": "BU1",
        "asset_class": "CENTRIFUGAL_PUMP",
        "pm_id": f"PM-{equipment_id}",
        "equipment_category": _EQUIPMENT_CATEGORY,
        "user_question": "Is this PM effective, and should anything change?",
        # --- validate_scope inputs (BU policy vs per-asset master-data state) ---
        "master_data": {
            "asset_resolved": True,
            "pm_population_count": 1,
            "operated_status": "OPERATED",
            "exemption_status": "NONE",
            "exemption_id": None,
            "criticality": {
                "code": "1", "label": "Non-critical", "validation_status": "VALIDATED",
                "source": "SAP (synthetic)", "stale": False, "equipment_floc_conflict": False,
            },
            "synthetic_data_flag": True,
        },
        # --- classifier inputs ---
        "pm_governance": {"mandatory_pm": False, "mandatory_basis": None, "object_dependency_code": None},
        "pm_attributes": {
            "failure_mode_justified": True, "right_asset_criticality": True, "right_strategy_type": True,
            "right_frequency": True, "task_list_complete": True, "parts_staged": True,
            "planned_hours_realistic": True, "findings_captured": True, "value_evidence_present": True,
        },
        "effectiveness_signals": {
            "failure_after_pm_rate": 0.04, "pm_to_follow_on_corrective_linkage": "PRESENT",
            "mtbf_trend": "IMPROVING", "mttr_trend": "FLAT", "repeat_failure_rate": 0.02,
            "finding_rate": 0.06, "pm_to_corrective_ratio": 3.5, "cost_per_finding": None,
            "planned_vs_actual_variance": 0.12,
        },
        "evidence_readiness": {
            "notification_coding_present": True, "cost_actuals_present": False,
            "measurement_readings_present": False, "signal_confidence": "MEDIUM",
        },
        # --- gate readiness (execution + task-list / Attachment-K carriers) ---
        "readiness": {
            "data_readiness": "GREEN", "evidence_sufficiency": "SUFFICIENT", "task_list_readiness": "GREEN",
            "component_readiness": "NOT_REQUIRED", "contractor_service_readiness": "NOT_REQUIRED",
            "cbm_readiness": "NOT_REQUIRED", "cbm_real_readings_available": False, "cbm_synthetic_data_flag": False,
            "object_dependency_readiness": "GREEN", "object_dependency_code": "PM_MCW",
            "acceptance_criteria_result": "PASSED", "follow_on_crmn_expected": False, "follow_on_crmn_created": False,
            "level_loading_status": "COMPLETE", "practicality_status": "COMPLETE",
            "work_center": "MECH01", "planned_hours": 4.0, "number_of_people": 2, "task_duration": 4.0,
            "single_frequency_per_operation": True, "maintenance_package": "ST_MON",
            # execution-readiness carriers (Wave C tools); actuals empty like the SOAR sample
            "actual_hours": 0.0, "materials": [], "ppe_beyond_minimum_present": True,
            "procurement_status": "NOT_REQUIRED", "lead_time_days": None,
            "measurement_points_present": False, "trigger_threshold_present": False,
        },
        "risk": {"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
        "approval": {
            "user_champion_named": True, "work_strategy_owner_named": True,
            "maintenance_manager_required": False, "maintenance_manager_named": False,
            "compliance_safety_named": False, "sap_pm_owner_required": False, "sap_pm_owner_named": False,
        },
        "approval_state": {"peer_review_complete": True},
        # --- strategy + recommendation context ---
        "current_strategy": {"strategy_type": "TIME_BASED", "cycle": "MONTHLY", "analysis_method": "EXISTING_STRATEGY"},
        "candidate_strategies": [{"strategy_type": "CONDITION_BASED", "rationale": "vibration-based candidate"}],
        "comparison": {},
        "data_domain_status": {
            "equipment": "GREEN", "pm_plans": "GREEN", "work_orders": "GREEN", "task_lists": "GREEN",
            "notifications_failures": "YELLOW", "risk_scorecard": "GREEN", "criticality": "GREEN",
        },
        # The change under consideration for this asset's scenario (drives the gate).
        "proposed_recommendation": {
            "type": "RETAIN_PM", "direction": None, "strategy_type": "TIME_BASED", "analysis_method": "PMO",
        },
        "current_value": "Monthly time-based PM",
        "proposed_value": "Monthly time-based PM (retain)",
        "requested_action": "DRAFT_PACKAGE",
        # --- evidence-tab narrative (synthetic) ---
        "wo_history": {"preventive": 10, "corrective": 3, "reactive": 1},
        "cost": {"labor_cost": 0.0, "material_cost": 1200.0, "basis": "material_services_partial_only"},
        "findings": {"damage_coded_pct": 0.56, "cause_coded_pct": 0.51},
        "expected_gate_status": "PASS",
    }
    return _merge(base, overrides)


def synthetic_fleet() -> List[Dict[str, Any]]:
    """Deterministic synthetic fleet covering every governance outcome."""
    return [
        # 1. PASS - criticality-1 retain PM, green evidence.
        _base("PUMP-4102"),

        # 2. REVIEW_REQUIRED - criticality-2 shorten-frequency trial; risk scorecard review.
        _base(
            "PUMP-4110",
            user_question="Should we shorten this high-value pump's PM interval?",
            master_data={"criticality": {"code": "2", "label": "High-value non-critical"}},
            readiness={"data_readiness": "YELLOW", "task_list_readiness": "YELLOW"},
            risk={"risk_result": "REVIEW", "risk_threshold_met": True},
            proposed_recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "SHORTEN"},
            current_value="Quarterly PM", proposed_value="Monthly PM (trial)",
            trial={"cycles_completed": 2, "target_cycles": 3, "failures_after_pm": 0, "corrective_work_orders": 1, "new_findings": 2},
            expected_gate_status="REVIEW_REQUIRED",
        ),

        # 3. BLOCKED - criticality-3 (mandatory coverage) proposed frequency EXTEND (reduce coverage).
        _base(
            "COMP-2201", asset_class="RECIP_COMPRESSOR",
            user_question="Can we extend this critical compressor's PM to save hours?",
            master_data={"criticality": {"code": "3", "label": "Critical"}},
            proposed_recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "EXTEND"},
            current_value="Monthly PM", proposed_value="Quarterly PM (extend)",
            expected_gate_status="BLOCKED",
        ),

        # 4. BLOCKED - criticality-4 HSE retire PM (mandatory / HSE).
        _base(
            "VALVE-3301", asset_class="ESD_VALVE",
            user_question="This safety valve PM rarely finds anything - can we retire it?",
            master_data={"criticality": {"code": "4", "label": "HSE critical"}},
            pm_governance={"mandatory_pm": True, "mandatory_basis": "PM_HSE"},
            proposed_recommendation={"type": "RETIRE_PM"},
            current_value="Annual function test", proposed_value="Retire PM",
            expected_gate_status="BLOCKED",
        ),

        # 5. BLOCKED - add CBM without real measurement readings.
        _base(
            "PUMP-4115",
            user_question="Can we move this pump to condition-based monitoring?",
            master_data={"criticality": {"code": "2", "label": "High-value non-critical"}},
            readiness={"cbm_readiness": "RED", "cbm_real_readings_available": False, "cbm_synthetic_data_flag": False},
            proposed_recommendation={"type": "ADD_CBM", "strategy_type": "CONDITION_BASED"},
            current_value="Monthly time-based PM", proposed_value="Condition-based (vibration)",
            expected_gate_status="BLOCKED",
        ),

        # 6. DRAFT_ONLY - synthetic-flagged CBM demo (draft-only path).
        _base(
            "PUMP-4116",
            user_question="Show the CBM path on synthetic readings.",
            master_data={"criticality": {"code": "1", "label": "Non-critical"}},
            readiness={"cbm_readiness": "YELLOW", "cbm_real_readings_available": False, "cbm_synthetic_data_flag": True},
            proposed_recommendation={"type": "ADD_CBM", "strategy_type": "CONDITION_BASED"},
            current_value="Monthly time-based PM", proposed_value="Condition-based (SYNTHETIC readings)",
            expected_gate_status="DRAFT_ONLY",
        ),

        # 7. DRAFT_ONLY - task-list cleanup but no Work Strategy Owner named.
        _base(
            "MOTOR-5501", asset_class="ELECTRIC_MOTOR",
            user_question="Clean up this motor's task list.",
            readiness={"task_list_readiness": "YELLOW"},
            approval={"work_strategy_owner_named": False},
            proposed_recommendation={"type": "TASK_LIST_CLEANUP"},
            current_value="Task list with gaps", proposed_value="Cleaned task list",
            expected_gate_status="DRAFT_ONLY",
        ),

        # 8. BLOCKED - move criticality-3 to run-to-failure (RTF barred for 2/3/4).
        _base(
            "PUMP-4120",
            user_question="Can this critical pump go run-to-failure?",
            master_data={"criticality": {"code": "3", "label": "Critical"}},
            proposed_recommendation={"type": "MOVE_TO_RTF", "strategy_type": "RTF"},
            current_value="Monthly PM", proposed_value="Run-to-failure",
            expected_gate_status="BLOCKED",
        ),

        # 9. REVIEW_REQUIRED - criticality-0 (unvalidated) strategy change.
        _base(
            "HX-6601", asset_class="HEAT_EXCHANGER",
            user_question="Change this asset's strategy.",
            master_data={"criticality": {"code": "0", "label": "Pending assessment", "validation_status": "NOT_VALIDATED"}},
            proposed_recommendation={"type": "STRATEGY_TYPE_CHANGE", "strategy_type": "RISK_BASED"},
            current_value="Time-based PM", proposed_value="Risk-based strategy",
            expected_gate_status="REVIEW_REQUIRED",
        ),

        # 10. BLOCKED (out of analysis scope) - non-operated / JV asset.
        _base(
            "PUMP-4130",
            user_question="Assess this joint-venture pump's PM.",
            master_data={"operated_status": "JV", "criticality": {"code": "2", "label": "High-value non-critical"}},
            expected_gate_status="BLOCKED",
        ),

        # 11. BLOCKED (out of analysis scope) - exempt asset.
        _base(
            "PUMP-4140",
            user_question="Assess this exempt pump's PM.",
            master_data={"exemption_status": "EXEMPT", "exemption_id": "EX-001"},
            expected_gate_status="BLOCKED",
        ),

        # 12. PASS - criticality-1 keep-coverage improvement (add inspection), green.
        _base(
            "FAN-7701", asset_class="COOLING_FAN",
            user_question="Add a check to this fan's PM.",
            proposed_recommendation={"type": "ADD_INSPECTION"},
            current_value="Basic PM", proposed_value="PM + added inspection",
            expected_gate_status="REVIEW_REQUIRED",
        ),
    ]


def fleet_index() -> Dict[str, Dict[str, Any]]:
    return {a["equipment_id"]: a for a in synthetic_fleet()}


def asset_by_id(equipment_id: str) -> Optional[Dict[str, Any]]:
    return fleet_index().get(equipment_id)
