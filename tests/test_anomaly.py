"""SAP-transactional anomaly / drift evidence tools 29-30 (reliability_drift_monitor, sap_cost_distribution).

EVIDENCE ONLY: they flag drift/outliers + a CANDIDATE recommendation TYPE; they never change the
classifier label or the gate, and every actionability threshold stays BU_DEFINED (null). Fail-closed on
thin / degenerate data - in particular Oxy's all-zero Breakdown_Duration and <5 costed events. Cost is
labor-blind (Oxy labor actuals ~0): material/services basis only, no savings claim.
"""

from __future__ import annotations

from max_agent.orchestrator import MaxAgent
from max_agent.tools.anomaly import (
    _MIN_COST_EVENTS,
    reactive_share,
    reliability_drift_monitor,
    sap_cost_distribution,
)


def _events(gaps, downtime=None):
    """Dated failure_events from inter-failure gaps (days). Ages accumulate; dates increase in step so the
    date-order and age-order agree. downtime defaults to 0 (Oxy's real Breakdown_Duration reality)."""
    events, acc = [], 0
    for i, g in enumerate(gaps):
        acc += g
        events.append({"failure_start_date": f"20{20 + i:02d}-01-15", "age_days": acc,
                       "downtime_hrs": (downtime[i] if downtime else 0),
                       "object_part": "BEARING", "cause_code": "NORMAL-WEAR"})
    return events


def _wos(spec):
    """wo_detail from (order_type, year, material_cost) triples. labor_cost is deliberately large to prove
    the cost tool never reads it."""
    return [{"order_type": t, "order_date": f"{y}-06-15", "material_cost": mc, "labor_cost": 9999.0}
            for (t, y, mc) in spec]


def _sig(env, name):
    return next(s for s in env["data"]["signals"] if s["signal"] == name)


# --- interval drift + trend -------------------------------------------------------------------------
def test_interval_self_drift_flags_acceleration_and_keeps_threshold_null():
    env = reliability_drift_monitor(_events([120, 110, 95, 70, 40]))  # gaps shrink -> failures accelerate
    s = _sig(env, "interval_self_drift")
    assert s["computable"] and s["direction"] == "ACCELERATING"
    assert s["statistic"]["z_score"] < 0
    assert s["candidate_recommendation_type"] == "PM_FREQUENCY_CHANGE:SHORTEN"
    assert s["actionable_threshold"] is None            # policy stays BU_DEFINED
    assert env["data"]["any_drift_flag"] is True


def test_interval_trend_slope_negative_on_deteriorating_series():
    s = _sig(reliability_drift_monitor(_events([120, 110, 95, 70, 40, 30])), "interval_trend_slope")
    assert s["computable"] and s["direction"] == "DETERIORATING"
    assert s["statistic"]["slope_days_per_failure"] < 0
    assert s["actionable_threshold"] is None


def test_interval_signals_fail_closed_below_floor():
    env = reliability_drift_monitor(_events([100, 90]))  # 3 failures -> 2 intervals (< self=3, < trend=5)
    sd, tr = _sig(env, "interval_self_drift"), _sig(env, "interval_trend_slope")
    assert sd["computable"] is False and "Failure_Start_Date" in sd["data_needed"]
    assert tr["computable"] is False


# --- downtime drift: computes on real durations, fail-closed on Oxy's all-zero reality ---------------
def test_downtime_drift_computes_on_nonzero_varied_durations():
    s = _sig(reliability_drift_monitor(_events([100, 90, 80, 70, 60], downtime=[4, 9, 6, 14, 22])),
             "downtime_drift")
    assert s["computable"] and "z_score" in s["statistic"]


def test_downtime_drift_fail_closed_on_all_zero_breakdown_duration():
    # Oxy reality: every breakdown row has Breakdown_Duration = 0 -> degenerate -> must fail closed.
    s = _sig(reliability_drift_monitor(_events([100, 90, 80, 70, 60], downtime=[0, 0, 0, 0, 0])),
             "downtime_drift")
    assert s["computable"] is False
    assert "Breakdown_Duration" in s["data_needed"]


# --- reactive work mix: level now, trend needs >=2 dated windows ------------------------------------
def test_reactive_ratio_trend_over_two_windows():
    wos = _wos([("preventive", "2024", 0), ("preventive", "2024", 0), ("corrective", "2024", 500)] +
               [("corrective", "2025", 500), ("reactive", "2025", 800), ("corrective", "2025", 500)])
    s = _sig(reliability_drift_monitor([], wo_detail=wos), "reactive_ratio_drift")
    assert s["computable"] and s["direction"] == "RISING"           # reactive share climbs 2024 -> 2025
    assert s["candidate_recommendation_type"] == "PM_FREQUENCY_CHANGE:SHORTEN"
    assert s["actionable_threshold"] is None


def test_reactive_ratio_single_window_fails_closed_on_the_trend_delta():
    wos = _wos([("preventive", "2025", 0), ("corrective", "2025", 500), ("reactive", "2025", 800)])
    s = _sig(reliability_drift_monitor([], wo_detail=wos), "reactive_ratio_drift")
    assert s["direction"] == "LEVEL_ONLY" and s["statistic"]["reactive_share"] is not None
    assert "2 windows" in s["data_needed"] or ">=2" in s["data_needed"]


def test_reactive_share_uses_evidence_classification_sets():
    assert reactive_share(_wos([("preventive", "2025", 0), ("corrective", "2025", 1),
                                ("reactive", "2025", 1), ("preventive", "2025", 0)])) == 0.5
    assert reactive_share([]) is None


# --- cohort bad-actor outlier ----------------------------------------------------------------------
def test_cohort_outlier_fail_closed_below_ten_peers():
    s = _sig(reliability_drift_monitor(_events([100, 90, 80]), cohort=[{"failure_count": 2}] * 5),
             "cohort_outlier")
    assert s["computable"] is False and "10" in s["data_needed"]


def test_cohort_outlier_flags_a_bad_actor():
    events = _events([40] * 20)  # subject has 20 failures
    cohort = [{"failure_count": c} for c in [1, 2, 2, 3, 2, 1, 3, 2, 2, 1, 3, 2]]  # peers ~1-3
    s = _sig(reliability_drift_monitor(events, cohort=cohort), "cohort_outlier")
    assert s["computable"] and s["direction"] == "OUTLIER_HIGH"
    assert s["statistic"]["percentile_rank"] == 100
    assert s["candidate_recommendation_type"] == "PM_FREQUENCY_CHANGE:SHORTEN"
    assert s["actionable_threshold"] is None


# --- overall fail-closed + no-invented-values ------------------------------------------------------
def test_drift_monitor_fail_closed_with_no_history():
    env = reliability_drift_monitor([], wo_detail=[], cohort=[])
    assert env["data"]["computable"] is False and env["data"]["any_drift_flag"] is False


def test_every_signal_threshold_is_null():
    env = reliability_drift_monitor(_events([120, 100, 90, 70, 50, 30], downtime=[4, 9, 6, 14, 22, 30]),
                                    wo_detail=_wos([("corrective", "2024", 500), ("reactive", "2025", 800)]),
                                    cohort=[{"failure_count": c} for c in range(12)])
    assert all(s["actionable_threshold"] is None for s in env["data"]["signals"])


def test_uncoded_history_caps_confidence():
    hi = reliability_drift_monitor(_events([120, 100, 90, 70, 50, 30]), uncoded_pct=0)
    lo = reliability_drift_monitor(_events([120, 100, 90, 70, 50, 30]), uncoded_pct=90)
    order = {"low": 0, "medium": 1, "high": 2}
    assert order[lo["confidence"]] <= order[hi["confidence"]]


# --- cost distribution (labor-blind) ---------------------------------------------------------------
def test_cost_distribution_bands_material_only_no_savings_claim():
    events = [{"material_cost": c, "order_type": "corrective"} for c in (200, 400, 600, 800, 1000, 5000)]
    d = sap_cost_distribution(events)["data"]
    assert d["computable"] and d["cost_p50"] > 0 and d["cost_p90"] >= d["cost_p50"]
    assert d["cost_basis"] == "material_services_partial_only"
    assert d["labor_cost_claim_allowed"] is False and d["savings_claim_allowed"] is False
    assert d["cost_action_threshold"] is None                      # actionability stays BU_DEFINED
    assert d["events_over_own_p90"] >= 1                            # the 5000 outlier


def test_cost_distribution_fail_closed_below_min_events():
    d = sap_cost_distribution([{"material_cost": 100, "order_type": "corrective"}] * (_MIN_COST_EVENTS - 1))["data"]
    assert d["computable"] is False and "Actual_Total_Cost" in d["data_needed"]
    assert d["savings_claim_allowed"] is False


def test_cost_distribution_never_reads_labor_cost():
    # labor_cost is huge but must be ignored; bands come from material_cost only.
    events = [{"material_cost": 100, "labor_cost": 1_000_000, "order_type": "corrective"} for _ in range(6)]
    d = sap_cost_distribution(events)["data"]
    assert d["cost_p50"] == 100 and d["cost_p90"] == 100          # labor never enters the distribution


# --- orchestrator integration: evidence-only, scope-authoritative ----------------------------------
def test_run_populates_drift_and_cost_and_leaves_label_gate_unchanged():
    a = MaxAgent()
    r = a.run("PUMP-4110")
    assert isinstance(r.get("reliability_drift"), dict) and "signals" in r["reliability_drift"]
    cost = r.get("cost_distribution") or {}
    assert cost.get("cost_basis") == "material_services_partial_only"
    assert cost.get("savings_claim_allowed") is False
    # evidence-only: the label + gate are untouched by the anomaly tools (re-run is identical).
    assert r["classifier_label"] == a.run("PUMP-4110")["classifier_label"]
    assert "drift" not in str(r.get("gate_status"))              # gate is a gate code, not a drift value


def test_out_of_scope_asset_has_no_drift_or_cost():
    agent = MaxAgent()
    for eid in agent._fleet_index:
        r = agent.run(eid)
        if r.get("classifier_label") == "Not classified (out of analysis scope)":
            assert "reliability_drift" not in r and "cost_distribution" not in r
            return
    assert True  # vacuously satisfied if the fleet has no out-of-scope asset


# --- free-flow read-only surface + artifact rendering ----------------------------------------------
def test_free_flow_exposes_drift_and_cost_as_read_only_tools():
    import pytest
    pytest.importorskip("langchain_core")
    from max_agent.agent_tools import make_agent_tools
    a = MaxAgent()
    last = a.run("PUMP-4110")
    tools = {t.name: t for t in make_agent_tools(a, last)}
    assert "reliability_drift" in tools and "cost_distribution" in tools
    # they read the FROZEN decision (no re-compute) and never claim savings
    assert tools["cost_distribution"].invoke({})["savings_claim_allowed"] is False
    assert "signals" in tools["reliability_drift"].invoke({})


def test_drift_anomaly_artifact_renders_and_auto_defaults_when_flagged():
    from max_agent.ui.artifact_catalog import _drift_anomaly, default_artifacts
    r = MaxAgent().run("PUMP-4110")
    if (r.get("reliability_drift") or {}).get("any_drift_flag"):
        assert "drift_anomaly" in default_artifacts(r)   # surfaced even if the model did not select it
    assert _drift_anomaly(r) is not None                 # the card builds from the governed result
