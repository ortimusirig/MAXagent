"""The richer FREE_FLOW lane: sub-intent routing (INFO / GATE_CHECK / APPROVAL), the advisory read-only
gate preview, and inline human-committed approvals.

Governance holds throughout: deterministic tools decide; the LLM proposes / previews; the authenticated
human commits approvals; nothing reaches SAP. The gate-check is ADVISORY (never the authoritative decision,
drafts nothing), and the inline approve/reject only SURFACES buttons - a click routes through the
deterministic approval_workflow_state.
"""

from __future__ import annotations

from max_agent.orchestrator import MaxAgent, _narration_affirms_blocked_change
from max_agent.prompts import classify_free_flow_intent_deterministic


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


# --- sub-intent classifier (deterministic floor) -----------------------------
def test_sub_intent_classifier_deterministic():
    C = classify_free_flow_intent_deterministic
    assert C("approve it", True) == "APPROVAL"
    assert C("reject this change", True) == "APPROVAL"
    assert C("can I reduce it instead?", True) == "GATE_CHECK"
    assert C("would extending pass the gate?", True) == "GATE_CHECK"
    assert C("can we skip the review?", True) == "GATE_CHECK"
    assert C("what does BLOCKED mean?", True) == "INFO"
    assert C("thanks", True) == "INFO"
    # no prior governed result -> nothing to gate-check / approve -> INFO (fail-safe)
    assert C("approve it", False) == "INFO"


# --- APPROVAL branch: lead-in only, MAX never approves ------------------------
def test_approval_branch_is_leadin_only():
    a = MaxAgent()
    last = a.run("PUMP-4110")
    ans = a.free_flow_answer("approve it", [], last, intent="APPROVAL")
    assert "buttons below" in ans
    assert "never writes SAP" in ans
    assert "cannot approve on your behalf" in ans


# --- GATE_CHECK branch: advisory, never affirms ------------------------------
def test_gate_check_is_advisory_and_grounds_the_verdict():
    a = MaxAgent()
    last = a.run("COMP-2201")  # BLOCKED
    ans = a.free_flow_answer("can I extend it?", [], last, intent="GATE_CHECK")
    assert ("preview" in ans.lower()) or ("advisory" in ans.lower())
    assert "governed review" in ans.lower()
    assert not _narration_affirms_blocked_change(ans)  # never affirms the blocked change


def test_gate_check_narration_gate_catches_an_affirming_preview():
    # A rogue gate-check draft that affirms a BLOCKED change is corrected (never shown to the user).
    a = MaxAgent(client=FakeClient([
        "Sure, go ahead and reduce it.",
        "That change is BLOCKED; a governed review is required - MAX cannot bypass it.",
    ]))
    last = MaxAgent().run("COMP-2201")
    ans = a.free_flow_answer("can I reduce it?", [], last, intent="GATE_CHECK")
    assert "go ahead" not in ans.lower()


# --- preview_gate_check tool: advisory, read-only ----------------------------
def test_preview_gate_check_tool_is_advisory_readonly():
    import pytest
    pytest.importorskip("langchain_core")
    from max_agent.agent_tools import make_gate_preview_tool
    a = MaxAgent()
    tool = make_gate_preview_tool(a, a._fleet_index["COMP-2201"])
    out = tool.invoke({"change_type": "PM_FREQUENCY_CHANGE", "direction": "EXTEND"})
    assert out["advisory"] is True
    assert out["gate_status"] in {"PASS", "REVIEW_REQUIRED", "BLOCKED", "DRAFT_ONLY"}
    assert "advisory" in out["note"].lower() and "governed" in out["note"].lower()


# --- inline approval: the human commits via the deterministic tool -----------
def test_inline_approval_routes_through_the_deterministic_tool():
    import app
    # Approving a BLOCKED asset is DENIED by approval_workflow_state (the gate blocks the transition).
    new_audit, entry, authorized = app._run_approval_action("COMP-2201", "APPROVE", "ANALYST_REVIEWED", "", [])
    assert authorized is False
    assert entry["outcome"] == "DENIED"
    assert entry["equipment_id"] == "COMP-2201"
    assert len(new_audit) == 1


def test_inline_approval_buttons_render_in_the_transcript():
    from max_agent.ui.chat import render_transcript
    msgs = [{"role": "user", "content": "approve it"},
            {"role": "assistant", "summary": "Here is the recommendation..."},
            {"role": "assistant", "kind": "approval", "equipment_id": "PUMP-4110",
             "gate_status": "REVIEW_REQUIRED", "approve_ok": True}]
    blob = str(render_transcript(msgs))
    assert "ff-approve" in blob and "ff-request" in blob and "ff-reject" in blob
    assert "PUMP-4110" in blob


def test_inline_approve_is_disabled_when_no_approval_path():
    from max_agent.ui.chat import render_inline_approval
    blob = str(render_inline_approval("COMP-2201", 2, gate_status="BLOCKED", approve_ok=False))
    assert "disabled" in blob.lower() or "not-allowed" in blob  # fail-closed at the UI (BLOCKED / DRAFT_ONLY)


def test_gate_check_forces_affirm_check_even_on_a_pass_last_result():
    # The advisory answer must never affirm ANY hypothetical, even when the last governed result was PASS -
    # the narration gate is forced on this branch so a PASS last_result cannot make it lenient.
    a = MaxAgent(client=FakeClient([
        "Yes, you can retire it - go ahead.",                       # affirms the hypothetical -> caught
        "Retiring it would NOT clear the gate; a governed review is required.",
    ]))
    last = MaxAgent().run("PUMP-4150")  # a PASS last result
    assert last["gate_status"] == "PASS"
    ans = a.free_flow_answer("would retiring it pass?", [], last, intent="GATE_CHECK")
    assert "go ahead" not in ans.lower()


# --- the TOP router now sends approval / gate-check follow-ups to FREE_FLOW ---
def test_top_router_routes_approval_and_gatecheck_to_free_flow():
    from max_agent.prompts import deterministic_intent
    # these act on the asset just analysed - free-flow (advisory preview / surface the action), not a
    # fresh governed decision:
    for q in ("approve it", "reject this change", "can I reduce it instead?", "would extending pass the gate?",
              "can we skip the review?"):
        assert deterministic_intent(q, has_last_result=True) == "FREE_FLOW", q
    # ...but a real decision ask still routes to GOVERNED, and with no prior result there is nothing to
    # approve / gate-check:
    assert deterministic_intent("should we shorten the interval?", has_last_result=True) == "GOVERNED"
    assert deterministic_intent("approve it", has_last_result=False) == "GOVERNED"


# --- free-flow now produces a READ-ONLY Artifacts-panel card (summary + detail) ---
def _ff_entry(intent="GATE_CHECK"):
    return {"n": 2, "question": "can I extend it?", "ts": "10:00", "kind": "free_flow", "intent": intent,
            "answer": "Advisory: extending is BLOCKED; run a governed review.",
            "ref": {"equipment_id": "COMP-2201", "gate_status": "BLOCKED", "gate_reason": "MANDATORY_COVERAGE",
                    "recommendation_type": "SHORTEN_INTERVAL", "evidence_lines": ["14 work orders", "coding 56%"]}}


def test_free_flow_artifact_card_shows_summary_and_grounded_detail():
    from max_agent.ui.artifact_catalog import render_free_flow_card
    blob = str(render_free_flow_card(_ff_entry("GATE_CHECK")))
    assert "Advisory gate check" in blob                       # summary header
    assert "COMP-2201" in blob and "14 work orders" in blob    # grounded detail (asset + evidence)
    assert "not the authoritative decision" in blob.lower()    # advisory framing


def test_free_flow_approval_card_notes_the_human_commit():
    from max_agent.ui.artifact_catalog import render_free_flow_card
    blob = str(render_free_flow_card(_ff_entry("APPROVAL")))
    assert "never writes SAP" in blob and "audit" in blob.lower()


def test_history_dispatches_governed_and_free_flow_entries():
    from max_agent.ui.artifact_catalog import render_artifact_history, render_trace_history
    gov = {"n": 1, "question": "review it", "ts": "09:00", "result": MaxAgent().run("COMP-2201"), "selected": []}
    hist = [gov, _ff_entry("GATE_CHECK")]
    art = str(render_artifact_history(hist, collapsed=[]))
    assert "Advisory gate check" in art                        # free-flow card rendered
    assert "COMP-2201" in art                                  # governed + free-flow cards coexist, no crash
    tr = str(render_trace_history(hist, collapsed=[]))
    assert "No governed pipeline" in tr                        # free-flow gets a read-only trace note


# --- backward-compat: an INFO follow-up still works with no intent passed ----
def test_info_followup_still_answers_without_explicit_intent():
    a = MaxAgent()
    last = a.run("PUMP-4110")
    ans = a.free_flow_answer("what does that mean?", [], last)  # classifies -> INFO
    assert ans and "PUMP-4110" in ans
