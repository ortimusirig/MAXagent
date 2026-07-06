"""Free-flow vs governed intent routing (orchestrator.classify_intent / free_flow_answer).

MAX is free-flow by default; the governance DAG is the route a GOVERNED intent triggers. A follow-up /
definition / greeting is answered conversationally from the LAST governed result + glossary, WITHOUT
re-running the pipeline and WITHOUT minting a new governed value. Fail-safe: unclear -> GOVERNED.
"""

from __future__ import annotations

from max_agent.orchestrator import MaxAgent
from max_agent.prompts import deterministic_free_flow, deterministic_intent


def test_governed_intents_route_to_the_pipeline():
    for q in ("is PUMP-4110 effective?", "should we shorten the interval?", "compare it to peers",
              "what's the cost view for this pump", "retire PUMP-4130?"):
        assert deterministic_intent(q, has_last_result=True) == "GOVERNED", q


def test_explain_and_greeting_route_to_free_flow():
    assert deterministic_intent("what does it mean?", has_last_result=True) == "FREE_FLOW"
    assert deterministic_intent("why?", has_last_result=True) == "FREE_FLOW"
    assert deterministic_intent("what does IMPROVE_TASK_LIST mean", has_last_result=True) == "FREE_FLOW"
    assert deterministic_intent("hi", has_last_result=False) == "FREE_FLOW"
    assert deterministic_intent("thanks", has_last_result=True) == "FREE_FLOW"


def test_explain_without_context_fails_safe_to_governed():
    # "why?" with no prior result isn't explainable -> treat as an analysis ask (never skip governance)
    assert deterministic_intent("why is that", has_last_result=False) == "GOVERNED"


def test_data_fetch_about_current_asset_routes_to_free_flow():
    # A read/fetch of EXISTING data about the asset just analysed is a fast read, not a new decision.
    for q in ("fetch data about the current asset", "show me the work orders for this asset",
              "pull up its failure history", "how many corrective work orders on this pump",
              "list the components for the current pm",
              "show it", "list this asset's components", "display the current pm's readings"):
        assert deterministic_intent(q, has_last_result=True) == "FREE_FLOW", q


def test_data_fetch_needs_a_prior_result_else_governed():
    # No asset analysed yet -> there is nothing to fetch about; run the governed pipeline (fail-safe).
    assert deterministic_intent("fetch data about the current asset", has_last_result=False) == "GOVERNED"


def test_data_fetch_naming_a_specific_id_stays_governed():
    # A raw equipment id may be a DIFFERENT asset -> let the governed pipeline resolve + analyse it.
    assert deterministic_intent("fetch the work orders for PUMP-4130", has_last_result=True) == "GOVERNED"


def test_fetch_that_also_asks_a_decision_stays_governed():
    assert deterministic_intent("show me why we should shorten this asset", has_last_result=True) == "GOVERNED"
    # a governed analytical ask on the current asset (no fetch verb) is unaffected by the carve-out
    assert deterministic_intent("what's the cost view for this pump", has_last_result=True) == "GOVERNED"


def test_offline_free_flow_fetch_surfaces_the_evidence_on_file():
    a = MaxAgent()
    r = a.run("PUMP-4110", question="is this pm effective")
    ans = a.free_flow_answer("fetch the data for the current asset", [], r)   # no LLM -> deterministic
    assert "on file" in ans
    assert "Work-order history" in ans or "Failure coding" in ans           # the retrieved evidence


def test_free_flow_answer_explains_last_result_read_only():
    a = MaxAgent()
    r = a.run("PUMP-4110", question="is this pm effective")
    ans = a.free_flow_answer("what does it mean?", [], r)          # no LLM locally -> deterministic
    assert "Improve the task list" in ans          # explains the recommendation in plain language
    assert "IMPROVE_TASK_LIST" not in ans          # never the raw code
    assert "does not change it" in ans             # read-only: it explains, it does not re-decide


def test_free_flow_with_no_prior_result_asks_to_analyze():
    a = MaxAgent()
    ans = a.free_flow_answer("what does it mean?", [], None)
    assert "specific PM" in ans and "run the governed analysis" in ans


def test_free_flow_answer_never_asserts_a_new_gate_code():
    a = MaxAgent()
    r = a.run("COMP-2201", question="why is this blocked")
    ans = a.free_flow_answer("what does blocked mean here?", [], r)
    # it may reference the last gate, but must not emit a raw gate/recommendation enum code
    for code in ("REVIEW_REQUIRED", "DRAFT_ONLY", "PM_FREQUENCY_CHANGE", "IMPROVE_TASK_LIST"):
        assert code not in ans


def test_free_flow_uses_read_only_tools_and_cannot_decide_or_write():
    # Free-flow's agentic loop binds the READ-ONLY tools (make_agent_tools) bound to the last governed
    # result: it can read the decision + fetch evidence/reliability/comparison/BOM/portfolio, but there is
    # NO decide-tool (so it never re-runs oxy_gate_check / re-classifies / re-recommends) and NO
    # write/approval tool. A fresh decision must go through the governed lane.
    import pytest
    pytest.importorskip("langchain_core")
    from max_agent.agent_tools import make_agent_tools
    a = MaxAgent()
    last = a.run("PUMP-4110")
    names = {t.name for t in make_agent_tools(a, last)}
    assert {"governed_decision", "evidence", "reliability", "like_equipment_comparison",
            "execution_readiness", "parts_bom", "reliability_drift", "cost_distribution",
            "portfolio_health"} <= names
    for banned in ("run_oxy_gate", "classify_effectiveness", "recommend_change", "check_data_readiness",
                   "draft_sap_change_package", "approval_workflow_state"):
        assert banned not in names, f"{banned} must NOT be reachable from free-flow"


def test_free_flow_agent_returns_none_without_a_prior_result():
    from max_agent.agent_loop import run_free_flow_agent
    a = MaxAgent()
    assert run_free_flow_agent(a, "what does it mean?", [], None) is None  # nothing to ground on
