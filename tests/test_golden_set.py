"""Golden-set regression harness (08 "Golden-Set Regression Harness" / 09 "Golden-Set Note").

Data-driven: labeled cases in ``fixtures/golden_gate_classifier_cases.json`` are replayed
through ``oxy_gate_check`` and ``pm_effectiveness_classifier``. Any threshold or rule change
re-runs this set and shows whether a previously agreed outcome changed. The classifier
straw-man bands are TEST-ONLY (the shipped profile keeps thresholds null).
"""

import copy
import json
import os

import pytest

from conftest import make_classifier_kwargs, make_gate_kwargs, STRAW_MAN_CLASSIFIER_THRESHOLDS
from max_agent.config import load_bu_profile
from max_agent.tools.classification import pm_effectiveness_classifier
from max_agent.tools.governance import oxy_gate_check

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "golden_gate_classifier_cases.json")

with open(_FIXTURE, "r", encoding="utf-8") as _fh:
    _GOLDEN = json.load(_fh)


def _profile_with_thresholds():
    profile = load_bu_profile("default_oxy")
    profile["classifier_thresholds"] = copy.deepcopy(STRAW_MAN_CLASSIFIER_THRESHOLDS)
    return profile


@pytest.mark.parametrize("case", _GOLDEN["gate_cases"], ids=lambda c: c["name"])
def test_golden_gate_cases(case):
    profile = load_bu_profile("default_oxy")
    result = oxy_gate_check(**make_gate_kwargs(profile, **case["overrides"]))
    assert result["data"]["gate_status"] == case["expected_gate_status"], case["name"]
    if "expected_blocked_reason" in case:
        assert result["blocked_reason"] == case["expected_blocked_reason"], case["name"]


@pytest.mark.parametrize("case", _GOLDEN["classifier_cases"], ids=lambda c: c["name"])
def test_golden_classifier_cases(case):
    profile = _profile_with_thresholds() if case["thresholds"] == "set" else load_bu_profile("default_oxy")
    result = pm_effectiveness_classifier(**make_classifier_kwargs(profile, **case["overrides"]))
    assert result["data"]["label"] == case["expected_label"], case["name"]
