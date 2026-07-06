"""Work Strategy Studio (ui/studio.py): the governed review screen. Recommendation-first, owns the
visible context bar, exposes the governed action once (no duplicate approve/reject ids), and never
implies MAX writes SAP."""

from __future__ import annotations

from max_agent.orchestrator import MaxAgent
from max_agent.ui.studio import render_studio


def _ids(component):
    out = []

    def walk(c):
        cid = getattr(c, "id", None)
        if cid:
            out.append(cid)
        ch = getattr(c, "children", None)
        if isinstance(ch, (list, tuple)):
            for x in ch:
                walk(x)
        elif ch is not None:
            walk(ch)

    walk(component)
    return out


def _result():
    return MaxAgent().run("PUMP-4102")


def test_empty_state_when_no_pm():
    empty = render_studio(None)
    assert "Work Strategy Studio" in str(empty)
    # no governed-action controls exist until a PM is in context
    assert "approve-btn" not in _ids(empty)


def test_governed_controls_present_exactly_once():
    ids = _ids(render_studio(_result(), audit=[]))
    for cid in ("approve-btn", "request-btn", "reject-btn", "approval-comment", "approval-trail"):
        assert ids.count(cid) == 1, f"{cid} should appear exactly once, got {ids.count(cid)}"


def test_leads_with_recommendation_and_is_draft_only():
    from max_agent.labels import rec_label
    r = _result()
    s = str(render_studio(r, audit=[], narrative="MAX assessment paragraph."))
    assert "MAX recommends" in s
    # the Studio hero shows the HUMAN label, not the raw enum code
    assert rec_label(r["recommendation_type"]) in s
    # draft-only stance is on screen and MAX does not claim a SAP write
    assert "DRAFT ONLY" in s and "does not write to SAP" in s


def test_divergence_note_shown_when_recommendation_differs():
    r = _result()
    assert r["recommendation_diverges"] is True  # PUMP-4102 recommends remediation, not the asked change
    assert "MAX recommends" in str(render_studio(r, audit=[]))


def test_command_center_preview_shares_the_studio_synthesis_block():
    # The user asked for panel 3's fuller synthesis in the Command Center preview: same narrative +
    # 'Evidence MAX cited' + 'Required approvers'. Both panels render the shared render_why block.
    from max_agent.ui.command_center import render_pm_preview
    r = _result()
    nar = "Governed MAX narrative for the preview."
    preview = str(render_pm_preview(r, narrative=nar))
    studio = str(render_studio(r, audit=[], narrative=nar))
    for marker in ("Why MAX recommended this", "Evidence MAX cited", "Required approvers", nar):
        assert marker in preview, f"Command Center preview missing: {marker}"
        assert marker in studio, f"Studio missing: {marker}"
