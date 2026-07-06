"""Evidence-first chat + SAP data-needs (evidence.py + prompts.deterministic_summary).

The chat must (a) explain the data behind the recommendation and (b) when the data is not enough to
conclude, name the SPECIFIC Oxy SAP data needed - grounded in the Project Soar extract. No invented
numbers; fail-closed and do-not-invent stay intact.
"""

from __future__ import annotations

from max_agent.evidence import REASON_SAP, build_evidence_digest, data_needs, is_insufficient
from max_agent.orchestrator import MaxAgent


def test_digest_cites_only_computed_workorder_counts():
    a = MaxAgent()
    r = a.run("PUMP-4102")
    d = r["evidence_digest"]
    assert d["work_orders_total"] > 0
    # the total is exactly the sum of the per-type records - nothing invented
    assert d["work_orders_total"] == sum(d["work_orders_by_type"].values())
    assert any("Work-order history" in line for line in d["lines"])


def test_digest_lines_are_present_on_the_result_for_the_chat():
    a = MaxAgent()
    r = a.run("PUMP-4102", question="is this pm effective?")
    assert r["evidence_digest"]["lines"]           # attached for the chat
    assert "data_needs" in r


def test_missing_evidence_asset_lists_data_needs():
    a = MaxAgent()
    r = a.run("PUMP-4102")
    assert r["classifier_label"] == "Missing Evidence"
    assert is_insufficient(r)
    needs = r["data_needs"]
    assert needs, "an insufficient-data asset must say what data is needed"
    # shipped profile has null thresholds -> the honest need is the Oxy threshold decision
    assert any("threshold" in n["need"].lower() for n in needs)


def test_data_needs_maps_missing_domains_to_real_soar_sap_sources():
    # A RED-readiness state with missing SAP domains names the real Project Soar sheets/columns.
    result = {
        "classifier_label": "Missing Evidence", "data_readiness": "RED",
        "classifier_reason": "NOTIFICATION_CODING_ABSENT",
        "missing_domains": ["notifications_failures", "recent_readings", "measurement_points"],
    }
    needs = data_needs(result)
    sources = " ".join(n["sap_source"] for n in needs)
    assert "Notifications" in sources          # Damage_Code / Cause_Code
    assert "Measurement Points" in sources     # condition readings
    # the classifier reason's own need is included too
    assert any(n["need"] == REASON_SAP["NOTIFICATION_CODING_ABSENT"]["need"] for n in needs)
    # every need names a source and is deduped
    assert all(n.get("sap_source") for n in needs)
    assert len({(n["need"], n["sap_source"]) for n in needs}) == len(needs)


def test_confident_or_out_of_scope_has_no_data_needs():
    assert data_needs({"classifier_label": "Effective", "data_readiness": "GREEN"}) == []
    assert data_needs({"classifier_label": "Not classified (out of analysis scope)"}) == []


def test_empty_evidence_digest_is_safe():
    d = build_evidence_digest({"evidence": {}, "time_window": "LAST_24_MONTHS"})
    assert d["work_orders_total"] == 0
    assert d["lines"] == []


def test_deterministic_summary_is_evidence_first_and_names_sap_when_insufficient():
    a = MaxAgent()
    r = a.run("PUMP-4102", question="is this pm effective, should anything change?")
    s = r["chat_summary"]
    assert "What the data shows" in s
    assert "Work-order history" in s
    assert "Not enough data to conclude" in s
    # honest cost view: no realized-savings claim is made
    assert "no labor-savings" in s.lower()


def test_preview_summary_is_a_governed_paragraph():
    from max_agent.prompts import preview_summary
    r = MaxAgent().run("PUMP-4102")
    p = preview_summary(r)
    # one flowing paragraph (no line breaks, no markdown headers/bullets), grounded on the deterministic
    # result, and never contradicting the draft-only stance.
    assert "\n" not in p and "**" not in p
    assert r["classifier_label"] in p and r["gate_status"] in p
    assert "does not write SAP" in p


def test_no_rag_color_code_in_prose_or_llm_prompt():
    # The RAG code (GREEN/YELLOW/RED) drives the UI badge, but it must never appear as a bare token in the
    # narrative prose or in the prompt handed to the LLM - it reads robotic. Readiness is described in words.
    import re
    from max_agent.prompts import preview_summary, preview_narration_prompt, narration_prompt
    rag = re.compile(r"\b(YELLOW|GREEN|RED|AMBER)\b")  # word-bounded so REQUIRED/REVIEW_REQUIRED don't match
    a = MaxAgent()
    for eid in ("PUMP-4110", "PUMP-4102", "COMP-2201"):
        r = a.run(eid, question="is this pm effective?")
        for txt in (preview_summary(r, concise=True), preview_summary(r, concise=False),
                    preview_narration_prompt(r), preview_narration_prompt(r, concise=True), narration_prompt(r)):
            assert not rag.search(txt), f"RAG code leaked into prose/prompt for {eid}: {rag.search(txt).group()}"
    # readiness is still conveyed, just in plain language
    assert "data readiness is" in preview_narration_prompt(a.run("PUMP-4110"))


def test_concise_preview_is_shorter_but_still_governed():
    from max_agent.prompts import preview_summary
    r = MaxAgent().run("PUMP-4110")
    full = preview_summary(r, concise=False)
    brief = preview_summary(r, concise=True)
    assert len(brief.split()) < 0.65 * len(full.split())     # meaningfully shorter (~half)
    # still a governed single paragraph that names the label + gate and holds the draft-only line
    assert "\n" not in brief and "**" not in brief
    assert r["classifier_label"] in brief and r["gate_status"] in brief
    assert "does not write SAP" in brief


def test_preview_narrative_falls_back_to_deterministic_without_llm():
    # No serving endpoint is bound in the test env, so agent.preview_narrative degrades to preview_summary.
    a = MaxAgent()
    r = a.run("COMP-2201")
    assert a.preview_narrative(r) == __import__("max_agent.prompts", fromlist=["preview_summary"]).preview_summary(r)
    assert a.preview_narrative({"error": "x"}) == ""
