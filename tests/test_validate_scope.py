"""Unit tests for validate_scope - every case from 10 ("validate_scope" unit tests)."""

import copy

from max_agent.tools.context import validate_scope


BASE_CONTEXT = {
    "equipment_id": "PUMP-4102",
    "plant": "HOUSTON",
    "business_unit": "BU1",
    "asset_class": "CENTRIFUGAL_PUMP",
    "bu_profile_id": "default_oxy",
    "time_window": "LAST_24_MONTHS",
}

BASE_MASTER_DATA = {
    "asset_resolved": True,
    "pm_population_count": 1,
    "operated_status": "OPERATED",
    "exemption_status": "NONE",
    "exemption_id": None,
    "criticality": {
        "code": "2",
        "label": "High-value non-critical",
        "validation_status": "VALIDATED",
        "source": "SAP",
        "stale": False,
        "equipment_floc_conflict": False,
    },
    "synthetic_data_flag": False,
}


def _md(**overrides):
    md = copy.deepcopy(BASE_MASTER_DATA)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(md.get(key), dict):
            md[key] = {**md[key], **value}
        else:
            md[key] = value
    return md


def test_blocks_when_no_asset_or_population(bu_profile):
    result = validate_scope(BASE_CONTEXT, bu_profile, _md(asset_resolved=False))
    assert result["data"]["scope_validated"] is False
    assert result["data"]["blocked_reason"] == "NO_VALIDATED_SCOPE"
    assert result["scope_validated"] is False


def test_blocks_when_pm_population_empty(bu_profile):
    context = {**BASE_CONTEXT, "equipment_id": None, "pm_population": {"filter": "class=PUMP"}}
    result = validate_scope(context, bu_profile, _md(pm_population_count=0))
    assert result["data"]["scope_validated"] is False
    assert result["data"]["blocked_reason"] == "EMPTY_PM_POPULATION"


def test_flags_non_operated_jv_out_of_scope(bu_profile):
    result = validate_scope(BASE_CONTEXT, bu_profile, _md(operated_status="JV"))
    assert result["data"]["in_scope"] is False
    assert result["data"]["blocked_reason"] == "NON_OPERATED_OR_JV_OUT_OF_SCOPE"


def test_flags_exempted_asset(bu_profile):
    result = validate_scope(BASE_CONTEXT, bu_profile, _md(exemption_status="EXEMPT", exemption_id="EX-001"))
    assert result["data"]["in_scope"] is False
    assert result["data"]["blocked_reason"] == "EXEMPT_ASSET_OUT_OF_SCOPE"


def test_flags_out_of_pilot_class_scope(bu_profile):
    profile = copy.deepcopy(bu_profile)
    profile["pilot_equipment_classes"] = ["CENTRIFUGAL_PUMP"]  # P4 - set for this test only
    context = {**BASE_CONTEXT, "asset_class": "RECIP_COMPRESSOR"}
    result = validate_scope(context, profile, _md())
    # A pilot-scope miss is a warn flag, not a hard block.
    assert result["data"]["scope_validated"] is True
    assert result["data"]["in_scope"] is True
    assert "OUT_OF_PILOT_SCOPE" in result["data"]["scope_flags"]


def test_flags_unvalidated_criticality_0_or_blank(bu_profile):
    result = validate_scope(BASE_CONTEXT, bu_profile, _md(criticality={"code": "0", "validation_status": "NOT_VALIDATED"}))
    assert result["data"]["scope_validated"] is True
    assert "CRITICALITY_UNVALIDATED" in result["data"]["scope_flags"]


def test_flags_stale_criticality(bu_profile):
    result = validate_scope(BASE_CONTEXT, bu_profile, _md(criticality={"stale": True}))
    assert "CRITICALITY_STALE" in result["data"]["scope_flags"]


def test_flags_equipment_floc_criticality_conflict(bu_profile):
    result = validate_scope(BASE_CONTEXT, bu_profile, _md(criticality={"equipment_floc_conflict": True}))
    assert "CRITICALITY_FLOC_CONFLICT" in result["data"]["scope_flags"]


def test_marks_synthetic_provenance_when_flagged(bu_profile):
    result = validate_scope(BASE_CONTEXT, bu_profile, _md(synthetic_data_flag=True))
    assert result["data"]["provenance"] == "SYNTHETIC"
    assert "PROVENANCE_SYNTHETIC" in result["data"]["scope_flags"]


def test_passes_in_scope_operated_validated_asset(bu_profile):
    result = validate_scope(BASE_CONTEXT, bu_profile, _md())
    assert result["data"]["scope_validated"] is True
    assert result["data"]["in_scope"] is True
    assert result["data"]["scope_flags"] == []
    assert result["data"]["provenance"] == "GOVERNED"
