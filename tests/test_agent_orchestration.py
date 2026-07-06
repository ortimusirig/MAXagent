"""Deterministic run + read-only free-flow tools (post narration-gate refactor).

The GOVERNED lane is deterministic; the LLM only narrates through the shared narration gate. FREE-FLOW
uses the READ-ONLY tools (make_agent_tools) and never re-decides / re-runs oxy_gate_check. Without a
serving endpoint the app runs deterministic-only. The narration gate itself is tested in
test_narration_gate.py.
"""

from __future__ import annotations

from max_agent.agent_loop import free_flow_tools_available
from max_agent.orchestrator import MaxAgent


def test_free_flow_tools_unavailable_without_stack_or_endpoint():
    # No serving endpoint bound locally -> the read-only free-flow tool loop is unavailable (fallbacks run).
    assert free_flow_tools_available(MaxAgent().client) is False


def test_deterministic_only_when_no_question():
    r = MaxAgent().run("COMP-2201")
    assert r["orchestration_mode"] == "deterministic_only"
    assert r["chat_summary"]  # deterministic summary present


def test_question_without_endpoint_stays_deterministic():
    r = MaxAgent().run("COMP-2201", question="is this compressor PM ok?")
    # No endpoint bound -> narration gate falls to the deterministic template -> mode deterministic_only.
    assert r["orchestration_mode"] == "deterministic_only"
    assert r["gate_status"] == "BLOCKED"


def test_recommendation_is_gate_checked_and_divergence_flagged():
    # 70/10: every recommendation passes to oxy_gate_check. PUMP-4102 (Missing Evidence) -> MAX
    # recommends DATA_REMEDIATION, which differs from the scenario's RETAIN_PM change under review.
    r = MaxAgent().run("PUMP-4102")
    assert r["change_under_review_type"] == "RETAIN_PM"
    assert r["recommendation_type"] == "DATA_REMEDIATION"
    assert r["recommendation_diverges"] is True
    assert r.get("recommendation_gate_status") in {"PASS", "REVIEW_REQUIRED", "DRAFT_ONLY", "BLOCKED"}


def test_answer_resolves_explicit_id_and_threads_question():
    r = MaxAgent().answer("why does COMP-2201 keep failing?")
    assert r["equipment_id"] == "COMP-2201"
    assert r["user_question"] == "why does COMP-2201 keep failing?"
    assert r["orchestration_mode"] == "deterministic_only"  # no endpoint bound locally


def test_read_only_tools_report_the_governed_decision_and_cannot_decide():
    # make_agent_tools needs langchain_core; skip cleanly when the agentic stack is absent.
    import pytest
    pytest.importorskip("langchain_core")
    from max_agent.agent_tools import make_agent_tools
    agent = MaxAgent()
    result = agent.run("COMP-2201")
    tools = make_agent_tools(agent, result)
    names = {t.name for t in tools}
    assert "governed_decision" in names and "evidence" in names
    # No decide-tool and no write-tool is reachable from the read-only free-flow set.
    for banned in ("run_oxy_gate", "classify_effectiveness", "recommend_change",
                   "draft_sap_change_package", "approval_workflow_state"):
        assert banned not in names
    gd = next(t for t in tools if t.name == "governed_decision")
    out = gd.invoke({})
    assert out["gate_status"] == "BLOCKED"  # reports the deterministic decision, read-only
