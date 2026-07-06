"""Regression tests for the seven Codex-review fixes.

Each test pins the corrected behavior so a future change cannot silently reintroduce the defect.
Governance invariants (fail-closed scope, no invented Oxy value, deterministic decides) are preserved.
"""

from __future__ import annotations

from max_agent.intent import resolve_asset_from_text
from max_agent.orchestrator import MaxAgent
from max_agent.prompts import _gate_reason
from max_agent.synthetic_data import fleet_index
from max_agent.tools.governance import approval_workflow_state
from max_agent.tools.retrieval import run_scoped_sql
from max_agent.tools.sql_guard import validate_generated_sql

_ALLOW = ["v_work_order_history"]


# 1. SQL guard: an IN(...) predicate counts as scope-bound ONLY when fully parameter-bound.
def test_sql_guard_requires_bound_in_list():
    scope = {"equipment_id": "PUMP-4102"}
    bound = validate_generated_sql(
        "SELECT order_type FROM v_work_order_history WHERE equipment_id IN (:ids)", _ALLOW, scope)
    assert bound["scope_filter_present"] is True
    assert bound["status"] == "PASSED"

    inlined = validate_generated_sql(
        "SELECT order_type FROM v_work_order_history WHERE equipment_id IN ('PUMP-4130','PUMP-4140')", _ALLOW, scope)
    assert inlined["scope_filter_present"] is False          # inlined literals are NOT proof of scope
    assert "SCOPE_FILTER_NOT_BOUND" in inlined["reasons"]
    assert inlined["status"] != "PASSED"


# 2. run_scoped_sql ENFORCES the row cap (does not merely detect a LIMIT), and reports the truncation.
def test_run_scoped_sql_enforces_row_cap():
    def _ex(_t, _p):
        return [{"i": i} for i in range(10)]
    env = run_scoped_sql("work_order_detail", {"equipment_id": "X"}, {"row_cap": 3}, executor=_ex)
    d = env["data"]
    assert d["row_count"] == 3
    assert d["row_cap_truncated"] is True
    assert d["dropped_row_count"] == 7                        # no silent cap


# 3. The out-of-scope (fail-closed) path exposes NO scoped evidence records.
def test_out_of_scope_run_reads_no_evidence():
    r = MaxAgent().run("PUMP-4130")  # JV, out of analysis scope
    assert r["evidence"] == {}       # base evidence SQL runs only after the scope check passes


# 4. Free-text resolver: only an explicit fleet id auto-resolves; a class word / fake id does not.
def test_resolver_only_locks_on_an_explicit_fleet_id():
    fi = fleet_index()
    # a bare class word -> candidates for the UI, never an auto-picked first asset
    cls = resolve_asset_from_text("why does this pump keep failing?", fi)
    assert cls["equipment_id"] is None
    assert len(cls["candidates"]) > 1

    # a fabricated id near a real one does not resolve to the real asset
    fake = resolve_asset_from_text("assess PUMP-41020 for me", fi)
    assert fake["equipment_id"] != "PUMP-4102"

    # an explicit real id resolves exactly
    exact = resolve_asset_from_text("is COMP-2201 effective?", fi)
    assert exact["equipment_id"] == "COMP-2201"


# 5. Approval: "request changes" / "reject" from a DRAFT package are real, authorized transitions.
def test_request_changes_from_draft_reaches_changes_requested():
    r = approval_workflow_state(
        "PKG-1", "DRAFT", requested_transition="CHANGES_REQUESTED",
        actor={"user_id": "p1", "roles": ["planner_scheduler"]}, gate_status="PASS")
    assert r["data"]["transition_allowed"] is True
    assert r["data"]["current_state"] == "CHANGES_REQUESTED"


def test_reject_from_draft_is_allowed():
    r = approval_workflow_state(
        "PKG-1", "DRAFT", requested_transition="REJECTED",
        actor={"user_id": "p1", "roles": ["planner_scheduler"]}, gate_status="PASS")
    assert r["data"]["transition_allowed"] is True


# 6. Decision wording: the package drafts MAX's recommendation, not the change under review.
def test_decision_wording_says_package_drafts_the_recommendation():
    from max_agent.ui.artifacts import render_decision
    r = MaxAgent().run("PUMP-4102")            # recommendation diverges from the requested change
    assert r["recommendation_diverges"] is True
    blob = str(render_decision(r))
    assert "drafts MAX's recommendation" in blob
    assert "drafts the change under review" not in blob


# 7. Gate reason: a REVIEW_REQUIRED gate falls back to the review trigger (never 'reason None').
def test_review_gate_reason_falls_back_to_review_trigger():
    assert _gate_reason({"gate_status": "REVIEW_REQUIRED", "gate_review_trigger": "RISK_SCORECARD_REVIEW"}) == "RISK_SCORECARD_REVIEW"
    r = MaxAgent().run("PUMP-4110")            # a real REVIEW_REQUIRED asset
    assert r["gate_status"] == "REVIEW_REQUIRED"
    assert _gate_reason(r)                      # truthy - not None
