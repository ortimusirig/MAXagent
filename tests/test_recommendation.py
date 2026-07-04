"""Unit tests for recommend_strategy_change - every case from 10 ("recommend_strategy_change").

These safety rails prevent an unsafe recommendation from ever being formed (it still has to
clear oxy_gate_check afterwards).
"""

from max_agent.tools.recommendation import recommend_strategy_change


def rec_type(result):
    return result["data"]["recommendation"]["type"]


def test_mandatory_pm_never_recommends_reduce_retire_rtf(bu_profile):
    result = recommend_strategy_change(
        classifier_label="Governance Review Required",
        data_readiness="GREEN",
        criticality={"code": "4", "validation_status": "VALIDATED"},
        pm_governance={"mandatory_pm": False},
        readiness={"task_list_gap": True},
        bu_profile=bu_profile,
    )
    assert result["data"]["do_not_optimize"] is True
    assert rec_type(result) not in ("REDUCE_OR_RETIRE_CANDIDATE", "RETIRE_PM", "MOVE_TO_RTF")


def test_red_data_recommends_remediation_not_change(bu_profile):
    result = recommend_strategy_change(
        classifier_label="Needs Improvement",
        data_readiness="RED",
        criticality={"code": "1", "validation_status": "VALIDATED"},
        pm_governance={"mandatory_pm": False},
        readiness={},
        bu_profile=bu_profile,
    )
    assert rec_type(result) == "DATA_REMEDIATION"


def test_unvalidated_criticality_routes_to_governance(bu_profile):
    result = recommend_strategy_change(
        classifier_label="Needs Improvement",
        data_readiness="GREEN",
        criticality={"code": "0", "validation_status": "NOT_VALIDATED"},
        pm_governance={"mandatory_pm": False},
        readiness={},
        bu_profile=bu_profile,
    )
    assert rec_type(result) == "REQUEST_CRITICALITY_VALIDATION"
    assert "governance" in result["data"]["recommendation"]["next_action"].lower()


def test_add_cbm_requires_readings(bu_profile):
    result = recommend_strategy_change(
        classifier_label="Needs Improvement",
        data_readiness="GREEN",
        comparison={"suggests_cbm": True},
        criticality={"code": "1", "validation_status": "VALIDATED"},
        pm_governance={"mandatory_pm": False},
        readiness={"cbm_real_readings_available": False},
        bu_profile=bu_profile,
    )
    assert rec_type(result) == "MEASUREMENT_READINESS_FIRST"


def test_prefers_least_invasive_fix(bu_profile):
    # Even for an Ineffective PM, a task-list fix is preferred over a frequency change.
    result = recommend_strategy_change(
        classifier_label="Ineffective",
        data_readiness="GREEN",
        comparison={"suggests_frequency_change": True},
        criticality={"code": "1", "validation_status": "VALIDATED"},
        pm_governance={"mandatory_pm": False},
        readiness={"task_list_gap": True},
        bu_profile=bu_profile,
    )
    assert rec_type(result) == "IMPROVE_TASK_LIST"
