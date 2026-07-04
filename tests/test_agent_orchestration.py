"""LLM tool-calling orchestration (agent_loop) - the governance fence and deterministic fallback.

The chat path may narrate via a LangGraph react agent, but the deterministic gate/label/package are
authoritative and must never change. When the agentic stack / serving endpoint is absent, the app
runs deterministic-only. langgraph is not a test dependency, so the live react path is exercised via
a stubbed planner; the fallback path is exercised for real.
"""

from __future__ import annotations

import max_agent.agent_loop as agent_loop
from max_agent.agent_loop import agentic_available
from max_agent.orchestrator import MaxAgent


def test_agentic_unavailable_without_stack_or_endpoint():
    # langgraph/databricks_langchain are not installed here, so the planner is unavailable and
    # run_agentic_answer returns None (the deterministic-only fallback).
    agent = MaxAgent()
    assert agentic_available(agent.client) is False
    assert agent_loop.run_agentic_answer(agent, {"equipment_id": "X"}, "why?") is None


def test_deterministic_only_when_no_question():
    agent = MaxAgent()
    r = agent.run("COMP-2201")
    assert r["orchestration_mode"] == "deterministic_only"
    assert r["chat_summary"]  # deterministic summary present


def test_question_without_endpoint_stays_deterministic():
    agent = MaxAgent()
    r = agent.run("COMP-2201", question="is this compressor PM ok?")
    # No endpoint bound -> planner returns None -> narration unchanged, mode stays deterministic.
    assert r["orchestration_mode"] == "deterministic_only"
    assert r["gate_status"] == "BLOCKED"


def test_rogue_narration_contradicting_gate_is_rejected(monkeypatch):
    agent = MaxAgent()

    # A rogue narration that affirms/approves a non-PASS gate must be REJECTED, not shown.
    def _stub(*_a, **_k):
        return {"narration": "This PM is fine, gate PASS, go ahead and reduce it.",
                "plan": ["governed_decision"], "mode": "llm_orchestrated"}

    monkeypatch.setattr(agent_loop, "run_agentic_answer", _stub)
    r = agent.run("COMP-2201", question="can we extend this PM?")
    # Deterministic decision unchanged AND the contradicting narration is not surfaced to the user.
    assert r["gate_status"] == "BLOCKED"
    assert r["orchestration_mode"] == "llm_narration_rejected"
    assert "go ahead" not in (r["chat_summary"] or "").lower()
    assert "gate pass" not in (r["chat_summary"] or "").lower()


def test_benign_narration_is_accepted(monkeypatch):
    agent = MaxAgent()

    def _stub(*_a, **_k):
        return {"narration": "This compressor PM is mandatory-coverage; the proposed extension is blocked and routed to governance.",
                "plan": ["governed_decision"], "mode": "llm_orchestrated"}

    monkeypatch.setattr(agent_loop, "run_agentic_answer", _stub)
    r = agent.run("COMP-2201", question="can we extend this PM?")
    assert r["orchestration_mode"] == "llm_orchestrated"
    assert r["chat_summary"].startswith("This compressor")
    assert r["gate_status"] == "BLOCKED"


def test_recommendation_is_gate_checked_and_divergence_flagged():
    # 70/10: every recommendation passes to oxy_gate_check. PUMP-4102 (Missing Evidence) -> MAX
    # recommends DATA_REMEDIATION, which differs from the scenario's RETAIN_PM change under review.
    agent = MaxAgent()
    r = agent.run("PUMP-4102")
    assert r["change_under_review_type"] == "RETAIN_PM"
    assert r["recommendation_type"] == "DATA_REMEDIATION"
    assert r["recommendation_diverges"] is True
    assert r.get("recommendation_gate_status") in {"PASS", "REVIEW_REQUIRED", "DRAFT_ONLY", "BLOCKED"}


def test_answer_threads_question_through(monkeypatch):
    agent = MaxAgent()
    seen = {}

    def _stub(_agent, result, question, thread_id="default"):
        seen["question"] = question
        seen["eid"] = result.get("equipment_id")
        return {"narration": "ok", "plan": [], "mode": "llm_orchestrated"}

    monkeypatch.setattr(agent_loop, "run_agentic_answer", _stub)
    r = agent.answer("why does this compressor keep failing?")
    assert seen["question"] == "why does this compressor keep failing?"
    assert seen["eid"] == r["equipment_id"]
    assert r["orchestration_mode"] == "llm_orchestrated"


def test_orchestration_tools_match_the_deterministic_pipeline():
    # The AI-callable tools run the REAL deterministic tools; their outputs must equal what the
    # hardcoded pipeline computes - so Sonnet calling them can never diverge from the governed result.
    import pytest
    pytest.importorskip("langchain_core")
    from max_agent.agent_tools import make_orchestration_tools
    agent = MaxAgent()
    for eid in ("PUMP-4102", "COMP-2201"):
        asset = agent._fleet_index[eid]
        state = {"time_window": "LAST_24_MONTHS"}
        tools = {t.name: t for t in make_orchestration_tools(agent, asset, state)}
        clf = tools["classify_effectiveness"].invoke({})
        rec = tools["recommend_change"].invoke({})
        gate = tools["run_oxy_gate"].invoke({})
        r = agent.run(eid)
        assert clf["label"] == r["classifier_label"]
        assert rec["type"] == r["recommendation_type"]
        assert gate["gate_status"] == r["recommendation_gate_status"]


def test_enforcer_runs_mandatory_tools_when_ai_skips_them():
    import pytest
    pytest.importorskip("langchain_core")
    from max_agent.agent_tools import enforce_mandatory
    agent = MaxAgent()
    asset = agent._fleet_index["COMP-2201"]
    state = {"time_window": "LAST_24_MONTHS"}  # AI called nothing
    out = enforce_mandatory(agent, asset, state)
    assert out["scope"] is not None
    assert out["classifier"]["label"] == "Governance Review Required"
    assert out["gate"]["gate_status"] in {"PASS", "REVIEW_REQUIRED", "BLOCKED", "DRAFT_ONLY"}


def test_agent_tools_read_governed_decision():
    # make_agent_tools needs langchain_core; skip cleanly when the agentic stack is absent.
    import pytest
    pytest.importorskip("langchain_core")
    from max_agent.agent_tools import make_agent_tools
    agent = MaxAgent()
    result = agent.run("COMP-2201")
    tools = make_agent_tools(agent, result)
    names = {t.name for t in tools}
    assert "governed_decision" in names and "evidence" in names
    gd = next(t for t in tools if t.name == "governed_decision")
    out = gd.invoke({})
    assert out["gate_status"] == "BLOCKED"  # tool reports the deterministic decision, read-only
