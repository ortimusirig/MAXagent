"""Live-progress instrumentation: the deterministic governed pipeline and the free-flow lane emit an
ordered per-tool checklist via on_step. These are DISPLAY-ONLY signals - they never change any decision,
gate, scope, or narration - so the tests assert both the emitted sequence AND that the result is identical
with or without the callback.

Regression guard for the refactor-orphan bug: when the governed LLM tool-loop was replaced by the
deterministic _run_asset pipeline, per-tool on_step emission was dropped (only "synthesizing" survived),
so the UI showed only "thinking -> synthesizing". These tests pin the re-instrumented stages.
"""

from __future__ import annotations

from max_agent.orchestrator import MaxAgent
from max_agent.ui.chat import STEP_LABELS


def _recorder():
    steps = []
    return steps, (lambda key: steps.append(key))


# --- governed lane: fixed pipeline stages, in order, ending in synthesizing -------------------------
def test_governed_run_emits_ordered_stage_checklist():
    steps, on_step = _recorder()
    MaxAgent().run("PUMP-4110", question="Is the PM on PUMP-4110 effective?", on_step=on_step)
    assert steps == [
        "lock_scope", "retrieve_evidence", "classify_effectiveness", "check_data_readiness",
        "recommend_change", "run_oxy_gate", "execution_readiness", "compare_like_equipment",
        "reliability_evidence", "synthesizing",
    ]


def test_out_of_scope_run_short_circuits_the_checklist():
    # An out-of-scope asset must not emit the evidence/classify stages - scope stays authoritative, and the
    # progress stream proves it (only scope + gate + synthesizing fire).
    steps, on_step = _recorder()
    MaxAgent().run("PUMP-4130", question="Review PUMP-4130.", on_step=on_step)
    assert steps == ["lock_scope", "run_oxy_gate", "synthesizing"]
    assert "retrieve_evidence" not in steps and "classify_effectiveness" not in steps


def test_browsing_without_a_question_emits_no_synthesizing():
    # Selecting an asset (no question) runs the deterministic pipeline but never the narration step.
    steps, on_step = _recorder()
    MaxAgent().run("PUMP-4110", on_step=on_step)
    assert steps[0] == "lock_scope" and "synthesizing" not in steps


# --- display-only invariant: the callback changes nothing ------------------------------------------
def test_on_step_is_display_only_and_changes_no_decision():
    a = MaxAgent()
    without = a.run("PUMP-4110", question="Review it.")
    steps, on_step = _recorder()
    with_cb = a.run("PUMP-4110", question="Review it.", on_step=on_step)
    for field in ("classifier_label", "gate_status", "recommendation_type", "do_not_optimize"):
        assert without.get(field) == with_cb.get(field)
    assert steps  # the callback did fire


# --- free-flow lane: every selectable tool + the group header has a friendly label ------------------
def test_step_labels_cover_every_free_flow_tool_and_the_group_header():
    # run_free_flow_agent emits on_step(tool_name) per selected tool + "planning" per turn; every key must
    # resolve to a phrase so no raw tool name ever shows in the checklist.
    required = {
        "planning", "synthesizing",
        # make_agent_tools read-only set (tools the model may select)
        "governed_decision", "evidence", "like_equipment_comparison", "execution_readiness",
        "reliability", "parts_bom", "reliability_drift", "cost_distribution", "portfolio_health",
        # advisory GATE_CHECK sub-intent tool
        "preview_gate_check",
    }
    missing = required - set(STEP_LABELS)
    assert not missing, f"STEP_LABELS missing free-flow keys: {sorted(missing)}"


def test_free_flow_answer_accepts_on_step_without_error_offline():
    # Offline (no LLM bound) free-flow falls back deterministically; passing on_step must not crash and the
    # answer must still be produced.
    a = MaxAgent()
    last = a.run("PUMP-4110", question="Review it.")
    steps, on_step = _recorder()
    ans = a.free_flow_answer("What does DRAFT_ONLY mean?", messages=[], last_result=last,
                             intent="INFO", on_step=on_step)
    assert isinstance(ans, str) and ans
