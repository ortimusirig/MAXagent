"""Unit tests for oxy_gate_check - every case from 08 "Unit Test Cases".

Each test overrides only the fields that exercise its rule (via the ``gate_kwargs`` factory)
and asserts the precise ``blocked_reason`` / ``review_trigger`` where the spec names one, so a
broken predicate cannot hide behind the final "criticality 2/3/4 or changes_strategy" catch-all.
"""

from max_agent.tools.governance import oxy_gate_check


def gs(result):
    return result["data"]["gate_status"]


def rt(result):
    return result["data"].get("review_trigger")


def br(result):
    return result["blocked_reason"]


# --- Hard blocks -------------------------------------------------------------

def test_blocks_direct_sap_update(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(requested_action="DIRECT_SAP_UPDATE"))
    assert gs(result) == "BLOCKED"
    assert br(result) == "DIRECT_SAP_UPDATE_OUT_OF_SCOPE"


def test_blocks_frequency_reduction_without_risk_scorecard(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "EXTEND"},
        risk={"risk_scorecard_available": False, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "RISK_SCORECARD_REQUIRED"


def test_blocks_when_risk_scorecard_result_blocks(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "EXTEND"},
        risk={"risk_scorecard_available": True, "risk_result": "BLOCK", "risk_threshold_met": True},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "RISK_THRESHOLD_NOT_MET"


def test_blocks_when_risk_threshold_not_met(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "EXTEND"},
        risk={"risk_scorecard_available": True, "risk_result": "REVIEW", "risk_threshold_met": False},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "RISK_THRESHOLD_NOT_MET"


def test_blocks_red_data_for_frequency_change(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "SHORTEN"},
        readiness={"data_readiness": "RED"},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "DATA_READINESS_RED"


def test_blocks_weak_evidence_for_strong_data_recommendation(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "SHORTEN"},
        readiness={"data_readiness": "GREEN", "evidence_sufficiency": "WEAK"},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "EVIDENCE_WEAK"


def test_blocks_hse_critical_reduction_without_compliance(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        criticality={"code": "4", "validation_status": "VALIDATED"},
        recommendation={"type": "RETIRE_PM"},
        approval={"work_strategy_owner_named": True, "compliance_safety_named": False, "sap_pm_owner_required": False},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert gs(result) == "BLOCKED"  # criticality-4 reduce is barred (mandatory / HSE)


def test_blocks_mandatory_pm_coverage_reduction(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        pm_governance={"mandatory_pm": True, "mandatory_basis": "PM_REG"},
        recommendation={"type": "RETIRE_PM"},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "MANDATORY_PM_CANNOT_REDUCE_COVERAGE"


def test_blocks_cbm_without_real_measurement_readings(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "ADD_CBM"},
        readiness={"cbm_real_readings_available": False, "cbm_synthetic_data_flag": False},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "CBM_REQUIRES_REAL_MEASUREMENT_READINGS"


def test_blocks_abc4_without_object_dependency(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        criticality={"code": "4", "validation_status": "VALIDATED"},
        recommendation={"type": "ADD_INSPECTION"},
        readiness={"object_dependency_code": None},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "ABC4_OBJECT_DEPENDENCY_REQUIRED"


def test_blocks_rbi_when_bu_profile_disables_rbi(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "STRATEGY_TYPE_CHANGE", "analysis_method": "RBI"},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "RBI_DISABLED_BY_BU_PROFILE"


def test_blocks_strategy_type_disabled_by_bu_profile(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "STRATEGY_TYPE_CHANGE", "strategy_type": "GHOST_STRATEGY"},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "STRATEGY_TYPE_DISABLED_BY_BU_PROFILE"


def test_blocks_when_risk_result_pass_but_threshold_not_confirmed(gate_kwargs):
    # risk_result PASS but risk_threshold_met is not explicitly True -> cannot confirm threshold.
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "SHORTEN"},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": None},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "RISK_THRESHOLD_NOT_CONFIRMED"


def test_blocks_when_risk_result_not_pass_or_review(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "SHORTEN"},
        risk={"risk_scorecard_available": True, "risk_result": "UNKNOWN", "risk_threshold_met": True},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "RISK_RESULT_REQUIRED"


def test_blocks_analysis_method_not_in_enabled_list(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "TASK_LIST_CLEANUP", "analysis_method": "SOMETHING_ELSE"},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "ANALYSIS_METHOD_NOT_ENABLED"


def test_blocks_rtf_for_criticality_2_3_4(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        criticality={"code": "3", "validation_status": "VALIDATED"},
        pm_governance={"mandatory_pm": False},
        recommendation={"type": "MOVE_TO_RTF", "strategy_type": "RTF"},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "RTF_BARRED_FOR_CRITICAL_2_3_4"


def test_blocks_required_component_owner_missing(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "ADD_COMPONENT"},
        readiness={"component_readiness": "RED"},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "EXECUTION_READINESS_BLOCKED"


def test_blocks_cbm_conversion_without_measurement_readiness(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "CBM_CONVERSION"},
        # readings available (so the readings rule passes) but the readiness domain is RED.
        readiness={"cbm_real_readings_available": True, "cbm_readiness": "RED", "data_readiness": "GREEN"},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "EXECUTION_READINESS_BLOCKED"


# --- Draft-only holds --------------------------------------------------------

def test_allows_draft_only_without_work_strategy_owner(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "ADD_INSPECTION"},
        approval={"work_strategy_owner_named": False, "sap_pm_owner_required": False},
    ))
    assert gs(result) == "DRAFT_ONLY"
    assert br(result) == "WORK_STRATEGY_OWNER_REQUIRED"


def test_draft_package_without_sap_pm_owner_returns_draft_only(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "SAP_OBJECT_CHANGE"},
        approval={"work_strategy_owner_named": True, "sap_pm_owner_required": True, "sap_pm_owner_named": False},
    ))
    assert gs(result) == "DRAFT_ONLY"
    assert br(result) == "SAP_PM_OWNER_REQUIRED"


def test_allows_synthetic_cbm_demo_as_draft_only(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "ADD_CBM"},
        readiness={"cbm_real_readings_available": False, "cbm_synthetic_data_flag": True},
        requested_action="DRAFT_PACKAGE",
    ))
    assert gs(result) == "DRAFT_ONLY"
    assert br(result) == "CBM_SYNTHETIC_DEMO_ONLY"


def test_master_data_submit_without_level_loading_is_draft_only(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "TASK_LIST_CLEANUP"},
        readiness={"level_loading_status": "DEFERRED_WAVE_1", "practicality_status": "COMPLETE"},
        approval_state={"peer_review_complete": True},
        requested_action="MASTER_DATA_SUBMIT",
    ))
    assert gs(result) == "DRAFT_ONLY"
    assert br(result) == "LEVEL_LOADING_DEFERRED_WAVE_1"


def test_master_data_submit_without_practicality_is_draft_only(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "TASK_LIST_CLEANUP"},
        readiness={"level_loading_status": "COMPLETE", "practicality_status": "INCOMPLETE"},
        approval_state={"peer_review_complete": True},
        requested_action="MASTER_DATA_SUBMIT",
    ))
    assert gs(result) == "DRAFT_ONLY"
    assert br(result) == "PRACTICALITY_NOT_CONFIRMED"


def test_master_data_submit_without_peer_review_is_draft_only(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "TASK_LIST_CLEANUP"},
        readiness={"level_loading_status": "COMPLETE", "practicality_status": "COMPLETE"},
        approval_state={"peer_review_complete": False},
        requested_action="MASTER_DATA_SUBMIT",
    ))
    assert gs(result) == "DRAFT_ONLY"
    assert br(result) == "PEER_REVIEW_NOT_CONFIRMED"


def test_allows_data_cleanup_draft_on_red_data(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "DATA_CLEANUP"},
        readiness={"data_readiness": "RED", "evidence_sufficiency": "WEAK"},
    ))
    assert gs(result) == "DRAFT_ONLY"
    assert br(result) == "DATA_CLEANUP_ONLY"


# --- Review-required routes ---------------------------------------------------

def test_requires_review_when_risk_scorecard_result_review(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "SHORTEN"},
        risk={"risk_scorecard_available": True, "risk_result": "REVIEW", "risk_threshold_met": True},
    ))
    assert gs(result) == "REVIEW_REQUIRED"
    assert rt(result) == "RISK_REVIEW_REQUIRED"


def test_requires_review_for_critical_frequency_change(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        criticality={"code": "3", "validation_status": "VALIDATED"},
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "SHORTEN"},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert gs(result) == "REVIEW_REQUIRED"
    assert rt(result) == "CRITICALITY_OR_STRATEGY_CHANGE"


def test_requires_review_when_data_readiness_yellow(gate_kwargs):
    # Non-strategy-change recommendation with YELLOW data routes to review with a caveat.
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "RETAIN_PM"},
        readiness={"data_readiness": "YELLOW"},
    ))
    assert gs(result) == "REVIEW_REQUIRED"
    assert rt(result) == "DATA_READINESS_YELLOW"


def test_requires_review_when_criticality_pending_or_unassigned(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        criticality={"code": "0", "validation_status": "NOT_VALIDATED"},
        recommendation={"type": "ADD_INSPECTION"},
    ))
    assert gs(result) == "REVIEW_REQUIRED"
    assert rt(result) == "CRITICALITY_NOT_VALIDATED"


def test_requires_review_for_rejected_acceptance_without_follow_on_crmn(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "TASK_LIST_CLEANUP"},
        readiness={"acceptance_criteria_result": "REJECTED", "follow_on_crmn_expected": False, "follow_on_crmn_created": False},
    ))
    assert gs(result) == "REVIEW_REQUIRED"
    assert rt(result) == "ACCEPTANCE_CRITERION_REJECTED_NO_FOLLOW_ON"


def test_requires_review_when_moc_threshold_exceeded(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "SHORTEN", "moc_threshold_exceeded": True},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert gs(result) == "REVIEW_REQUIRED"
    assert rt(result) == "MOC_THRESHOLD_EXCEEDED"


def test_requires_review_when_strategy_past_reevaluation_cadence(gate_kwargs):
    kwargs = gate_kwargs(
        recommendation={"type": "TASK_LIST_CLEANUP", "strategy_review_age_days": 1200},
    )
    kwargs["bu_profile"]["reevaluation_cadence"]["days"] = 1095  # within the 1825 ceiling
    result = oxy_gate_check(**kwargs)
    assert gs(result) == "REVIEW_REQUIRED"
    assert rt(result) == "STRATEGY_PAST_REEVALUATION_CADENCE"


def test_review_when_cadence_exceeds_five_year_ceiling(gate_kwargs):
    kwargs = gate_kwargs(
        recommendation={"type": "TASK_LIST_CLEANUP", "strategy_review_age_days": 120},
    )
    kwargs["bu_profile"]["reevaluation_cadence"]["days"] = 3000  # > max_days 1825
    result = oxy_gate_check(**kwargs)
    assert gs(result) == "REVIEW_REQUIRED"
    assert rt(result) == "REEVALUATION_CADENCE_EXCEEDS_CEILING"


# --- Pass --------------------------------------------------------------------

def test_passes_noncritical_retain_pm(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs())
    assert gs(result) == "PASS"
    assert br(result) is None


# --- BU profile override behavior --------------------------------------------

def test_uses_bu_profile_pm_requirement_overrides(gate_kwargs):
    # Criticality 2 resolves to MANDATORY -> reduce is blocked.
    mandatory = oxy_gate_check(**gate_kwargs(
        criticality={"code": "2", "validation_status": "VALIDATED"},
        pm_governance={"mandatory_pm": False},
        recommendation={"type": "RETIRE_PM"},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert gs(mandatory) == "BLOCKED"
    assert br(mandatory) == "MANDATORY_PM_CANNOT_REDUCE_COVERAGE"

    # Criticality 1 resolves to BU_DISCRETION -> no mandatory-branch block (routes to review).
    discretion = oxy_gate_check(**gate_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
        pm_governance={"mandatory_pm": False},
        recommendation={"type": "RETIRE_PM"},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert gs(discretion) == "REVIEW_REQUIRED"
    assert br(discretion) != "MANDATORY_PM_CANNOT_REDUCE_COVERAGE"


# --- Scope gate (runs first, fail-closed) ------------------------------------

def test_blocks_when_scope_not_validated_unresolved_asset(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        scope={"scope_validated": False, "in_scope": False, "blocked_reason": "NO_VALIDATED_SCOPE"},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "NO_VALIDATED_SCOPE"
    assert result["scope_validated"] is False


def test_blocks_when_pm_population_empty(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        scope={"scope_validated": False, "in_scope": False, "blocked_reason": "EMPTY_PM_POPULATION"},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "EMPTY_PM_POPULATION"
    assert result["scope_validated"] is False


def test_blocks_non_operated_jv_asset_out_of_scope(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        scope={"scope_validated": True, "in_scope": False, "blocked_reason": "NON_OPERATED_OR_JV_OUT_OF_SCOPE"},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "NON_OPERATED_OR_JV_OUT_OF_SCOPE"


def test_blocks_exempt_asset_out_of_scope(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        scope={"scope_validated": True, "in_scope": False, "blocked_reason": "EXEMPT_ASSET_OUT_OF_SCOPE"},
    ))
    assert gs(result) == "BLOCKED"
    assert br(result) == "EXEMPT_ASSET_OUT_OF_SCOPE"
