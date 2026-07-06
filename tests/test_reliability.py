"""Reliability-evidence tools 25-27 (reliability_metrics, weibull_reliability, failure_mode_summary).

EVIDENCE ONLY: they compute reliability facts + a math-defensible interpretation that feeds the
narration / recommendation; they NEVER change the classifier label or the gate, and every judgment
threshold stays BU_DEFINED. Fail-closed on thin data; out-of-scope assets never reach them.
"""

from __future__ import annotations

from max_agent.orchestrator import MaxAgent
from max_agent.tools.reliability import (
    _WEIBULL_MIN_FAILURES,
    failure_mode_summary,
    reliability_metrics,
    weibull_reliability,
)


def _events(n, dmg=True):
    return [{"age_days": 100 * (i + 1), "downtime_hrs": 6, "object_part": "MECH-SEAL" if dmg else None,
             "damage_code": "SEAL-LEAK" if dmg else None, "cause_code": "NORMAL-WEAR" if dmg else None}
            for i in range(n)]


def test_reliability_metrics_compute_and_stay_neutral():
    env = reliability_metrics(_events(4), window_days=730)
    d = env["data"]
    assert d["computable"] and d["mtbf_days"] == round(730 / 4, 1)
    assert d["mttr_hours"] == 6 and d["availability_pct"] is not None
    assert d["acceptable_threshold"] is None      # judgment stays BU_DEFINED (unset)


def test_reliability_metrics_fail_closed_without_failures():
    env = reliability_metrics([], window_days=730)
    assert env["data"]["computable"] is False
    assert "Failure_Start_Date" in env["data"]["data_needed"]


def test_weibull_fails_closed_below_min_failures():
    env = weibull_reliability(_events(_WEIBULL_MIN_FAILURES - 1), window_days=730)
    assert env["data"]["computable"] is False
    assert env["data"]["min_failures"] == _WEIBULL_MIN_FAILURES


def test_weibull_computes_shape_and_sane_probability():
    env = weibull_reliability(_events(8), window_days=730, horizon_days=90)
    d = env["data"]
    assert d["computable"] and d["hazard_shape"] in ("WEAR_OUT", "RANDOM", "INFANT_MORTALITY")
    assert 0.0 <= d["p_fail_horizon"] <= 1.0        # a probability, not a certainty artifact
    assert d["cbm_threshold"] is None               # the beta->CBM band stays BU_DEFINED
    assert d["synthetic_flag"] is True


def test_failure_mode_summary_groups_and_flags_uncoded():
    events = _events(2, dmg=True) + _events(2, dmg=False)  # 2 coded, 2 uncoded
    d = failure_mode_summary(events)["data"]
    assert d["computable"] and d["uncoded_pct"] == 50
    assert d["dominant_mode"]["object_part"] == "MECH-SEAL"


def test_run_populates_reliability_and_leaves_label_gate_unchanged():
    a = MaxAgent()
    r = a.run("PUMP-4110")
    rel = r.get("reliability") or {}
    assert rel.get("metrics", {}).get("computable")           # MTBF/MTTR/availability present
    assert r.get("reliability_interpretation")                # prominent read exists
    # evidence-only: the label + gate come from the classifier/gate, untouched by reliability
    assert r["classifier_label"] == a.run("PUMP-4110")["classifier_label"]
    assert "reliability" not in str(r.get("gate_status"))     # gate is a gate code, not a reliability value


def test_out_of_scope_asset_has_no_reliability():
    r = MaxAgent().run("PUMP-4130")  # non-operated / JV -> short-circuits before _run_extras
    assert not r.get("reliability")
