"""Unit tests for approval_workflow_state - every case from 10 ("approval_workflow_state").

Master Data Submitted is the last state MAX produces; Implemented / Monitored / Closed are
status-only reflections, never a MAX write.
"""

from max_agent.tools.governance import approval_workflow_state


def allowed(result):
    return result["data"]["transition_allowed"]


def reason(result):
    return result["data"]["blocked_transition_reason"]


def test_blocks_transition_when_gate_blocked():
    result = approval_workflow_state(
        "PKG-1", "DRAFT",
        requested_transition="ANALYST_REVIEWED",
        actor={"user_id": "u1", "roles": ["planner_scheduler"]},
        gate_status="BLOCKED",
    )
    assert allowed(result) is False
    assert reason(result) == "GATE_BLOCKED"


def test_master_data_submit_requires_practicality_peer_review_levelloading():
    base = dict(
        package_id="PKG-1",
        current_state="WSO_APPROVED",
        requested_transition="MASTER_DATA_SUBMITTED",
        actor={"user_id": "mdc", "roles": ["mdc_bpdo"]},
        gate_status="PASS",
    )
    r_practicality = approval_workflow_state(
        **base,
        readiness={"practicality_status": "INCOMPLETE", "level_loading_status": "COMPLETE"},
        approval_state={"peer_review_complete": True},
    )
    assert reason(r_practicality) == "PRACTICALITY_INCOMPLETE"

    r_peer = approval_workflow_state(
        **base,
        readiness={"practicality_status": "COMPLETE", "level_loading_status": "COMPLETE"},
        approval_state={"peer_review_complete": False},
    )
    assert reason(r_peer) == "PEER_REVIEW_INCOMPLETE"

    r_level = approval_workflow_state(
        **base,
        readiness={"practicality_status": "COMPLETE", "level_loading_status": "DEFERRED_WAVE_1"},
        approval_state={"peer_review_complete": True},
    )
    assert reason(r_level) == "LEVEL_LOADING_DEFERRED"


def test_rejects_self_approval():
    result = approval_workflow_state(
        "PKG-1", "SME_REVIEWED",
        requested_transition="WSO_APPROVED",
        actor={"user_id": "u1", "roles": ["work_strategy_owner"]},
        gate_status="PASS",
        creator_user_id="u1",
    )
    assert allowed(result) is False
    assert reason(result) == "SELF_APPROVAL_NOT_ALLOWED"


def test_rejects_unverified_role():
    result = approval_workflow_state(
        "PKG-1", "DRAFT",
        requested_transition="ANALYST_REVIEWED",
        actor={"user_id": "u2", "roles": []},
        gate_status="PASS",
    )
    assert allowed(result) is False
    assert reason(result) == "ROLE_NOT_VERIFIED"


def test_post_submission_states_are_status_only():
    result = approval_workflow_state(
        "PKG-1", "MASTER_DATA_SUBMITTED",
        requested_transition="IMPLEMENTED",
        actor={"user_id": "sys", "roles": []},
        gate_status="PASS",
    )
    assert result["data"]["is_status_only"] is True
    assert result["data"]["max_writes_sap"] is False


def test_draft_to_analyst_reviewed_allowed_for_planner():
    result = approval_workflow_state(
        "PKG-1", "DRAFT",
        requested_transition="ANALYST_REVIEWED",
        actor={"user_id": "p1", "roles": ["planner_scheduler"]},
        gate_status="PASS",
    )
    assert allowed(result) is True
    assert result["data"]["role_verified"] is True
    assert result["data"]["current_state"] == "ANALYST_REVIEWED"
