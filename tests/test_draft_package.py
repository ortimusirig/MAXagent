"""Unit tests for draft_sap_change_package - every case from 10 ("draft_sap_change_package").

Draft-only, no write. Blocked gate -> documentation-only; draft-only gate -> no submit path;
level loading not assessed; business impact baseline-only; synthetic provenance badged.
"""

from max_agent.tools.package import draft_sap_change_package


def _gate(gate_status, blocked_reason=None, review_trigger=None):
    """Minimal oxy_gate_check-shaped result envelope."""
    return {
        "data": {
            "gate_status": gate_status,
            "required_approvers": ["Planner", "Reliability Engineer"],
            "review_trigger": review_trigger,
        },
        "blocked_reason": blocked_reason,
    }


def test_no_direct_write_action_emitted():
    pkg = draft_sap_change_package(recommendation={"type": "PM_FREQUENCY_CHANGE"}, gate_result=_gate("PASS"))
    assert pkg["data"]["max_writes_sap"] is False
    actions = pkg["data"]["emitted_actions"]
    assert all("DIRECT_SAP_UPDATE" not in a and "WRITE" not in a.upper() for a in actions)


def test_blocked_gate_yields_documentation_only_package():
    pkg = draft_sap_change_package(
        recommendation={"type": "RETIRE_PM"},
        gate_result=_gate("BLOCKED", blocked_reason="MANDATORY_PM_CANNOT_REDUCE_COVERAGE"),
    )
    assert pkg["data"]["package_type"] == "documentation_only"
    assert pkg["data"]["approval_path_available"] is False
    assert pkg["data"]["submit_path_available"] is False


def test_draft_only_gate_has_no_submit_path():
    pkg = draft_sap_change_package(
        recommendation={"type": "ADD_CBM"},
        gate_result=_gate("DRAFT_ONLY", blocked_reason="CBM_SYNTHETIC_DEMO_ONLY"),
    )
    assert pkg["data"]["submit_path_available"] is False
    assert pkg["data"]["approval_path_available"] is False


def test_level_loading_marked_not_assessed():
    pkg = draft_sap_change_package(recommendation={"type": "TASK_LIST_CLEANUP"}, gate_result=_gate("PASS"))
    assert pkg["data"]["level_loading_status"] == "NOT_ASSESSED_WAVE_1"


def test_baseline_only_no_savings_claim():
    pkg = draft_sap_change_package(
        recommendation={"type": "PM_FREQUENCY_CHANGE"},
        gate_result=_gate("REVIEW_REQUIRED", review_trigger="MOC_THRESHOLD_EXCEEDED"),
    )
    assert pkg["data"]["business_impact"]["basis"] == "baseline_only"
    assert pkg["data"]["business_impact"]["projected_savings"] is None


def test_synthetic_flag_propagates():
    pkg = draft_sap_change_package(
        recommendation={"type": "ADD_CBM"},
        gate_result=_gate("DRAFT_ONLY", blocked_reason="CBM_SYNTHETIC_DEMO_ONLY"),
        provenance="SYNTHETIC",
        current_value="7 days",
        proposed_value="14 days",
    )
    assert pkg["data"]["synthetic_flag"] is True
    assert pkg["data"]["current_value"]["synthetic"] is True


# --- Attachment-K shaping (80/12 field map) ----------------------------------

def test_carries_attachment_k_fields_when_sources_exist(bu_profile):
    # Values supplied by upstream tools are assembled into the worksheet-shaped payload.
    pkg = draft_sap_change_package(
        recommendation={"type": "PM_FREQUENCY_CHANGE", "analysis_method": "PMO", "strategy_type": "TIME_BASED"},
        gate_result=_gate("REVIEW_REQUIRED", review_trigger="CRITICALITY_OR_STRATEGY_CHANGE"),
        criticality={"code": "3", "validation_status": "VALIDATED"},
        readiness={"object_dependency_code": "PM_MCW", "work_center": "MECH01", "planned_hours": 4.0},
        bu_profile=bu_profile,
    )
    ak = pkg["data"]["attachment_k"]
    assert ak["criticality"]["code"] == "3"
    assert ak["analysis_method"] == "PMO"
    assert ak["strategy_type"] == "TIME_BASED"
    assert ak["object_dependency"]["code"] == "PM_MCW"
    assert ak["object_dependency"]["critical_work_flag"] is True  # PM_MCW is in the BU catalog
    assert ak["task_list"]["work_center"] == "MECH01"


def test_unknown_attachment_k_fields_are_deferred_not_invented(bu_profile):
    pkg = draft_sap_change_package(
        recommendation={"type": "PM_FREQUENCY_CHANGE"},
        gate_result=_gate("REVIEW_REQUIRED"),
        criticality={"code": "2", "validation_status": "VALIDATED"},
        readiness={},
        bu_profile=bu_profile,
    )
    ak = pkg["data"]["attachment_k"]
    # Unknown Oxy sources are marked, never fabricated.
    assert ak["object_dependency"]["mandatory_tag_source"] == "BU_DEFINED"  # B2/C7, not invented
    assert ak["cost_benefit"]["labor_cost"] is None  # F1 - no labor cost
    assert ak["cost_benefit"]["cost_of_loss"] is None  # deferred
    assert ak["cost_benefit"]["probability_of_failure"] is None  # deferred
    assert ak["master_data_request"]["status"] == "STUB"  # G1 / PGHO - deferred
    assert ak["moc_linkage"] == "REVIEW_REQUIRED_ONLY"  # C3 - no MOC-ready package
    assert ak["attachment_k_confirmed"] is False  # exact p.42 layout confirmed in Houston
    postures = {d["field"]: d["posture"] for d in pkg["data"]["deferred_fields"]}
    assert postures["mandatory_tag_source"] == "FAIL_CLOSED"
    assert postures["moc_package"] == "REVIEW_REQUIRED"
    assert postures["level_loading"] == "NOT_ASSESSED_WAVE_1"
