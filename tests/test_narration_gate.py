"""The ONE shared narration gate (governed narration + free-flow).

The model may EXPLAIN a gate; it may never AFFIRM a non-PASS one - whichever path wrote the sentence.
Gate: clean/ PASS -> show the model answer; affirms a non-PASS change -> ONE corrective re-prompt ->
re-check; still affirms / empty -> deterministic template (circuit breaker). Ties go to the deterministic
layer. orchestration_mode is only ever 'deterministic_only' or 'llm_narrated'.
"""

from __future__ import annotations

from max_agent.orchestrator import MaxAgent, _narration_affirms_blocked_change


class FakeClient:
    """A bound client whose llm_complete returns scripted replies in order (then '')."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

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
        return False

    def genie_query(self, *a, **k):
        return {}


# --- the detector itself -----------------------------------------------------
def test_detector_fires_on_real_approval_not_on_routing_or_definitions():
    assert _narration_affirms_blocked_change("Approved - go ahead and reduce it.") is True
    assert _narration_affirms_blocked_change("You can retire this PM now.") is True
    assert _narration_affirms_blocked_change("The change is approved.") is True
    # legit non-PASS language must NOT fire (would needlessly cost a corrective round-trip)
    assert _narration_affirms_blocked_change("This change is blocked; proceed with a governance review.") is False
    assert _narration_affirms_blocked_change("'Cleared to draft' means the change may be drafted for review.") is False
    assert _narration_affirms_blocked_change("The extension must be approved by the Work Strategy Owner first.") is False


# --- (a) governed, BLOCKED, first draft affirms, corrective is clean ---------
def test_governed_blocked_corrected_after_one_reprompt():
    agent = MaxAgent(client=FakeClient([
        "This is approved, go ahead and reduce it.",                       # first draft AFFIRMS -> caught
        "The extension is blocked and routed to a governance review; the reviewer decides next.",  # clean
    ]))
    r = agent.run("COMP-2201", question="can we extend this PM?")
    assert r["gate_status"] == "BLOCKED"
    assert r["orchestration_mode"] == "llm_narrated"              # corrected model text, still LLM
    assert r["chat_summary"].startswith("The extension is blocked")
    assert "go ahead" not in r["chat_summary"].lower()
    assert len(agent.client.calls) == 2                          # narration + ONE corrective


# --- (b) governed, BLOCKED, BOTH drafts affirm -> deterministic template -----
def test_governed_blocked_both_drafts_affirm_fall_to_template():
    agent = MaxAgent(client=FakeClient([
        "Approved: go ahead and reduce it.",
        "Sure, you can reduce it right now.",
    ]))
    r = agent.run("COMP-2201", question="can we extend this PM?")
    assert r["orchestration_mode"] == "deterministic_only"        # circuit breaker
    assert r["gate_status"] == "BLOCKED"
    assert "go ahead" not in r["chat_summary"].lower()
    assert "you can reduce" not in r["chat_summary"].lower()


# --- (c) governed, PASS gate -> affirming language allowed, no correction ----
def test_governed_pass_gate_keeps_affirming_language():
    agent = MaxAgent(client=FakeClient(["Looks good - safe to reduce it if you like."]))
    r = agent.run("PUMP-4150", question="is this pm fine?")
    assert r["gate_status"] == "PASS"
    assert r["orchestration_mode"] == "llm_narrated"
    assert r["chat_summary"] == "Looks good - safe to reduce it if you like."
    assert len(agent.client.calls) == 1                          # PASS short-circuits, no corrective


# --- (d) free-flow on a BLOCKED last_result, draft affirms -------------------
def test_free_flow_blocked_last_result_is_guarded():
    last = MaxAgent().run("COMP-2201")                           # a BLOCKED governed result to ground on
    agent = MaxAgent(client=FakeClient([
        "Yes, go ahead and reduce it.",                          # affirms -> caught
        "That change is blocked; a reviewer must sign off before anything changes.",  # clean
    ]))
    ans = agent.free_flow_answer("can I just reduce it?", [], last)
    assert "go ahead" not in ans.lower()
    assert ans.startswith("That change is blocked")


def test_free_flow_both_drafts_affirm_fall_to_deterministic():
    last = MaxAgent().run("COMP-2201")
    agent = MaxAgent(client=FakeClient([
        "Go ahead and reduce it.",
        "You can retire it now.",
    ]))
    ans = agent.free_flow_answer("can I just reduce it?", [], last)
    assert "go ahead" not in ans.lower() and "you can retire" not in ans.lower()


# --- (e) router: a verbose reply falls to GOVERNED (safe direction) ----------
def test_router_verbose_reply_classifies_governed():
    agent = MaxAgent(client=FakeClient(["GOVERNED, not FREE_FLOW"]))
    assert agent.classify_intent("should we extend it?", [], has_last_result=True) == "GOVERNED"


def test_router_freeflow_prefix_classifies_free_flow():
    agent = MaxAgent(client=FakeClient(["FREE_FLOW - it's a follow-up"]))
    assert agent.classify_intent("what does that mean?", [], has_last_result=True) == "FREE_FLOW"
