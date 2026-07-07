"""Ask MAX Artifacts HISTORY (Finance-style): every answered question stacks a collapsible card,
newest first. Only the newest card is interactive (live filter/download ids); prior cards render static
snapshots so the fixed ids never duplicate across the stack. Plus the Summary/Detailed toggle within the
work-order evidence artifact.
"""

from __future__ import annotations

from max_agent.entities import ARTIFACT_CHOICES
from max_agent.orchestrator import MaxAgent
from max_agent.ui.artifact_catalog import _RENDERERS, _evidence_table, render_artifact_history


def _ids(component, out=None):
    out = [] if out is None else out
    cid = getattr(component, "id", None)
    if cid is not None:
        out.append(repr(cid) if isinstance(cid, dict) else cid)
    ch = getattr(component, "children", None)
    if isinstance(ch, (list, tuple)):
        for x in ch:
            _ids(x, out)
    elif ch is not None:
        _ids(ch, out)
    return out


def _hist(n_entries=2):
    a = MaxAgent()
    r = a.run("PUMP-4110", question="list all work orders")
    return [{"n": i + 1, "question": f"q{i + 1}", "ts": "10:0%d:00" % i, "result": r, "selected": ["evidence_table"]}
            for i in range(n_entries)]


def test_empty_history_shows_guidance():
    # Empty state: centered icon + short contextual line (shared right-panel empty-state pattern).
    rendered = str(render_artifact_history([], []))
    assert "/assets/icons/artifacts.svg" in rendered
    assert "artifacts appear here" in rendered


def test_history_stacks_newest_first_with_headers():
    ids = _ids(render_artifact_history(_hist(3), []))
    assert sum(1 for i in ids if "arti-hdr" in str(i)) == 3  # one collapsible header per answer


def test_only_newest_card_is_interactive_no_duplicate_ids():
    ids = _ids(render_artifact_history(_hist(2), []))          # both expanded
    dups = [i for i in set(ids) if ids.count(i) > 1]
    assert not dups, f"duplicate ids across history: {dups}"
    # the fixed detail-filter ids come from the newest (live) card only
    assert any("detail-filter" in str(i) for i in ids)


def test_collapsed_card_renders_header_only():
    # collapse the newest (n=2) -> its body (and interactive ids) are not rendered
    ids = _ids(render_artifact_history(_hist(2), [2]))
    assert not any("detail-filter" in str(i) for i in ids)


def test_evidence_table_has_summary_and_detailed_toggle():
    r = MaxAgent().run("PUMP-4110", question="is this pm effective")
    s = str(_evidence_table(r, live=True))
    assert "Summary" in s and "Detailed records" in s
    # a plain effectiveness question defaults to the Summary view
    assert "value='summary'" in s.replace('"', "'")


def test_detail_intent_opens_detailed_view_by_default():
    r = MaxAgent().run("PUMP-4110", question="list all individual work orders")
    assert "value='detailed'" in str(_evidence_table(r, live=True)).replace('"', "'")


def test_catalog_has_no_detail_or_trace_artifacts():
    assert set(_RENDERERS) == set(ARTIFACT_CHOICES)
    assert "work_order_detail" not in ARTIFACT_CHOICES  # folded into evidence_table's Detailed tab
    assert "notification_detail" not in ARTIFACT_CHOICES
    assert "gate_trace" not in ARTIFACT_CHOICES          # moved to the dedicated Governance Trace tab


def test_governance_trace_shows_everything_that_ran():
    from max_agent.ui.artifacts import render_governance_trace
    r = MaxAgent().run("PUMP-4110", question="is this pm effective")
    s = str(render_governance_trace(r))
    assert "Governance summary" in s                     # gate / label / approvers / scope
    assert "Tool Trace" in s                              # the model plan + full deterministic tool table
    assert "Scoped SQL" in s and "SELECT" in s           # the real queries that fetched the evidence
    assert "does not write SAP" in s                     # draft-only stance is on the audit view


def test_governance_trace_history_stacks_independently():
    from max_agent.ui.artifact_catalog import render_trace_history
    r = MaxAgent().run("PUMP-4110", question="is this pm effective")
    hist = [{"n": i + 1, "question": f"q{i + 1}", "ts": "10:0%d" % i, "result": r, "selected": []} for i in range(2)]
    ids = _ids(render_trace_history(hist, []))
    assert sum(1 for i in ids if "trace-hdr" in str(i)) == 2   # its own header id namespace (not arti-hdr)
    assert not any("arti-hdr" in str(i) for i in ids)


def test_out_of_scope_trace_flags_the_scope_block():
    from max_agent.ui.artifacts import render_governance_trace
    r = MaxAgent().run("PUMP-4130")  # non-operated / JV -> out of analysis scope
    s = str(render_governance_trace(r))
    assert "OUT OF SCOPE" in s           # the governance summary flags the fail-closed scope block
    assert "Governance summary" in s
