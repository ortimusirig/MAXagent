"""Fail-closed / unknown-Oxy-value invariants.

These prove that unresolved Oxy values do NOT get turned into permissive behavior. Each maps to
a Deep Audit 3 requirement and to a Decision Register row; the matching spec bullets are in
70/08 ("Fail-Closed Invariants (unknown Oxy values)") and 70/10 (draft_sap_change_package).

Invariants:
1. Unknown mandatory tag fails closed (protected on the criticality 2/3/4 proxy).   B2 / C7
2. Unknown MOC threshold is review-only (never blocks, never silently passes).       C3 / 60.400.304
3. CBM without real readings blocks.                                                  F1
4. Direct SAP write-back is blocked.                                                  G2
5. Stage 7 level loading deferred keeps a master-data submit draft-only.              E3
"""

from max_agent.tools.governance import moc_threshold_exceeded, oxy_gate_check
from max_agent.tools.package import draft_sap_change_package


def _gs(result):
    return result["data"]["gate_status"]


# 1. Unknown mandatory tag -> fail closed on the criticality proxy (B2 / C7).
def test_unknown_mandatory_tag_fails_closed(gate_kwargs):
    # pm_governance.mandatory_pm is None (the SAP tag is unknown), yet a criticality-4 asset
    # must still block a reduce/retire on the asset-coverage mandate.
    result = oxy_gate_check(**gate_kwargs(
        criticality={"code": "4", "validation_status": "VALIDATED"},
        pm_governance={"mandatory_pm": None, "mandatory_basis": None},
        recommendation={"type": "RETIRE_PM"},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    ))
    assert _gs(result) == "BLOCKED"
    assert result["blocked_reason"] == "MANDATORY_PM_CANNOT_REDUCE_COVERAGE"


# 2. Unknown MOC threshold -> review-only; material change still routed to review, not skipped (C3).
def test_moc_unknown_is_review_only(gate_kwargs):
    kwargs = gate_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
        recommendation={"type": "PM_FREQUENCY_CHANGE", "direction": "SHORTEN", "moc_threshold_exceeded": False},
        risk={"risk_scorecard_available": True, "risk_result": "PASS", "risk_threshold_met": True},
    )
    # The default profile keeps moc_threshold null -> no MOC-specific escalation fires.
    assert moc_threshold_exceeded(kwargs["recommendation"], kwargs["bu_profile"]) is False
    result = oxy_gate_check(**kwargs)
    # But the material change is NOT skipped: it still returns REVIEW_REQUIRED via the
    # strategy-change rule (not BLOCKED, and not via a fabricated MOC flag).
    assert _gs(result) == "REVIEW_REQUIRED"
    assert result["data"]["review_trigger"] != "MOC_THRESHOLD_EXCEEDED"


# 3. CBM without real readings -> blocked (F1).
def test_cbm_without_readings_blocks(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "ADD_CBM"},
        readiness={"cbm_real_readings_available": False, "cbm_synthetic_data_flag": False},
    ))
    assert _gs(result) == "BLOCKED"
    assert result["blocked_reason"] == "CBM_REQUIRES_REAL_MEASUREMENT_READINGS"


# 4. Direct SAP write-back -> blocked (G2).
def test_direct_sap_write_back_blocks(gate_kwargs):
    result = oxy_gate_check(**gate_kwargs(requested_action="DIRECT_SAP_UPDATE"))
    assert _gs(result) == "BLOCKED"
    assert result["blocked_reason"] == "DIRECT_SAP_UPDATE_OUT_OF_SCOPE"


# 5. Stage 7 level loading deferred -> master-data submit stays draft-only; package is draft-only (E3).
def test_stage7_deferred_keeps_package_draft_only(gate_kwargs):
    gate = oxy_gate_check(**gate_kwargs(
        recommendation={"type": "TASK_LIST_CLEANUP"},
        readiness={"level_loading_status": "DEFERRED_WAVE_1", "practicality_status": "COMPLETE"},
        approval_state={"peer_review_complete": True},
        requested_action="MASTER_DATA_SUBMIT",
    ))
    assert _gs(gate) == "DRAFT_ONLY"
    assert gate["blocked_reason"] == "LEVEL_LOADING_DEFERRED_WAVE_1"

    pkg = draft_sap_change_package(recommendation={"type": "TASK_LIST_CLEANUP"}, gate_result=gate)
    assert pkg["data"]["submit_path_available"] is False
    assert pkg["data"]["approval_path_available"] is False
    assert pkg["data"]["level_loading_status"] == "NOT_ASSESSED_WAVE_1"
    assert pkg["data"]["max_writes_sap"] is False
