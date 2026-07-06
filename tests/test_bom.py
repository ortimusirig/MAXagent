"""Parts / BOM-completeness evidence (tool 28) + its ADD_COMPONENT feed.

pm_bom_completeness compares THIS PM's linked components to like equipment and flags missing ones. It
is EVIDENCE ONLY: a gap FEEDS the deterministic ADD_COMPONENT recommendation (a keep-coverage
improvement) but never changes the classifier label or the gate, and it fails closed with too few peers.
"""

from __future__ import annotations

import pytest

from max_agent.orchestrator import MaxAgent
from max_agent.tools import pm_bom_completeness
from max_agent.tools.recommendation import REC_ADD_COMPONENT, _least_invasive_keep_coverage


def _rows(*codes_linked):
    """Build target v_bom rows: each entry (code, linked?)."""
    return [{"component_code": c, "on_pm_task_list": linked} for c, linked in codes_linked]


def _cohort(*linked_lists):
    return [{"equipment_id": f"PEER-{i}", "linked": list(l)} for i, l in enumerate(linked_lists)]


def test_bom_complete_has_no_gap():
    target = _rows(("A", True), ("B", True), ("C", True))
    cohort = _cohort(["A", "B", "C"], ["A", "B", "C"], ["A", "B"])  # A,B,C all majority
    d = pm_bom_completeness(target, cohort)["data"]
    assert d["computable"] is True
    assert d["bom_completeness"] == "COMPLETE"
    assert d["component_gap"] is False
    assert d["components_missing"] == []


def test_bom_gap_flags_missing_and_sets_component_gap():
    target = _rows(("A", True), ("B", True))                       # links A,B
    cohort = _cohort(["A", "B", "C", "D"], ["A", "B", "C", "D"], ["A", "C", "D"])  # expected A,C,D
    d = pm_bom_completeness(target, cohort)["data"]
    assert d["bom_completeness"] == "GAPS"
    assert d["component_gap"] is True
    assert set(d["components_missing"]) == {"C", "D"}
    assert 0.0 <= d["coverage_pct"] <= 1.0


def test_bom_fails_closed_with_too_few_peers():
    d = pm_bom_completeness(_rows(("A", True)), _cohort(["A", "B"]))["data"]  # only 1 peer < min 3
    assert d["computable"] is False
    assert d["bom_completeness"] == "NOT_COMPARABLE"
    assert d["component_gap"] is False
    assert d["data_needed"]  # names the SAP data still needed, never a fabricated gap


def test_bom_evidence_only_no_invented_threshold():
    d = pm_bom_completeness(_rows(("A", True)), _cohort(["A"], ["A"], ["A"]))["data"]
    # structural majority parameter, synthetic-flagged; no Oxy policy value, no RAG colour in the data
    assert d["min_prevalence"] == 0.5
    assert d["synthetic_flag"] is True
    assert "RED" not in str(d) and "YELLOW" not in str(d) and "GREEN" not in str(d)


def test_component_gap_feeds_add_component():
    # The deterministic recommendation picks ADD_COMPONENT when there is a component gap and the task
    # list is otherwise clean (least-invasive keep-coverage order: data -> task list -> component).
    assert _least_invasive_keep_coverage({"task_list_readiness": "GREEN", "component_gap": True}, {}) == REC_ADD_COMPONENT


def test_orchestrator_pump4150_recommends_add_component():
    r = MaxAgent().run("PUMP-4150")
    assert r["bom_completeness"]["component_gap"] is True
    assert set(r["bom_completeness"]["components_missing"]) == {"IMPELLER", "COUPLING"}
    assert r["recommendation_type"] == "ADD_COMPONENT"      # the BOM gap fed the recommendation
    assert r["gate_status"] == "PASS"                        # the change under review is a plain retain


def test_orchestrator_pump4110_shows_bom_gap_but_does_not_override_recommendation():
    r = MaxAgent().run("PUMP-4110")
    assert r["bom_completeness"]["bom_completeness"] == "GAPS"      # BOM gap is visible as evidence
    assert "IMPELLER" in r["bom_completeness"]["components_missing"]
    assert r["recommendation_type"] == "IMPROVE_TASK_LIST"          # task-list fix precedes ADD_COMPONENT
    # the gap does not move the gate/label
    assert r["gate_status"] == "REVIEW_REQUIRED"


def test_bom_gap_shows_in_the_evidence_digest():
    r = MaxAgent().run("PUMP-4150")
    joined = " ".join((r.get("evidence_digest") or {}).get("lines") or [])
    assert "Spare parts / BOM" in joined and "IMPELLER" in joined


def test_out_of_scope_asset_has_no_bom_read():
    # scope short-circuit runs before the BOM step, so out-of-scope assets never expose components
    r = MaxAgent().run("PUMP-4130")  # JV, out of analysis scope
    assert "bom_completeness" not in r


def test_parts_bom_read_tool_registered_when_stack_present():
    # The BOM evidence is exposed to free-flow as the READ-ONLY parts_bom tool (reads the frozen result);
    # no decide-tool / write-tool is reachable from the read-only set.
    pytest.importorskip("langchain_core")
    from max_agent.agent_tools import make_agent_tools
    a = MaxAgent()
    r = a.run("PUMP-4150")
    read_names = {t.name for t in make_agent_tools(a, r)}
    assert "parts_bom" in read_names
    for banned in ("run_oxy_gate", "recommend_change", "draft_sap_change_package", "approval_workflow_state"):
        assert banned not in read_names
