"""Unit tests for pm_effectiveness_classifier - every case from 09 "Unit Test Cases".

Label-asserting tests use the straw-man threshold set (via ``classifier_kwargs``); the
describe-and-flag test uses the shipped null-threshold profile.
"""

import copy

from max_agent.tools.classification import pm_effectiveness_classifier


def label(result):
    return result["data"]["label"]


def test_effective_when_all_attributes_pass(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs())
    assert label(result) == "Effective"


def test_needs_improvement_on_task_list_gap(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(pm_attributes={"task_list_complete": False}))
    assert label(result) == "Needs Improvement"


def test_needs_improvement_on_planned_vs_actual_variance(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        effectiveness_signals={"planned_vs_actual_variance": 0.30},  # > straw-man max 0.20
    ))
    assert label(result) == "Needs Improvement"
    assert result["data"]["needs_improvement_reason"] == "PLANNED_VS_ACTUAL_VARIANCE"


def test_ineffective_nonmandatory_failed_dimensions(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
        effectiveness_signals={
            "failure_after_pm_rate": 0.40,  # > max 0.10
            "mtbf_trend": "DECLINING",
            "repeat_failure_rate": 0.20,    # > max 0.10
        },
    ))
    assert label(result) == "Ineffective"


def test_low_findings_alone_is_not_ineffective(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        effectiveness_signals={
            "finding_rate": 0.01,           # <= low floor 0.02
            "failure_after_pm_rate": 0.03,  # healthy
            "mtbf_trend": "IMPROVING",
            "repeat_failure_rate": 0.02,
        },
    ))
    assert label(result) == "Effective"
    assert result["data"]["low_findings_guard_applied"] is True


def test_low_findings_guard_applies_to_nonmandatory(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
        effectiveness_signals={
            "finding_rate": 0.005,
            "failure_after_pm_rate": 0.02,
            "mtbf_trend": "FLAT",
            "repeat_failure_rate": 0.01,
        },
    ))
    assert label(result) != "Ineffective"
    assert result["data"]["low_findings_guard_applied"] is True


def test_governance_review_for_criticality_4(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "4", "validation_status": "VALIDATED"},
        effectiveness_signals={"finding_rate": 0.005},
    ))
    assert label(result) == "Governance Review Required"
    assert result["data"]["protection_basis"] == "CRITICALITY_MANDATE"


def test_governance_review_for_per_pm_mandatory(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
        pm_governance={"mandatory_pm": True, "mandatory_basis": "PM_HSE"},
    ))
    assert label(result) == "Governance Review Required"
    assert result["data"]["protection_basis"] == "PER_PM_MANDATORY"


def test_governance_review_for_mandatory_object_dependency(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
        pm_governance={"mandatory_pm": False, "object_dependency_code": "PM_REG"},
        effectiveness_signals={"finding_rate": 0.005},
    ))
    assert label(result) == "Governance Review Required"
    assert result["data"]["protection_basis"] == "OBJECT_DEPENDENCY_MANDATE"


def test_mandatory_never_ineffective(classifier_kwargs):
    # Mandatory PM with genuinely failed dimensions must be Governance, never Ineffective.
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "4", "validation_status": "VALIDATED"},
        effectiveness_signals={"failure_after_pm_rate": 0.9, "mtbf_trend": "DECLINING", "repeat_failure_rate": 0.9},
    ))
    assert label(result) == "Governance Review Required"
    assert label(result) != "Ineffective"


def test_missing_evidence_when_signals_null(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
        effectiveness_signals={"failure_after_pm_rate": None},
    ))
    assert label(result) == "Missing Evidence"
    assert result["data"]["missing_evidence_reason"] == "FAILURE_SIGNAL_NULL"


def test_missing_evidence_when_notification_coding_absent(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
        evidence_readiness={"notification_coding_present": False},
    ))
    assert label(result) == "Missing Evidence"
    assert result["data"]["missing_evidence_reason"] == "NOTIFICATION_CODING_ABSENT"


def test_missing_evidence_when_cost_actuals_absent_for_cost_metric(classifier_kwargs, bu_profile_thresholds_set):
    profile = copy.deepcopy(bu_profile_thresholds_set)
    profile["classifier_thresholds"]["cost_per_finding_max"] = 500.0  # label now depends on cost
    result = pm_effectiveness_classifier(**classifier_kwargs(
        bu_profile=profile,
        criticality={"code": "1", "validation_status": "VALIDATED"},
        evidence_readiness={"cost_actuals_present": False, "notification_coding_present": True},
    ))
    assert label(result) == "Missing Evidence"
    assert result["data"]["missing_evidence_reason"] == "COST_ACTUALS_ABSENT"


def test_missing_evidence_for_cbm_without_readings(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
        context={"pm_id": "PM-CBM-1", "pm_strategy_type": "CONDITION_BASED", "time_window": "LAST_24_MONTHS"},
        evidence_readiness={"measurement_readings_present": False, "notification_coding_present": True},
    ))
    assert label(result) == "Missing Evidence"
    assert result["data"]["missing_evidence_reason"] == "MEASUREMENT_READINGS_ABSENT"


def test_describe_and_flag_when_thresholds_unset(classifier_kwargs, bu_profile):
    # Shipped profile keeps thresholds null -> describe-and-flag, never a final judgment.
    result = pm_effectiveness_classifier(**classifier_kwargs(bu_profile=bu_profile))
    assert result["data"]["describe_and_flag"] is True
    assert label(result) not in ("Effective", "Ineffective")


def test_governance_precedence_over_missing_evidence(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "4", "validation_status": "VALIDATED"},
        effectiveness_signals={"failure_after_pm_rate": None},  # would be Missing Evidence if unprotected
    ))
    assert label(result) == "Governance Review Required"


def test_missing_evidence_precedence_over_ineffective(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
        effectiveness_signals={"failure_after_pm_rate": 0.40, "mtbf_trend": "DECLINING"},
        evidence_readiness={"signal_confidence": "LOW", "notification_coding_present": True},
    ))
    assert label(result) == "Missing Evidence"
    assert result["data"]["missing_evidence_reason"] == "SIGNAL_CONFIDENCE_LOW"


def test_uses_bu_profile_thresholds(classifier_kwargs, bu_profile_thresholds_set):
    label_a = label(pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "1", "validation_status": "VALIDATED"},
    )))
    profile_b = copy.deepcopy(bu_profile_thresholds_set)
    profile_b["classifier_thresholds"]["finding_rate_effective_min"] = 0.10  # 0.06 now falls below
    label_b = label(pm_effectiveness_classifier(**classifier_kwargs(
        bu_profile=profile_b,
        criticality={"code": "1", "validation_status": "VALIDATED"},
    )))
    assert label_a != label_b


def test_criticality_unvalidated_defers_to_gate(classifier_kwargs):
    result = pm_effectiveness_classifier(**classifier_kwargs(
        criticality={"code": "0", "validation_status": "NOT_VALIDATED"},
    ))
    assert label(result) == "Missing Evidence"
    assert result["data"]["missing_evidence_reason"] == "CRITICALITY_UNVALIDATED"
    assert label(result) != "Ineffective"
