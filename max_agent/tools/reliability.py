"""Reliability-analytics EVIDENCE tools (Wave B, 60/07 extension - tools 25-27).

These compute reliability facts from the asset's failure history and a MATH-DEFENSIBLE interpretation.
They are EVIDENCE ONLY: they feed the narration + the recommendation rationale + the reliability
artifact; they DO NOT change the classifier label or the gate (that stays 70/09-spec'd, Oxy-threshold-
gated). Every judgment threshold (what MTBF is 'acceptable', which beta warrants CBM) stays BU_DEFINED /
null until Oxy confirms it - the tools report the number and the hazard SHAPE (which is arithmetic), not
the policy call. Fail-closed: too little data -> NOT_COMPUTABLE + the SAP field still needed. No invented
values; low sample -> low confidence; synthetic failure dates are flagged.

Input is the asset's `failure_events` list (one per unplanned failure): each maps to the SOAR
Notifications sheet - failure_start_date = Failure_Start_Date, downtime_hrs = Breakdown_Duration,
damage_code = Damage_Code (QMFE), cause_code = Cause_Code (QMUR), object_part = Object_Part_Code.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List

from ..schemas import STATUS_SUCCESS, STATUS_WARNING, tool_envelope

# Weibull fit needs enough failures to be meaningful; below this we fail closed rather than fit on noise.
_WEIBULL_MIN_FAILURES = 4


# --- Weibull math (method-of-moments; mirrors the reference PdM agent, pure `math`) -----------------
def _weibull_mom_fit(mean_days: float, sd_days: float):
    """(beta, eta) by method of moments: beta ~= 1.086/CV; eta = mean / Gamma(1 + 1/beta). Clamped."""
    if not mean_days or mean_days <= 0:
        return 1.0, 1.0
    sd = sd_days if sd_days and sd_days > 0 else max(mean_days * 0.3, 1.0)
    cv = sd / mean_days
    beta = max(0.5, min(5.0, 1.086 / cv if cv > 0 else 1.0))
    eta = mean_days / math.gamma(1 + 1.0 / beta)
    return round(beta, 3), round(eta, 1)


def _p_fail_conditional(t_days: float, horizon_days: int, beta: float, eta: float) -> float:
    """P(fail within horizon | alive at t): 1 - S(t+H)/S(t), S(t)=exp(-(t/eta)^beta)."""
    if not eta or eta <= 0:
        return 0.0
    try:
        s_now = math.exp(-(t_days / eta) ** beta) if t_days > 0 else 1.0
        s_then = math.exp(-((t_days + horizon_days) / eta) ** beta)
        return round(max(0.0, min(1.0, 1.0 - (s_then / s_now))), 3) if s_now > 0 else 0.0
    except (OverflowError, ValueError):
        return 0.0


def _rul_quantiles(t_days: float, beta: float, eta: float) -> Dict[str, float]:
    """Conditional remaining-useful-life quantiles: rul_p10 (early), p50 (median), p90 (late) in days."""
    out = {}
    if not eta or eta <= 0 or not beta or beta <= 0:
        return {"rul_p10": 0.0, "rul_p50": 0.0, "rul_p90": 0.0}
    for label, surv in (("rul_p10", 0.90), ("rul_p50", 0.50), ("rul_p90", 0.10)):
        try:
            out[label] = round(max(0.0, eta * ((-math.log(surv)) ** (1.0 / beta)) - t_days), 1)
        except (ValueError, OverflowError):
            out[label] = 0.0
    return out


def _hazard_shape(beta: float):
    """Arithmetic interpretation of the Weibull shape (NOT an Oxy policy call). Returns (shape, plain)."""
    if beta >= 1.2:
        return ("WEAR_OUT", "wear-out pattern (failure hazard rises with age) - a time-based PM is the "
                            "right lever; a shorter interval or condition monitoring is worth reviewing")
    if beta <= 0.85:
        return ("INFANT_MORTALITY", "early-life pattern (failures cluster early, hazard falls with age) - "
                                    "PM frequency is not the lever; investigate installation / build quality")
    return ("RANDOM", "roughly random failures (near-constant hazard) - a time-based PM adds little; "
                      "condition-based monitoring or run-to-failure is worth reviewing")


def _intervals(events: List[Dict[str, Any]]) -> List[float]:
    """Inter-failure intervals (days) from the failure ages within the window (as-good-as-new proxy)."""
    ages = sorted(e.get("age_days", 0) for e in events)
    prev, out = 0, []
    for a in ages:
        out.append(max(0.0, a - prev))
        prev = a
    return out


def _confidence(n: int) -> str:
    return "low" if n < 7 else ("medium" if n < 12 else "high")


# --- Tool 25: reliability_metrics (MTBF / MTTR / availability) --------------------------------------
def reliability_metrics(failure_events: List[Dict[str, Any]], window_days: int = 730,
                        synthetic: bool = True) -> Dict[str, Any]:
    """MTBF (days), MTTR (hours), availability (%) from the failure history. Judgment ('is MTBF
    acceptable?') stays BU_DEFINED; this reports the numbers + a neutral read. Fail-closed if no
    failures / no downtime."""
    events = failure_events or []
    n = len(events)
    if n == 0:
        return tool_envelope(
            tool="reliability_metrics", status=STATUS_WARNING,
            summary="No unplanned failures in the window - MTBF/MTTR not computable.",
            data={"computable": False, "n_failures": 0,
                  "data_needed": "Failure events (SAP Notifications: Failure_Start_Date) over the window."},
            confidence="low")
    downtimes = [float(e.get("downtime_hrs") or 0) for e in events]
    total_downtime = sum(downtimes)
    mtbf_days = round(window_days / n, 1)
    mttr_hours = round(total_downtime / n, 1) if total_downtime > 0 else None
    window_hours = window_days * 24
    availability = round(100.0 * (window_hours - total_downtime) / window_hours, 2) if window_hours else None
    interp = (f"MTBF is about {mtbf_days} days over the window ({n} unplanned failures). Whether that is "
              "acceptable is a BU-defined threshold (unset) - this is the measured value, not a pass/fail.")
    return tool_envelope(
        tool="reliability_metrics", status=STATUS_SUCCESS,
        summary=f"MTBF {mtbf_days}d, MTTR {mttr_hours}h, availability {availability}% ({n} failures).",
        data={"computable": True, "n_failures": n, "window_days": window_days,
              "mtbf_days": mtbf_days, "mttr_hours": mttr_hours, "availability_pct": availability,
              "mtbf_basis": "counts_over_window", "synthetic_flag": synthetic,
              "acceptable_threshold": None, "interpretation": interp},
        confidence=_confidence(n))


# --- Tool 26: weibull_reliability (hazard shape / P(fail) / RUL) ------------------------------------
def weibull_reliability(failure_events: List[Dict[str, Any]], window_days: int = 730,
                        horizon_days: int = 90, synthetic: bool = True) -> Dict[str, Any]:
    """Weibull hazard shape + conditional P(fail in horizon) + RUL quantiles, as an EVIDENCE input to
    the strategy recommendation. Fail-closed below _WEIBULL_MIN_FAILURES (never fit on 2-3 points). The
    beta->CBM band stays BU_DEFINED; the reported SHAPE (wear-out/random/infant) is arithmetic."""
    events = failure_events or []
    n = len(events)
    if n < _WEIBULL_MIN_FAILURES:
        return tool_envelope(
            tool="weibull_reliability", status=STATUS_WARNING,
            summary=f"Only {n} failures - below the {_WEIBULL_MIN_FAILURES} needed to fit a Weibull; not computed.",
            data={"computable": False, "n_failures": n, "min_failures": _WEIBULL_MIN_FAILURES,
                  "data_needed": "More dated failure events (SAP Notifications: Failure_Start_Date) to fit a hazard curve."},
            confidence="low")
    intervals = _intervals(events)
    mean_i = statistics.mean(intervals) if intervals else 0.0
    sd_i = statistics.pstdev(intervals) if len(intervals) > 1 else 0.0
    beta, eta = _weibull_mom_fit(mean_i, sd_i)
    shape, plain = _hazard_shape(beta)
    # Current running age = time SINCE the last failure/repair (as-good-as-new proxy), not the age AT it.
    t_now = max(0.0, window_days - max((e.get("age_days", 0) for e in events), default=0))
    p_fail = _p_fail_conditional(t_now, horizon_days, beta, eta)
    rul = _rul_quantiles(t_now, beta, eta)
    interp = (f"The failure history fits a {plain} (Weibull shape beta={beta}). "
              f"Estimated probability of a failure in the next {horizon_days} days is about {round(p_fail * 100)}%. "
              "The beta->strategy threshold is BU-defined (unset); this is the reliability shape, not an Oxy policy call."
              + (" Illustrative on synthetic failure dates until SOAR Failure_Start_Date is bound." if synthetic else ""))
    return tool_envelope(
        tool="weibull_reliability", status=STATUS_SUCCESS,
        summary=f"Weibull beta={beta} ({shape}); P(fail in {horizon_days}d) ~ {round(p_fail * 100)}%.",
        data={"computable": True, "n_failures": n, "beta": beta, "eta_days": eta, "hazard_shape": shape,
              "p_fail_horizon": p_fail, "horizon_days": horizon_days, "rul_days": rul,
              "synthetic_flag": synthetic, "cbm_threshold": None, "interpretation": interp},
        confidence=_confidence(n))


# --- Tool 27: failure_mode_summary (light RCA grouping) ---------------------------------------------
def failure_mode_summary(failure_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Top failure modes grouped by object-part x cause code, the dominant mode, and the uncoded share
    (the coding gap, flagged never guessed). Pure counting - no policy, no invented codes."""
    events = failure_events or []
    n = len(events)
    if n == 0:
        return tool_envelope(
            tool="failure_mode_summary", status=STATUS_WARNING,
            summary="No failures to analyse for failure modes.",
            data={"computable": False, "n_failures": 0,
                  "data_needed": "Coded notifications (SAP: Damage_Code / Cause_Code / Object_Part_Code)."},
            confidence="low")
    groups: Dict[str, Dict[str, Any]] = {}
    uncoded = 0
    for e in events:
        part, cause = e.get("object_part"), e.get("cause_code")
        if not cause and not part:
            uncoded += 1
            continue
        key = f"{part or 'UNSPEC'} / {cause or 'UNSPEC_CAUSE'}"
        g = groups.setdefault(key, {"object_part": part, "cause_code": cause, "count": 0})
        g["count"] += 1
    modes = sorted(groups.values(), key=lambda g: g["count"], reverse=True)
    for m in modes:
        m["share_pct"] = round(100.0 * m["count"] / n)
    dominant = modes[0] if modes else None
    uncoded_pct = round(100.0 * uncoded / n)
    interp = (f"{n} unplanned failures; " + (f"the dominant mode is {dominant['object_part'] or 'unspecified part'} / "
              f"{dominant['cause_code'] or 'uncoded cause'} ({dominant['count']} of {n}). " if dominant else "no coded modes. ")
              + f"{uncoded_pct}% of failures are uncoded and cannot be analysed - close the coding gap to make "
                "root-cause defensible.")
    return tool_envelope(
        tool="failure_mode_summary", status=STATUS_SUCCESS,
        summary=f"{len(modes)} failure mode(s); dominant "
                + (f"{dominant['object_part']}/{dominant['cause_code']}" if dominant else "-")
                + f"; {uncoded_pct}% uncoded.",
        data={"computable": True, "n_failures": n, "modes": modes, "dominant_mode": dominant,
              "uncoded_pct": uncoded_pct, "interpretation": interp},
        confidence="medium" if n >= 4 else "low")
