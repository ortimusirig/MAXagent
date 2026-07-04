"""Unit tests for data_readiness_gate - every case from 10 ("data_readiness_gate")."""

from max_agent.tools.classification import data_readiness_gate


def dr(result):
    return result["data"]["data_readiness"]


def test_green_when_required_domains_complete():
    result = data_readiness_gate(
        "PM_EFFECTIVENESS_CLASSIFICATION",
        {"equipment": "GREEN", "pm_plans": "GREEN", "work_orders": "GREEN", "task_lists": "GREEN"},
    )
    assert dr(result) == "GREEN"
    assert result["data"]["action"] == "allowed"


def test_yellow_when_partial_but_scorable():
    result = data_readiness_gate(
        "PM_EFFECTIVENESS_CLASSIFICATION",
        {"equipment": "GREEN", "pm_plans": "YELLOW", "work_orders": "GREEN", "task_lists": "GREEN"},
    )
    assert dr(result) == "YELLOW"
    assert result["data"]["action"] == "down_ranked"


def test_red_when_required_domain_missing():
    result = data_readiness_gate(
        "PM_EFFECTIVENESS_CLASSIFICATION",
        {"equipment": "GREEN", "pm_plans": "GREEN", "work_orders": "MISSING", "task_lists": "GREEN"},
    )
    assert dr(result) == "RED"
    assert "work_orders" in result["data"]["missing_domains"]


def test_cbm_red_without_reading_timeseries():
    result = data_readiness_gate(
        "CBM",
        {"measurement_points": "GREEN", "characteristic_unit": "GREEN", "recent_readings": "MISSING"},
    )
    assert dr(result) == "RED"  # point master alone is not enough; fail closed


def test_frequency_change_requires_risk_and_failure_domains():
    result = data_readiness_gate(
        "PM_FREQUENCY_CHANGE",
        {
            "pm_plans": "GREEN",
            "work_orders": "GREEN",
            "notifications_failures": "MISSING",
            "risk_scorecard": "MISSING",
            "criticality": "GREEN",
        },
    )
    assert dr(result) == "RED"
    assert "risk_scorecard" in result["data"]["missing_domains"]
    assert "notifications_failures" in result["data"]["missing_domains"]
