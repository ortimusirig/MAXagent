"""Regression tests for the three alignment fixes (free-flow grounding, approve-path gating, SQL binding).

Each pins the corrected behavior so a future change cannot silently reintroduce the deviation. Governance
invariants are preserved: deterministic tools DECIDE, the LLM only proposes/narrates, scope is
authoritative and fail-closed, and nothing reaches SAP.
"""

from __future__ import annotations

from max_agent.orchestrator import MaxAgent
from max_agent.sql_templates import sql_execution_plan


def _find(component, pred):
    """Depth-first search of a Dash component tree for the first node matching pred (children may be a
    single node, a list, or a plain string)."""
    if pred(component):
        return component
    children = getattr(component, "children", None)
    if children is None:
        return None
    for child in (children if isinstance(children, (list, tuple)) else [children]):
        found = _find(child, pred)
        if found is not None:
            return found
    return None


# 1. Free-flow grounding survives MULTIPLE consecutive follow-ups (free-flow cards carry no `result`).
def test_last_governed_result_survives_multiple_free_flow_turns():
    from app import _last_governed_result
    gov = {"equipment_id": "PUMP-4110", "gate_status": "REVIEW_REQUIRED"}
    history = [
        {"n": 1, "result": gov},                                      # a governed turn (carries result)
        {"n": 2, "kind": "free_flow", "answer": "...", "ref": {}},    # first free-flow card (no result)
        {"n": 3, "kind": "free_flow", "answer": "...", "ref": {}},    # SECOND consecutive free-flow card
    ]
    # Old code read history[-1].get("result") -> None on the 2nd follow-up (which re-ran GOVERNED).
    assert _last_governed_result(history) is gov


def test_last_governed_result_is_none_before_any_governed_turn():
    from app import _last_governed_result
    assert _last_governed_result([]) is None
    assert _last_governed_result([{"n": 1, "kind": "free_flow", "answer": "hi"}]) is None  # greeting only


# 2. Approve is gated on the package's approval path (PASS or REVIEW_REQUIRED), not the stricter submit path.
def test_studio_approve_enabled_for_review_required_package():
    a = MaxAgent()
    r = a.run("PUMP-4110")                          # package gate REVIEW_REQUIRED
    p = r["package"]
    assert p["approval_path_available"] is True
    assert p["submit_path_available"] is False      # the OLD (submit-path) rule wrongly disabled Approve
    from max_agent.ui.artifacts import render_governed_action
    btn = _find(render_governed_action(r, audit=[]), lambda c: getattr(c, "id", None) == "approve-btn")
    assert btn is not None
    assert btn.disabled is False                    # a REVIEW_REQUIRED package CAN be analyst-reviewed


def test_studio_approve_disabled_for_blocked_package():
    a = MaxAgent()
    r = a.run("PUMP-4115")                          # package gate BLOCKED
    assert r["package"]["approval_path_available"] is False
    from max_agent.ui.artifacts import render_governed_action
    btn = _find(render_governed_action(r, audit=[]), lambda c: getattr(c, "id", None) == "approve-btn")
    assert btn.disabled is True                     # BLOCKED stays fail-closed at the UI


def test_studio_approve_disabled_for_draft_only_package():
    a = MaxAgent()
    r = a.run("MOTOR-5501")                          # package gate DRAFT_ONLY (cannot enter approval)
    assert r["package"]["approval_path_available"] is False
    from max_agent.ui.artifacts import render_governed_action
    btn = _find(render_governed_action(r, audit=[]), lambda c: getattr(c, "id", None) == "approve-btn")
    assert btn.disabled is True


def test_inline_approve_button_respects_approval_path():
    from max_agent.ui.chat import render_inline_approval
    enabled = _find(render_inline_approval("PUMP-4110", 0, gate_status="REVIEW_REQUIRED", approve_ok=True),
                    lambda c: isinstance(getattr(c, "id", None), dict) and c.id.get("type") == "ff-approve")
    assert enabled.disabled is False
    disabled = _find(render_inline_approval("PUMP-4115", 0, gate_status="BLOCKED", approve_ok=False),
                     lambda c: isinstance(getattr(c, "id", None), dict) and c.id.get("type") == "ff-approve")
    assert disabled.disabled is True


# 3. The Databricks SQL path binds scope predicates server-side (no interpolation); row_cap is a trusted literal.
def test_sql_execution_plan_binds_scope_predicates_server_side():
    stmt, named = sql_execution_plan(
        "work_order_history", {"equipment_id": "PUMP-4102", "time_window": "LAST_24_MONTHS"},
        catalog="main", schema="max_agent")
    assert "main.max_agent.v_work_order_history" in stmt
    assert ":equipment_id" in stmt and ":time_window" in stmt      # stay as bound markers
    assert "PUMP-4102" not in stmt                                 # NOT interpolated -> no injection surface
    assert {p["name"]: p["value"] for p in named} == {"equipment_id": "PUMP-4102", "time_window": "LAST_24_MONTHS"}


def test_sql_execution_plan_inlines_trusted_row_cap():
    stmt, named = sql_execution_plan(
        "work_order_detail", {"equipment_id": "PUMP-4102", "time_window": "LAST_24_MONTHS", "row_cap": 25})
    assert "LIMIT 25" in stmt and ":row_cap" not in stmt           # trusted int inlined, no marker in LIMIT
    assert all(p["name"] != "row_cap" for p in named)              # row_cap is never a bound parameter
    assert ":equipment_id" in stmt and "PUMP-4102" not in stmt     # scope predicate still bound


def test_sql_execution_plan_row_cap_defaults_when_absent():
    stmt, _ = sql_execution_plan("work_order_detail", {"equipment_id": "X", "time_window": "Y"})
    assert "LIMIT 50" in stmt                                       # default cap, still no marker


def test_sql_execution_plan_missing_predicate_stays_unbound_fail_closed():
    # A missing scope value is NOT silently dropped/inlined: the marker stays, so the warehouse errors
    # (fail-closed) rather than running unscoped.
    stmt, named = sql_execution_plan("work_order_history", {"equipment_id": "X"})  # no time_window
    assert ":time_window" in stmt
    assert all(p["name"] != "time_window" for p in named)
