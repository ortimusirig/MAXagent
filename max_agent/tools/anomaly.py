"""SAP-transactional anomaly / drift EVIDENCE tools (Wave-B extension, tools 29-30).

Redesign of the reference PdM agent's ANOMALY_DETECTION intent onto TRANSACTIONAL SAP. The reference
tool is sensor-based (IMRG measurement readings + Z-score/IQR); Oxy has NO live condition readings
(SOAR Measurement Points are 0/175, stale ~2019), so this keeps ONLY the z-score / IQR / percentile /
trend ARITHMETIC and applies it to the data Oxy DOES have: failure timing + breakdown duration
(Notifications), the reactive/planned work mix (WOs), and cost (Cost / WO actuals).

EVIDENCE ONLY, exactly like the reliability tools (25-27):

- Returns tool_envelope; each signal reports a statistic (z-score, IQR fence position, P90 exceedance,
  OLS slope, ratio) and points at a CANDIDATE recommendation TYPE - it never forms or authorizes a
  change, never touches the classifier label or oxy_gate_check. recommend_strategy_change (deterministic)
  reads the evidence and applies its rails; the gate decides; a human commits (Wave-1 draft-only).
- Every actionability threshold stays BU_DEFINED / null (the statistic is arithmetic; "is this drift
  BAD?" is an Oxy policy call), exactly like weibull cbm_threshold / reliability acceptable_threshold.
- Fail-closed: below the sample floor -> computable=false + the exact SOAR field still needed. No
  invented values; a self-baseline is ordered by real Failure_Start_Date, not a synthetic age sort.
- Cost signals are labor-blind: Oxy labor actuals are ~0, so cost_basis='material_services_partial_only'
  and no labor-cost / savings claim is ever emitted (mirrors risk_business_justification + evidence.py).
- Synthetic failure/WO dates are flagged; confidence tiers by sample size.

Input feeds are the SAME the orchestrator already builds for the reliability tools: failure_events
(SOAR Notifications: Failure_Start_Date / Breakdown_Duration / Object_Part_Code / Cause_Code) and
wo_detail (SOAR WOs: order_date / order_type / per-WO cost), plus the like-equipment cohort already
computed for the BOM / comparison tools (keyed on Equipment_Class, not the unvalidated criticality).
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

from ..evidence import _CORRECTIVE, _PREVENTIVE  # reuse the digest's WO-type classification verbatim
from ..schemas import STATUS_SUCCESS, STATUS_WARNING, tool_envelope

# Sample floors. Mirror reliability._WEIBULL_MIN_FAILURES=4; a TREND needs more points than a LEVEL.
_MIN_SELF_FAILURES = 4       # >=4 dated failures => >=3 intervals for a self-baseline z-score
_MIN_TREND_INTERVALS = 5     # >=5 intervals (>=6 dated failures) before an interval trend is meaningful
_MIN_COHORT = 10             # cross-sectional IQR needs a populated cohort (mirrors ref len(vals)<10 skip)
_MIN_COST_EVENTS = 5         # v2 CostPredictionAgent gates per-equipment bands at n>=5

_REC_SHORTEN = "PM_FREQUENCY_CHANGE:SHORTEN"   # candidate TYPE hint only; recommend_strategy_change owns the real REC


# --- pure-arithmetic helpers -----------------------------------------------------------------------
def _confidence(n: int) -> str:
    return "low" if n < 7 else ("medium" if n < 12 else "high")


def _percentile(sorted_vals: List[float], p: float) -> float:
    """Linear-interpolation percentile (numpy default), so the bands match the reference agent."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _ols_slope(ys: List[float]):
    """(slope, r2) of ys vs index 0..n-1 by least squares. Pure arithmetic, no policy call."""
    n = len(ys)
    if n < 2:
        return 0.0, 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return 0.0, 0.0
    slope = sxy / sxx
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
    return round(slope, 3), round(r2, 3)


def _ordered_intervals(events: List[Dict[str, Any]]) -> List[float]:
    """Inter-failure intervals (days) in TRUE calendar order. Orders by Failure_Start_Date when present
    (real SOAR), else by age_days (monotonic with time for a single asset); magnitudes come from age_days
    diffs so no date arithmetic is needed. n failures -> n-1 intervals (real gaps, not a from-zero gap)."""
    dated = [(str(e.get("failure_start_date")), float(e.get("age_days") or 0))
             for e in events if e.get("failure_start_date") is not None]
    if len(dated) >= 2:
        dated.sort(key=lambda t: t[0])                       # ISO date strings sort chronologically
        ages = [a for _, a in dated]
    else:
        ages = sorted(float(e.get("age_days") or 0) for e in events)
    intervals, prev = [], None
    for a in ages:
        if prev is not None:
            intervals.append(max(0.0, a - prev))
        prev = a
    return intervals


def reactive_share(wo_detail: Optional[List[Dict[str, Any]]]) -> Optional[float]:
    """Corrective/reactive share of the work-order mix, using evidence.py's exact _CORRECTIVE set so
    this never drifts from the digest's corrective_count. Returns None when there are no orders."""
    wos = wo_detail or []
    total = 0
    corr = 0
    for w in wos:
        t = str(w.get("order_type") or "").lower()
        if t in _CORRECTIVE or t in _PREVENTIVE or t:
            total += 1
            if t in _CORRECTIVE:
                corr += 1
    return round(corr / total, 3) if total else None


def _sig(signal: str, computable: bool, **kw) -> Dict[str, Any]:
    """One signal record. actionable_threshold is ALWAYS null (arithmetic reported; policy BU_DEFINED)."""
    rec = {"signal": signal, "computable": computable, "actionable_threshold": None,
           "direction": None, "statistic": {}, "candidate_recommendation_type": None,
           "confidence": "low", "data_needed": None, "interpretation": None}
    rec.update(kw)
    return rec


# --- per-signal builders ---------------------------------------------------------------------------
def _interval_signals(events: List[Dict[str, Any]], synthetic: bool) -> List[Dict[str, Any]]:
    intervals = _ordered_intervals(events)
    n_int = len(intervals)
    out: List[Dict[str, Any]] = []

    # interval_self_drift: most-recent interval vs the asset's own prior intervals (z-score).
    if n_int >= 3:  # >=3 intervals => >=4 dated failures; baseline is the >=2 prior intervals
        recent = intervals[-1]
        baseline = intervals[:-1]
        mu = statistics.mean(baseline)
        sd = statistics.pstdev(baseline) if len(baseline) > 1 else 0.0
        z = round((recent - mu) / sd, 2) if sd > 0 else 0.0
        direction = "ACCELERATING" if z <= -1 else ("SLOWING" if z >= 1 else "STABLE")
        out.append(_sig(
            "interval_self_drift", True, direction=direction,
            statistic={"recent_interval_days": round(recent, 1), "baseline_mean_days": round(mu, 1),
                       "baseline_sd_days": round(sd, 1), "z_score": z, "n_intervals": n_int},
            candidate_recommendation_type=(_REC_SHORTEN if z <= -1 else None),
            confidence=_confidence(n_int + 1),
            interpretation=(
                f"Most-recent gap between failures is {round(recent)}d vs a self-baseline mean of "
                f"{round(mu)}d (z={z}); "
                + ("failures are accelerating relative to this asset's own history - a shorter PM interval "
                   "is worth reviewing" if z <= -1 else "no acceleration vs the asset's own history")
                + ". Whether |z| is actionable is BU-defined (unset)."
                + (" Synthetic failure dates until SOAR Failure_Start_Date is bound." if synthetic else ""))))
    else:
        out.append(_sig(
            "interval_self_drift", False, confidence="low",
            data_needed="Notifications: >=4 dated Failure_Start_Date events for a stable self-baseline",
            interpretation="Too few dated failures to compute a self-referential drift z-score (fail-closed)."))

    # interval_trend_slope: OLS slope of interval length over ordered failures (deterioration trend).
    if n_int >= _MIN_TREND_INTERVALS:
        slope, r2 = _ols_slope(intervals)
        direction = "DETERIORATING" if slope < 0 else ("IMPROVING" if slope > 0 else "FLAT")
        out.append(_sig(
            "interval_trend_slope", True, direction=direction,
            statistic={"slope_days_per_failure": slope, "r2": r2, "n_intervals": n_int},
            candidate_recommendation_type=(_REC_SHORTEN if slope < 0 else None),
            confidence=_confidence(n_int + 1),
            interpretation=(
                f"Inter-failure intervals are trending {'down' if slope < 0 else 'up' if slope > 0 else 'flat'} "
                f"over time (slope {slope} days/failure, R^2 {r2}); "
                + ("gradual reliability deterioration a single z-score can miss" if slope < 0
                   else "no deterioration trend")
                + ". The slope is arithmetic; the magnitude that qualifies as a real trend is BU-defined (unset)."
                + (" Synthetic dates." if synthetic else ""))))
    else:
        out.append(_sig(
            "interval_trend_slope", False, confidence="low",
            data_needed="Notifications: >=5 inter-failure intervals (>=6 dated Failure_Start_Date events) to fit a trend",
            interpretation="Too few intervals to fit an interval trend (fail-closed)."))
    return out


def _downtime_signal(events: List[Dict[str, Any]], synthetic: bool) -> Dict[str, Any]:
    """MTTR / repair-duration drift. On the bound SOAR extract EVERY breakdown row has Breakdown_Duration=0
    (a degenerate, zero-variance series), so this fails closed and surfaces the DATA-MAINTENANCE gap rather
    than a fabricated drift. Guard requires non-null AND non-zero AND positive variance, not just non-null."""
    durations = [float(e.get("downtime_hrs") or 0) for e in events]
    nonzero = [d for d in durations if d > 0]
    if len(nonzero) >= 4 and statistics.pstdev(nonzero) > 0:
        recent = nonzero[-1]
        baseline = nonzero[:-1]
        mu = statistics.mean(baseline)
        sd = statistics.pstdev(baseline) if len(baseline) > 1 else 0.0
        z = round((recent - mu) / sd, 2) if sd > 0 else 0.0
        p90 = _percentile(sorted(nonzero), 90)
        over = sum(1 for d in nonzero if d > p90)
        direction = "WORSENING" if z >= 1 else ("IMPROVING" if z <= -1 else "STABLE")
        return _sig(
            "downtime_drift", True, direction=direction,
            statistic={"recent_downtime_hrs": round(recent, 1), "baseline_mean_hrs": round(mu, 1),
                       "z_score": z, "p90_hrs": round(p90, 1), "events_over_p90": over, "n_nonzero": len(nonzero)},
            candidate_recommendation_type=(_REC_SHORTEN if z >= 1 else None),
            confidence=_confidence(len(nonzero) + 1),
            interpretation=(
                f"Recent repair duration {round(recent)}h vs a self-baseline mean of {round(mu)}h (z={z}); "
                + ("repairs are taking longer than this asset's own history" if z >= 1 else "no repair-duration drift")
                + ". Whether the drift is actionable is BU-defined (unset)."
                + (" Synthetic durations." if synthetic else "")))
    return _sig(
        "downtime_drift", False,
        statistic={"n_nonzero_durations": len(nonzero)}, confidence="low",
        data_needed=("Notifications: Breakdown_Duration populated with real repair hours at notification close "
                     "(currently 0 on all breakdown rows in the SOAR extract - the field is not maintained)"),
        interpretation=("Repair-duration (MTTR) drift is not computable: Breakdown_Duration is not being captured "
                        "(all values zero / no variance), so this surfaces a data-maintenance gap, not a reliability "
                        "finding. reliability_metrics likewise reports MTTR as unavailable."))


def _reactive_signal(wo_detail: Optional[List[Dict[str, Any]]], synthetic: bool) -> Dict[str, Any]:
    """Reactive-vs-planned work MIX: the LEVEL now, plus the period-over-period TREND (the non-duplicative
    core; the level alone echoes the classifier's point pm_to_corrective_ratio). Trend needs >=2 dated
    windows (WOs.order_date), else fail-closed on the delta while still reporting the level."""
    wos = wo_detail or []
    if not wos:
        return _sig("reactive_ratio_drift", False, confidence="low",
                    data_needed="WOs: dated work orders (order_date / order_type) to compute the reactive work mix",
                    interpretation="No work-order detail to compute a reactive work mix (fail-closed).")
    level = reactive_share(wos)

    # Period-bucket by calendar year of order_date for the trend.
    periods: Dict[str, List[int]] = {}
    for w in wos:
        d = str(w.get("order_date") or "")
        yr = d[:4] if len(d) >= 4 and d[:4].isdigit() else None
        t = str(w.get("order_type") or "").lower()
        if yr is None or not t:
            continue
        b = periods.setdefault(yr, [0, 0])       # [corrective, total]
        b[1] += 1
        if t in _CORRECTIVE:
            b[0] += 1
    shares = [(yr, (c / n if n else 0.0)) for yr, (c, n) in sorted(periods.items())]

    if len(shares) >= 2:
        slope, r2 = _ols_slope([s for _, s in shares])
        direction = "RISING" if slope > 0 else ("FALLING" if slope < 0 else "FLAT")
        return _sig(
            "reactive_ratio_drift", True, direction=direction,
            statistic={"reactive_share": level, "trend_slope_per_period": slope, "r2": r2,
                       "windows": [{"period": yr, "reactive_share": round(s, 3)} for yr, s in shares]},
            candidate_recommendation_type=(_REC_SHORTEN if slope > 0 else None),
            confidence=_confidence(len(wos)),
            interpretation=(
                f"Reactive/breakdown work is {round((level or 0) * 100)}% of orders and the reactive share is "
                f"{'rising' if slope > 0 else 'falling' if slope < 0 else 'flat'} over {len(shares)} windows "
                f"(slope {slope}/yr). "
                + ("A rising reactive share is the clearest leading indicator that the PM is losing ground."
                   if slope > 0 else "No adverse trend in the work mix.")
                + " The actionable level and trend are BU-defined (unset)."))
    # single window: level only, fail-closed on the delta
    return _sig(
        "reactive_ratio_drift", True, direction="LEVEL_ONLY",
        statistic={"reactive_share": level, "windows": [{"period": yr, "reactive_share": round(s, 3)}
                                                         for yr, s in shares]},
        candidate_recommendation_type=None, confidence="low",
        data_needed="WOs: dated records across >=2 windows (order_date) to period-bucket the reactive-ratio trend",
        interpretation=(
            f"Reactive/breakdown work is {round((level or 0) * 100)}% of orders (single window; distinct from the "
            "classifier's point pm-to-corrective ratio). The period-over-period trend is not computable without "
            ">=2 dated windows (fail-closed on the delta). The actionable level is BU-defined (unset)."))


def _cohort_signal(subject_failures: int, subject_reactive: Optional[float],
                   cohort: Optional[List[Dict[str, Any]]], cohort_criticality_unvalidated: bool,
                   synthetic: bool) -> Dict[str, Any]:
    """Cross-sectional BAD-ACTOR outlier: is the asset a statistical outlier vs its like-equipment cohort
    (Equipment_Class) on failure count? z-score + Tukey IQR fence + percentile rank. Distinct from
    like_equipment_comparison (standardization) and portfolio_health (gate-status). Fills the new-asset
    blind spot the self-baseline signals cannot (weibull fails closed below 4 failures)."""
    peers = [int(p.get("failure_count")) for p in (cohort or []) if p.get("failure_count") is not None]
    if len(peers) < _MIN_COHORT:
        return _sig("cohort_outlier", False, confidence="low",
                    data_needed=("Notifications/WOs across >=10 like-equipment peers (Equipment_Class cohort) "
                                 "to fit a cohort distribution"),
                    interpretation=(f"Cohort outlier not computable: only {len(peers)} comparable peers "
                                    f"(need >=10) (fail-closed)."))
    pop = sorted(peers + [subject_failures])
    mu = statistics.mean(peers)
    sd = statistics.pstdev(peers) if len(peers) > 1 else 0.0
    z = round((subject_failures - mu) / sd, 2) if sd > 0 else 0.0
    q1 = _percentile(pop, 25)
    q3 = _percentile(pop, 75)
    upper = q3 + 1.5 * (q3 - q1)
    rank = round(100.0 * sum(1 for p in peers if p <= subject_failures) / len(peers))
    is_outlier = bool(subject_failures > upper or z > 3)
    conf = "low" if cohort_criticality_unvalidated else ("medium" if len(peers) < 20 else "high")
    return _sig(
        "cohort_outlier", True, direction=("OUTLIER_HIGH" if is_outlier else "IN_DISTRIBUTION"),
        statistic={"subject_failures": subject_failures, "cohort_mean": round(mu, 1), "cohort_z": z,
                   "iqr_upper_fence": round(upper, 1), "percentile_rank": rank, "cohort_size": len(peers),
                   "subject_reactive_share": subject_reactive},
        candidate_recommendation_type=(_REC_SHORTEN if is_outlier else None),
        confidence=conf,
        interpretation=(
            f"This asset had {subject_failures} failures vs a cohort mean of {round(mu, 1)} "
            f"(z={z}, {rank}th percentile of {len(peers)} like-Equipment_Class peers); "
            + ("it sits ABOVE the cohort's Tukey upper fence - a reliability bad-actor worth reviewing"
               if is_outlier else "it is within the cohort distribution")
            + ". The outlier cutoff is BU-defined (unset)."
            + (" Cohort criticality is unvalidated (0-Pending Assessment), so confidence is capped."
               if cohort_criticality_unvalidated else "")))


# --- Tool 29: reliability_drift_monitor ------------------------------------------------------------
def reliability_drift_monitor(
    failure_events: List[Dict[str, Any]],
    wo_detail: Optional[List[Dict[str, Any]]] = None,
    cohort: Optional[List[Dict[str, Any]]] = None,
    window_days: int = 730,
    uncoded_pct: Optional[float] = None,
    cohort_criticality_unvalidated: bool = False,
    synthetic: bool = True,
) -> Dict[str, Any]:
    """SAP-transactional anomaly / drift EVIDENCE. Computes self-referential failure-interval drift +
    trend, MTTR drift (fail-closed on Oxy's all-zero Breakdown_Duration), reactive-work-mix level+trend,
    and a cross-sectional cohort bad-actor outlier. EVIDENCE ONLY: it FLAGS drift and names a candidate
    recommendation TYPE, but never forms a recommendation, never changes the classifier label or the gate.
    Every actionability threshold stays BU_DEFINED/null. Confidence is capped when failure coding is poor
    (uncoded_pct), reusing failure_mode_summary's coded-share so no confident claim rests on bad coding."""
    events = failure_events or []
    signals: List[Dict[str, Any]] = []
    signals.extend(_interval_signals(events, synthetic))
    signals.append(_downtime_signal(events, synthetic))
    signals.append(_reactive_signal(wo_detail, synthetic))
    subject_reactive = reactive_share(wo_detail)
    signals.append(_cohort_signal(len(events), subject_reactive, cohort,
                                  cohort_criticality_unvalidated, synthetic))

    # Uncoded-coding guard (folded in, not a standalone signal): cap confidence when coding is poor.
    coding_capped = False
    if uncoded_pct is not None and uncoded_pct >= 50:
        coding_capped = True
        for s in signals:
            if s["computable"] and s["confidence"] in ("medium", "high"):
                s["confidence"] = "low" if uncoded_pct >= 75 else "medium"

    computable = [s for s in signals if s["computable"]]
    flagged = [s for s in computable if s.get("candidate_recommendation_type")]
    any_drift = bool(flagged)
    interp = " ".join(s["interpretation"] for s in computable if s.get("interpretation"))
    if coding_capped:
        interp += (f" Note: {round(uncoded_pct)}% of failures are uncoded, so drift confidence is capped "
                   "(close the coding gap to make this defensible).")

    if not computable:
        return tool_envelope(
            tool="reliability_drift_monitor", status=STATUS_WARNING,
            summary="No SAP-transactional drift signal computable (insufficient failure / work-order history).",
            data={"computable": False, "any_drift_flag": False, "signals": signals,
                  "synthetic_flag": synthetic, "uncoded_pct": uncoded_pct,
                  "sap_source": "Notifications (Failure_Start_Date / Breakdown_Duration) + WOs (order_date / order_type)",
                  "interpretation": (interp or "Too little transactional history for any drift statistic; "
                                     "see each signal's data_needed.")},
            confidence="low")

    flagged_names = ", ".join(s["signal"] for s in flagged) or "none"
    return tool_envelope(
        tool="reliability_drift_monitor",
        status=STATUS_WARNING if any_drift else STATUS_SUCCESS,
        summary=(f"{len(computable)}/{len(signals)} drift signals computable; "
                 + (f"flagged: {flagged_names}." if any_drift else "no drift flagged.")),
        data={"computable": True, "any_drift_flag": any_drift, "flagged_signals": [s["signal"] for s in flagged],
              "signals": signals, "synthetic_flag": synthetic, "uncoded_pct": uncoded_pct,
              "sap_source": "Notifications (Failure_Start_Date / Breakdown_Duration) + WOs (order_date / order_type)",
              "interpretation": interp,
              "note": ("EVIDENCE ONLY - flags a candidate recommendation TYPE; recommend_strategy_change forms "
                       "the recommendation and oxy_gate_check decides. Never changes the label or the gate.")},
        confidence=max((s["confidence"] for s in computable),
                       key=lambda c: {"low": 0, "medium": 1, "high": 2}[c]))


# --- Tool 30: sap_cost_distribution ----------------------------------------------------------------
def sap_cost_distribution(
    cost_events: List[Dict[str, Any]],
    cohort_costs: Optional[List[float]] = None,
    min_events: int = _MIN_COST_EVENTS,
    synthetic: bool = True,
) -> Dict[str, Any]:
    """Governed cost-quantile EVIDENCE: this asset's own P10/P50/P90 maintenance-cost bands + a cohort-P90
    exceedance flag. LABOR-BLIND: Oxy labor actuals are ~0, so bands use total/material cost only,
    cost_basis='material_services_partial_only', and NO labor-cost or savings claim is ever made (mirrors
    risk_business_justification + evidence.py _BASIS_LABEL). The 'is a P90 exceedance actionable?' call
    stays BU_DEFINED/null. Fails closed below `min_events`. EVIDENCE ONLY - feeds risk_business_justification;
    never changes the label or the gate."""
    events = cost_events or []
    amounts = sorted(float(e.get("total_cost") or e.get("material_cost") or 0)
                     for e in events if (e.get("total_cost") or e.get("material_cost")))
    base_data = {"cost_basis": "material_services_partial_only", "labor_cost_claim_allowed": False,
                 "savings_claim_allowed": False, "cost_action_threshold": None, "synthetic_flag": synthetic,
                 "sap_source": "Cost: Actual_Total_Cost / Actual_Material_Cost; WOs: Global_Act_*_Cost"}

    if len(amounts) < min_events:
        return tool_envelope(
            tool="sap_cost_distribution", status=STATUS_WARNING,
            summary=f"Cost distribution not computable ({len(amounts)} costed events < {min_events}).",
            data={**base_data, "computable": False, "n_events": len(amounts),
                  "data_needed": ("Cost: Actual_Total_Cost / Actual_Material_Cost per work order "
                                  f"(>=  {min_events} events); labor actuals are ~0 so bands are material/services only"),
                  "interpretation": (f"Only {len(amounts)} costed events - too few for a stable P90 (fail-closed). "
                                     "Labor actuals are ~0, so any bands would be material/services only.")},
            confidence="low")

    p10 = _percentile(amounts, 10)
    p50 = _percentile(amounts, 50)
    p90 = _percentile(amounts, 90)
    over_own = sum(1 for a in amounts if a > p90)

    cohort_flag = None
    cohort_p90 = None
    peers = sorted(float(c) for c in (cohort_costs or []) if c)
    if len(peers) >= _MIN_COST_EVENTS:
        cohort_p90 = _percentile(peers, 90)
        cohort_flag = bool(p50 > cohort_p90)   # this asset's typical event exceeds the cohort's P90

    interp = (f"Maintenance spend: P50 ${p50:,.0f}, P90 ${p90:,.0f} across {len(amounts)} costed events "
              "(material/services only - labor actuals are ~0, so no labor-cost or savings claim). "
              f"{over_own} event(s) exceed this asset's own P90."
              + (f" This asset's median event (${p50:,.0f}) is above the cohort P90 (${cohort_p90:,.0f}) - a cost "
                 "outlier vs like equipment." if cohort_flag else "")
              + " Whether a P90 exceedance is actionable is BU-defined (unset).")
    return tool_envelope(
        tool="sap_cost_distribution",
        status=STATUS_WARNING if (cohort_flag or over_own) else STATUS_SUCCESS,
        summary=f"Cost bands P10 ${p10:,.0f} / P50 ${p50:,.0f} / P90 ${p90:,.0f} ({len(amounts)} events, material/services).",
        data={**base_data, "computable": True, "n_events": len(amounts),
              "cost_p10": round(p10, 2), "cost_p50": round(p50, 2), "cost_p90": round(p90, 2),
              "events_over_own_p90": over_own, "cohort_p90": (round(cohort_p90, 2) if cohort_p90 is not None else None),
              "cohort_cost_outlier": cohort_flag, "interpretation": interp},
        confidence=_confidence(len(amounts)))
