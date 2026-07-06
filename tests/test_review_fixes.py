"""Regression tests for the three review fixes (wrong approval gate, ungated preview narration,
out-of-scope free-flow evidence).

Each test pins the corrected behavior so a future change cannot silently reintroduce the defect. The
governance invariants are preserved: deterministic tools DECIDE, the LLM only narrates, scope is
authoritative and fail-closed, and nothing reaches SAP.
"""

from __future__ import annotations

import pytest

from max_agent.orchestrator import MaxAgent
from max_agent.tools import genie_query_scoped


class _StubClient:
    """A bound client for tests.

    - ``llm_complete`` returns scripted replies in order (then ""), recording every prompt in ``calls``
      so narration-gate round-trips can be counted.
    - Genie is toggleable; ``genie_query`` records the scoped params it is handed in ``genie_received``,
      so a test can prove an out-of-scope asset never triggers a bound read.
    """

    def __init__(self, replies=None, genie_bound=False):
        self._replies = list(replies or [])
        self._genie_bound = genie_bound
        self.calls = []
        self.genie_received = None

    def llm_bound(self):
        return True

    def llm_complete(self, prompt, system=None):
        self.calls.append(prompt)
        return self._replies.pop(0) if self._replies else ""

    def mode(self):
        return "synthetic"

    def sql_executor(self):
        return None

    def genie_bound(self):
        return self._genie_bound

    def genie_query(self, question, scoped_params):
        self.genie_received = scoped_params
        # A safe, scoped, allowlisted SELECT so the safety guard would pass and rows would surface IF this
        # were ever reached - it must NOT be, for an out-of-scope asset.
        return {"conversation_id": "conv-1",
                "generated_sql": "SELECT order_type FROM v_work_order_history WHERE equipment_id = :equipment_id",
                "records": [{"x": 1}], "referenced_relations": ["v_work_order_history"]}


# 1. Approval is gated on the PACKAGE (recommendation) gate, not the change-under-review gate.
def test_approval_is_gated_on_the_package_gate_not_the_change_gate(monkeypatch):
    """The package drafts MAX's recommendation, so approval must follow package_gate_status. Binding to the
    change gate FAILS OPEN when it is more permissive (PUMP-4102: change PASS vs package REVIEW_REQUIRED)."""
    import app as app_module
    from max_agent import tools as max_tools

    real = max_tools.approval_workflow_state
    seen = {}

    def _spy(**kwargs):
        seen["gate_status"] = kwargs.get("gate_status")
        return real(**kwargs)

    # _run_approval_action does `from max_agent.tools import approval_workflow_state` at call time, so
    # patching the module attribute is picked up. The orchestrator keeps its own binding (real function),
    # so the internal governed run is unaffected - the spy captures ONLY the app-layer approval call.
    monkeypatch.setattr(max_tools, "approval_workflow_state", _spy)

    r = app_module.agent.run("PUMP-4102")
    assert r["gate_status"] == "PASS"                       # the requested-change gate (permissive)
    assert r["package_gate_status"] == "REVIEW_REQUIRED"    # the recommendation/package gate (stricter)
    assert r["gate_status"] != r["package_gate_status"]     # the two gates genuinely diverge here

    app_module._run_approval_action("PUMP-4102", "APPROVE", "ANALYST_REVIEWED", "", [])
    assert seen["gate_status"] == r["package_gate_status"]  # bound to the PACKAGE gate
    assert seen["gate_status"] != r["gate_status"]          # never the more-permissive change gate (fail-open)


# 2. The preview narration is routed through the shared narration gate (may explain, never affirm non-PASS).
def test_preview_narrative_routes_through_the_narration_gate():
    """On a BLOCKED asset a first preview draft that AFFIRMS the change is caught and corrected by ONE
    re-prompt - approving language never reaches the preview panel."""
    agent = MaxAgent(client=_StubClient([
        "This is approved - go ahead and reduce it.",                                # AFFIRMS -> caught
        "The change is blocked and routed to a governance review; the reviewer decides next.",  # clean
    ]))
    r = agent.run("COMP-2201")                       # BLOCKED; run() with no question does NOT narrate
    assert r["gate_status"] == "BLOCKED"
    assert agent.client.calls == []                  # sanity: the plain governed run consumed no LLM calls

    text = agent.preview_narrative(r, concise=True)
    assert "go ahead" not in text.lower()
    assert text.startswith("The change is blocked")
    assert len(agent.client.calls) == 2              # first draft + ONE corrective re-prompt


def test_preview_narrative_falls_back_to_preview_summary_when_both_drafts_affirm():
    """When both drafts affirm, the circuit breaker returns the deterministic preview_summary - the LLM
    can never talk its way past the gate on the preview surface."""
    from max_agent.prompts import preview_summary
    agent = MaxAgent(client=_StubClient([
        "Approved: go ahead and reduce it.",
        "Sure, you can reduce it right now.",
    ]))
    r = agent.run("COMP-2201")
    text = agent.preview_narrative(r, concise=True)
    assert "go ahead" not in text.lower() and "you can reduce" not in text.lower()
    assert text == preview_summary(r, concise=True)  # deterministic fallback wins the tie


# 3a. genie_query_scoped fails closed on an out-of-scope asset, even with a bound Genie space.
def test_genie_query_scoped_fails_closed_when_out_of_scope():
    client = _StubClient(genie_bound=True)           # a BOUND Genie space...
    scope = {"equipment_id": "PUMP-4130", "time_window": "LAST_24_MONTHS",
             "scope_validated": True, "in_scope": False}    # ...but the asset is out of analysis scope
    env = genie_query_scoped("why so many failures?", scope, client=client)
    d = env["data"]
    assert d["genie_bound"] is False                 # no scoped read is attempted
    assert d["records"] == []
    assert d["sql_validation"]["status"] == "NOT_RUN_OUT_OF_SCOPE"
    assert env["blocked_reason"] == "OUT_OF_ANALYSIS_SCOPE"
    assert client.genie_received is None             # the bound Genie client was NEVER queried

    # In-scope (in_scope True) still delegates to the bound client -> proves the guard is scoped to False only.
    ok = genie_query_scoped(
        "q", {"equipment_id": "PUMP-4110", "time_window": "LAST_24_MONTHS",
              "scope_validated": True, "in_scope": True}, client=_StubClient(genie_bound=True))
    assert ok["data"]["genie_bound"] is True


# 3b. The free-flow evidence() tool forwards in_scope, so it inherits the same out-of-scope guard.
def test_free_flow_evidence_on_out_of_scope_result_never_runs_a_bound_read():
    pytest.importorskip("langchain_core")
    from max_agent.agent_tools import make_agent_tools

    client = _StubClient(genie_bound=True)
    agent = MaxAgent(client=client)
    last = agent.run("PUMP-4130")                    # JV, out of analysis scope
    assert last["scope"]["in_scope"] is False
    assert client.genie_received is None             # the governed run itself reads no scoped evidence

    evidence = next(t for t in make_agent_tools(agent, last) if t.name == "evidence")
    out = evidence.invoke({"question": "how many corrective work orders?"})
    assert not out["genie_rows"]                     # 0 rows
    assert out["genie_bound"] in (False, None)       # bound Genie was not run for an out-of-scope asset
    assert client.genie_received is None             # fail-closed: the bound client was never queried
