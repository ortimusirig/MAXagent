"""Shared fixtures for the deterministic-core tests.

The BU profile shipped in ``default_oxy.yaml`` keeps ``classifier_thresholds`` and
``moc_threshold`` null (Oxy owns those values). Tests that must assert a concrete classifier
label therefore inject a CLEARLY-LABELED STRAW-MAN threshold set - it lives only in the tests,
never in the shipped profile, exactly as 09 requires ("runs first against the PROPOSED
candidate bands ... re-run once Oxy confirms the values").
"""

from __future__ import annotations

import copy
import os
import sys

import pytest

# Make the app package importable without installation.
_APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from max_agent.config import load_bu_profile  # noqa: E402


# --- Straw-man classifier thresholds (TEST-ONLY; not Oxy policy) ---------------
# PROPOSED Applexus candidate bands so the label-asserting tests are deterministic.
# These are NOT written into the shipped default_oxy.yaml.
STRAW_MAN_CLASSIFIER_THRESHOLDS = {
    "status": "PROPOSED - Applexus straw-man (TEST ONLY; workshop to confirm B1)",
    "failure_after_pm_rate_max": 0.10,
    "mtbf_improvement_min": 0.0,
    "repeat_failure_rate_max": 0.10,
    "finding_rate_effective_min": 0.05,
    "finding_rate_low_floor": 0.02,
    "pm_to_corrective_ratio_band": [1.0, 5.0],
    "cost_per_finding_max": None,  # labor cost actuals unavailable -> cost not scored
    "planned_vs_actual_variance_max": 0.20,
    "evidence_confidence_floor": 0.50,
}


@pytest.fixture
def bu_profile():
    """The shipped default_oxy profile (classifier_thresholds / moc_threshold stay null)."""
    return load_bu_profile("default_oxy")


@pytest.fixture
def bu_profile_thresholds_set(bu_profile):
    """default_oxy with the straw-man classifier thresholds applied (TEST-ONLY)."""
    profile = copy.deepcopy(bu_profile)
    profile["classifier_thresholds"] = copy.deepcopy(STRAW_MAN_CLASSIFIER_THRESHOLDS)
    return profile


# --- Gate input builder -------------------------------------------------------

def make_gate_kwargs(bu_profile, **overrides):
    """Build a valid, in-scope oxy_gate_check kwargs dict that resolves to PASS by default.

    Each test overrides only the fields it needs, so the assertion targets exactly one rule.
    Nested dicts are shallow-merged when overridden via the ``<name>`` key.
    """
    kwargs = {
        "context": {
            "equipment_id": "PUMP-4102",
            "plant": "HOUSTON",
            "business_unit": "BU1",
            "bu_profile_id": "default_oxy",
            "asset_class": "CENTRIFUGAL_PUMP",
            "time_window": "LAST_24_MONTHS",
        },
        "scope": {
            "scope_validated": True,
            "in_scope": True,
            "scope_flags": [],
            "pm_population_count": 1,
            "provenance": "GOVERNED",
            "blocked_reason": None,
        },
        "bu_profile": bu_profile,
        "criticality": {
            "code": "1",
            "label": "Non-critical",
            "validation_status": "VALIDATED",
            "source": "SAP",
            "last_reviewed_at": "2026-05-01",
        },
        "pm_governance": {"mandatory_pm": False, "mandatory_basis": None},
        "recommendation": {
            "type": "RETAIN_PM",
            "direction": None,
            "strategy_type": "TIME_BASED",
            "analysis_method": "PMO",
            "moc_threshold_exceeded": False,
            "strategy_review_age_days": 120,
        },
        "readiness": {
            "data_readiness": "GREEN",
            "evidence_sufficiency": "SUFFICIENT",
            "task_list_readiness": "GREEN",
            "component_readiness": "NOT_REQUIRED",
            "contractor_service_readiness": "NOT_REQUIRED",
            "cbm_readiness": "NOT_REQUIRED",
            "cbm_real_readings_available": False,
            "cbm_synthetic_data_flag": False,
            "object_dependency_readiness": "GREEN",
            "object_dependency_code": "PM_MCW",
            "acceptance_criteria_result": "PASSED",
            "follow_on_crmn_expected": False,
            "follow_on_crmn_created": False,
            "level_loading_status": "COMPLETE",
            "practicality_status": "COMPLETE",
        },
        "risk": {
            "risk_scorecard_available": True,
            "risk_result": "PASS",
            "risk_threshold_met": True,
        },
        "approval": {
            "user_champion_named": True,
            "work_strategy_owner_named": True,
            "maintenance_manager_required": False,
            "maintenance_manager_named": False,
            "compliance_safety_named": False,
            "sap_pm_owner_required": False,
            "sap_pm_owner_named": False,
        },
        "approval_state": {"peer_review_complete": True},
        "requested_action": "DRAFT_PACKAGE",
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(kwargs.get(key), dict):
            merged = copy.deepcopy(kwargs[key])
            merged.update(value)
            kwargs[key] = merged
        else:
            kwargs[key] = value
    return kwargs


@pytest.fixture
def gate_kwargs(bu_profile):
    """Factory fixture: call ``gate_kwargs(**overrides)`` to build a gate input.

    Pass ``bu_profile=<profile>`` as an override to swap the profile for a case.
    """
    def _factory(**overrides):
        profile = overrides.pop("bu_profile", bu_profile)
        return make_gate_kwargs(profile, **overrides)
    return _factory


# --- Classifier input builder -------------------------------------------------

def make_classifier_kwargs(bu_profile, **overrides):
    """Build a classifier input for a healthy, scorable, non-mandatory PM (criticality 1)."""
    kwargs = {
        "context": {
            "equipment_id": "PUMP-4102",
            "pm_id": "PM-4102-01",
            "bu_profile_id": "default_oxy",
            "time_window": "LAST_24_MONTHS",
            "pm_strategy_type": "TIME_BASED",
        },
        "bu_profile": bu_profile,
        "criticality": {"code": "1", "label": "Non-critical", "validation_status": "VALIDATED", "source": "SAP"},
        "pm_governance": {"mandatory_pm": False, "mandatory_basis": None, "object_dependency_code": None},
        "pm_attributes": {
            "failure_mode_justified": True,
            "right_asset_criticality": True,
            "right_strategy_type": True,
            "right_frequency": True,
            "task_list_complete": True,
            "parts_staged": True,
            "planned_hours_realistic": True,
            "findings_captured": True,
            "value_evidence_present": True,
        },
        "effectiveness_signals": {
            "failure_after_pm_rate": 0.04,
            "pm_to_follow_on_corrective_linkage": "PRESENT",
            "mtbf_trend": "IMPROVING",
            "mttr_trend": "FLAT",
            "repeat_failure_rate": 0.02,
            "finding_rate": 0.06,
            "pm_to_corrective_ratio": 3.5,
            "cost_per_finding": None,
            "planned_vs_actual_variance": 0.12,
        },
        "evidence_readiness": {
            "notification_coding_present": True,
            "cost_actuals_present": False,
            "measurement_readings_present": False,
            "signal_confidence": "MEDIUM",
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(kwargs.get(key), dict):
            merged = copy.deepcopy(kwargs[key])
            merged.update(value)
            kwargs[key] = merged
        else:
            kwargs[key] = value
    return kwargs


@pytest.fixture
def classifier_kwargs(bu_profile_thresholds_set):
    """Factory fixture for a scorable classifier input (straw-man thresholds set).

    Pass ``bu_profile=<profile>`` as an override to swap the profile for a case.
    """
    def _factory(**overrides):
        profile = overrides.pop("bu_profile", bu_profile_thresholds_set)
        return make_classifier_kwargs(profile, **overrides)
    return _factory
