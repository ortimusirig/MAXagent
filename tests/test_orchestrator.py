"""End-to-end orchestrator tests on synthetic data (no Databricks connection).

These prove the app's pipeline drives the real deterministic tools correctly: every synthetic
asset reaches its expected gate status, scope fail-closed holds, mandatory PMs are do-not-optimize,
the null-threshold profile keeps the classifier in describe-and-flag mode, and MAX never writes SAP.
"""

import pytest

from max_agent.orchestrator import MaxAgent
from max_agent.synthetic_data import synthetic_fleet


@pytest.fixture(scope="module")
def agent():
    return MaxAgent()


def test_each_asset_hits_expected_gate_status(agent):
    for a in synthetic_fleet():
        r = agent.run(a["equipment_id"])
        assert r["gate_status"] == a["expected_gate_status"], (
            f"{a['equipment_id']}: got {r['gate_status']} ({r.get('gate_reason')})"
        )


def test_all_synthetic_no_sap_write_and_has_summary(agent):
    for a in synthetic_fleet():
        r = agent.run(a["equipment_id"])
        assert r["provenance"] == "SYNTHETIC"
        assert r["package"]["max_writes_sap"] is False
        assert r["chat_summary"]


def test_out_of_scope_yields_documentation_only(agent):
    # The scope-blocked path packages the blocked request itself -> documentation-only, no submit.
    r = agent.run("PUMP-4130")  # non-operated / JV -> out of analysis scope -> BLOCKED
    assert r["gate_status"] == "BLOCKED"
    assert r["package"]["package_type"] == "documentation_only"
    assert r["package"]["submit_path_available"] is False


def test_blocked_request_packages_max_recommendation(agent):
    # Coupling (70/10): the requested reduce is BLOCKED, but MAX recommends a safe keep-coverage
    # improvement, and the PACKAGE drafts that recommendation (gated separately, never a submit path).
    r = agent.run("COMP-2201")  # criticality-3 reduce -> requested change BLOCKED
    assert r["gate_status"] == "BLOCKED"           # the requested change is still blocked (demo)
    assert r["recommendation_diverges"] is True    # MAX recommends something other than the reduce
    assert r["package"]["package_type"] == "draft_change_package"   # package follows the recommendation
    assert r["package_gate_status"] != "BLOCKED"   # the recommendation itself is not blocked
    assert r["package"]["submit_path_available"] is False           # still no direct-submit path
    assert r["package"]["max_writes_sap"] is False


def test_scope_blocked_assets(agent):
    for eq, reason in [("PUMP-4130", "NON_OPERATED_OR_JV_OUT_OF_SCOPE"), ("PUMP-4140", "EXEMPT_ASSET_OUT_OF_SCOPE")]:
        r = agent.run(eq)
        assert r["gate_status"] == "BLOCKED"
        assert r["gate_reason"] == reason
        assert r["scope"]["in_scope"] is False


def test_mandatory_is_do_not_optimize(agent):
    r = agent.run("VALVE-3301")  # criticality-4 HSE mandatory
    assert r["do_not_optimize"] is True
    assert r["classifier_label"] == "Governance Review Required"


def test_describe_and_flag_when_thresholds_null(agent):
    r = agent.run("PUMP-4102")  # criticality-1 non-mandatory
    assert r["classifier_label"] == "Missing Evidence"  # thresholds null -> describe-and-flag


def test_attachment_k_present_and_unconfirmed(agent):
    r = agent.run("PUMP-4110")
    ak = r["package"]["attachment_k"]
    assert ak["criticality"]["code"] == "2"
    assert ak["attachment_k_confirmed"] is False
    assert r["package"]["deferred_fields"]


def test_portfolio_covers_fleet_and_all_statuses(agent):
    p = agent.portfolio()
    assert len(p) == len(synthetic_fleet())
    statuses = {row["gate_status"] for row in p}
    assert {"PASS", "REVIEW_REQUIRED", "BLOCKED", "DRAFT_ONLY"}.issubset(statuses)


def test_runs_in_local_synthetic_mode(agent):
    assert agent.client.mode() == "local_synthetic"


def test_unknown_asset_returns_error(agent):
    r = agent.run("NOPE-9999")
    assert "error" in r
