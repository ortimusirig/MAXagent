"""Ask MAX portfolio route: a fleet-scope question returns the ranked at-risk list, not a single PM."""
from __future__ import annotations

from max_agent.intent import is_fleet_question


def test_fleet_questions_detected():
    for q in ["what are the PMs currently at risk?", "which pumps need attention",
              "show me the worst PMs", "fleet overview", "which ones are of concern"]:
        assert is_fleet_question(q), q


def test_specific_asset_questions_not_fleet():
    for q in ["is the PM on PUMP-4110 effective?", "review COMP-2201",
              "should I extend the interval on MOTOR-5501?"]:
        assert not is_fleet_question(q), q


def test_portfolio_answer_lists_at_risk_only():
    import app
    ans = app._portfolio_answer(app.PORTFOLIO_HEALTH.get("rows", []), "what are the PMs at risk?")
    # only non-PASS gates are listed; a cleared-to-draft PM must not appear as "at risk"
    assert "currently need attention" in ans
    assert "Cleared to draft" not in ans          # PASS gate is excluded from the at-risk list
    assert "Blocked" in ans or "Needs governance review" in ans
    assert "highest-attention first" in ans
