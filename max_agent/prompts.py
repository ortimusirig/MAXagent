"""Narration prompts and a deterministic fallback summary.

The LLM (when a serving endpoint is bound) EXPLAINS the deterministic result in plain language.
It must never invent or override a gate status, a classifier label, or an Oxy value. When no LLM
endpoint is bound, `deterministic_summary` produces the same shape from the tool results directly,
so the app always has a chat answer.

Both paths are evidence-first: they cite the analysis MAX already ran (work-order counts, failure
coding, cost basis) and, when the data is not enough to conclude, name the SPECIFIC Oxy SAP data
still needed (from `evidence.py`, grounded in the Project Soar extract).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .labels import change_label, gate_label, reason_label, rec_label


def _gate_reason(result: Dict[str, Any]) -> Optional[str]:
    """The human gate reason. A BLOCKED gate carries a blocked_reason (gate_reason); a REVIEW_REQUIRED
    gate carries a review_trigger (gate_review_trigger). Fall back to the trigger so a REVIEW gate never
    renders 'reason None'."""
    return result.get("gate_reason") or result.get("gate_review_trigger")

# Data-readiness is a RAG code internally (GREEN/YELLOW/RED); in prose we describe it in plain language
# so the narrative never leaks an internal status token. The color still drives the UI badge/chip.
_READINESS_PHRASE = {
    "GREEN": "sufficient (readiness checks pass)",
    "YELLOW": "limited, with some data-quality gaps",
    "RED": "insufficient, with major data gaps",
    "NOT_REQUIRED": "not required for this PM",
}


def _readiness_phrase(rag: str) -> str:
    return _READINESS_PHRASE.get(rag, "not yet assessed")


def _gate_reason_code(result: Dict[str, Any]) -> Any:
    return result.get("gate_reason") or result.get("gate_review_trigger")


def _gate_reason_phrase(result: Dict[str, Any]) -> str:
    reason = _gate_reason_code(result)
    return reason_label(reason) if reason else ""


NARRATION_SYSTEM = (
    "You are MAX, a governed preventive-maintenance strategy copilot for Oxy. Explain the "
    "DETERMINISTIC result you are given in plain language for a planner or reliability engineer, as "
    "short bulleted findings. Always show your reasoning: cite the specific evidence you are given "
    "(work-order counts, failure-coding %, cost basis) - the data behind the recommendation. You must "
    "NOT change the classifier label, the gate status, the required approvers, or any Oxy value; only "
    "explain them. Cite ONLY numbers you are given; never invent a rate, a cost, or a threshold. Never "
    "claim realized savings, real CBM readiness, or a direct SAP write-back. When the data is not "
    "enough to conclude, say so plainly and list the specific SAP data still needed. Describe data "
    "readiness in plain language (e.g. 'limited data readiness', 'data gaps'); NEVER print the internal "
    "RAG status code (GREEN / YELLOW / AMBER / RED) in your prose. Keep it to Overview, What the data "
    "shows, and Recommendation, each a few bullets."
)


def _evidence_block(result: Dict[str, Any]) -> str:
    digest = result.get("evidence_digest") or {}
    lines = digest.get("lines") or []
    return "\n".join(f"- {l}" for l in lines) or "- (no scoped evidence records returned)"


def _needs_block(result: Dict[str, Any]) -> str:
    needs = result.get("data_needs") or []
    if not needs:
        return ""
    rows = "\n".join(f"- {n['need']} (SAP source: {n['sap_source']})" for n in needs)
    return "\nData still needed before MAX can SCORE effectiveness (state these plainly, do not invent others):\n" + rows


def narration_prompt(result: Dict[str, Any]) -> str:
    d = result
    lines = [
        f"Asset: {d.get('equipment_id')} ({d.get('asset_class')}), plant {d.get('plant')}.",
        f"User question: {d.get('user_question')}.",
        f"Classifier label: {d.get('classifier_label')} (data readiness is {_readiness_phrase(d.get('data_readiness_rag'))}, provenance {d.get('provenance')}).",
        f"Change under review: {d.get('change_under_review_type')} - gate {d.get('gate_status')}, reason {_gate_reason(d) or '-'}.",
        f"MAX recommendation: {rec_label(d.get('recommendation_type'))} - gate {gate_label(d.get('recommendation_gate_status'))} - {d.get('recommendation_rationale')}.",
        f"Recommendation differs from the change under review: {d.get('recommendation_diverges')}.",
        f"Required approvers: {', '.join(d.get('required_approvers') or []) or 'none'}.",
        "",
        "Evidence MAX already retrieved (cite these exact numbers; do not invent others):",
        _evidence_block(result),
        _needs_block(result),
        ("\nReliability read (EVIDENCE - state it prominently; it does NOT change the label or gate):\n"
         + "\n".join(f"- {b}" for b in _reliability_bullets(result))) if _reliability_bullets(result) else "",
        "",
        "Answer the user's question directly using ONLY these facts, as short bulleted findings under "
        "Overview / What the data shows (include the reliability read here) / Recommendation. Explain the "
        "data behind the recommendation. Do not contradict the gate or the label. Draft-only in Wave 1; "
        "humans approve; MDC/BPDO or the official Oxy process updates SAP.",
    ]
    return "\n".join(l for l in lines if l is not None)


def _question_opener(result: Dict[str, Any]) -> str:
    """A question-aware lead line so asking different things surfaces different content (no LLM)."""
    q = (result.get("user_question") or "").lower()
    if any(w in q for w in ("compare", "like equipment", "standardi", "other pump", "cohort")):
        cmp = result.get("comparison_result") or {}
        n = len(cmp.get("cohort", []))
        return f"You asked about comparison: {n} like-equipment match(es) - see the Comparison tab."
    if any(w in q for w in ("cost", "saving", "value", "hours")):
        return f"You asked about cost/value: cost view is {result.get('cost_view')} - no labor-savings claim is defensible in Wave 1."
    if any(w in q for w in ("block", "why", "reason", "allowed", "can we", "can i")):
        return f"You asked why: the change under review is {result.get('gate_status')} - {_gate_reason(result) or 'see the governance trace'}."
    if any(w in q for w in ("readiness", "task list", "materials", "cbm", "execute", "ready")):
        return "You asked about readiness: see the execution-readiness checks on the Evidence tab."
    if any(w in q for w in ("effective", "effectiveness", "working", "should anything change", "change")):
        return f"You asked about effectiveness: label is {result.get('classifier_label')}; MAX recommends {rec_label(result.get('recommendation_type'))}."
    return f"MAX assessed asset {result.get('equipment_id')}."


def _classifier_read(result: Dict[str, Any]) -> str:
    """The plain-language link between the evidence and the classifier's read (the 'why')."""
    label = result.get("classifier_label")
    dims = result.get("dimension_results") or {}
    reason = result.get("classifier_reason")
    if label == "Missing Evidence":
        if reason == "THRESHOLDS_UNSET":
            return ("MAX describes and flags only: Oxy has not confirmed the classifier scoring "
                    "thresholds yet, so MAX will not assert Effective or Ineffective.")
        return "MAX cannot score this PM on the evidence available; it describes and flags."
    if label == "Governance Review Required":
        basis = result.get("protection_basis") or "mandatory/criticality mandate"
        return f"This is a do-not-optimize PM ({basis}); it routes to governance review, not a reduce/retire."
    if dims:
        fails = [k.replace("_", " ") for k, v in dims.items() if v in ("FAIL", "SOFT_FAIL")]
        if fails:
            return f"Effectiveness dimensions falling short: {', '.join(fails)}."
        return "The effectiveness dimensions pass at or above the confirmed thresholds."
    return ""


def _reliability_bullets(result: Dict[str, Any]) -> List[str]:
    """Prominent, plain-language reliability read from tools 25-27 (EVIDENCE-ONLY - never moves the label
    or the gate; judgment thresholds stay BU_DEFINED)."""
    rel = result.get("reliability") or {}
    m, w, fm = rel.get("metrics") or {}, rel.get("weibull") or {}, rel.get("failure_modes") or {}
    out: List[str] = []
    if m.get("computable"):
        out.append(f"Reliability: MTBF about {m.get('mtbf_days')} days, MTTR ~{m.get('mttr_hours')}h, "
                   f"availability ~{m.get('availability_pct')}% over the window ({m.get('n_failures')} unplanned "
                   "failures); whether that MTBF is acceptable is a BU-defined threshold (unset).")
    if w.get("computable"):
        out.append(w.get("interpretation"))
    elif w.get("n_failures") is not None and w.get("min_failures"):
        out.append(f"Weibull hazard shape not computed - only {w.get('n_failures')} failure(s) "
                   f"(need {w.get('min_failures')} to fit a curve).")
    d = fm.get("dominant_mode")
    if fm.get("computable") and d:
        out.append(f"Dominant failure mode: {d.get('object_part') or 'unspecified part'} / "
                   f"{d.get('cause_code') or 'uncoded cause'} ({d.get('count')} of {fm.get('n_failures')}); "
                   f"{fm.get('uncoded_pct')}% of failures are uncoded.")
    return [b for b in out if b]


def deterministic_summary(result: Dict[str, Any]) -> str:
    """Plain-language, evidence-first summary built directly from the deterministic tool results.

    Structure (bulleted, matches the LLM narration shape): Overview -> What the data shows (the
    evidence + the classifier's read) -> [Not enough data to conclude, when applicable] ->
    Recommendation. Coherent by construction: the gate verdict is about the CHANGE UNDER REVIEW, and
    MAX's recommendation (with its own gate outcome) is stated separately.
    """
    gate = result.get("gate_status")
    reason = _gate_reason(result)
    change = result.get("change_under_review_type")
    rec_type = result.get("recommendation_type")
    rec_gate = result.get("recommendation_gate_status")
    rationale = result.get("recommendation_rationale")
    next_action = result.get("recommendation_next_action")
    diverges = result.get("recommendation_diverges")
    approvers = result.get("required_approvers") or []
    synthetic = result.get("provenance") == "SYNTHETIC"
    digest = result.get("evidence_digest") or {}
    needs = result.get("data_needs") or []

    verdict = {
        "PASS": f"The change under review ({change}) clears the Oxy gate and can move to a governed draft package for human review.",
        "REVIEW_REQUIRED": f"The change under review ({change}) is plausible but must go to human review before any action.",
        "BLOCKED": f"The change under review ({change}) is blocked by an Oxy business rule and should not proceed as asked.",
        "DRAFT_ONLY": f"The change under review ({change}) can be documented as a draft only; it cannot enter the approval/submit path yet.",
    }.get(gate, "Gate result unavailable.")

    parts: List[str] = [
        "**Overview**",
        f"- {_question_opener(result)}"
        + (" Data is SYNTHETIC (demo); no real Oxy recommendation is implied." if synthetic else ""),
    ]

    # What the data shows: the evidence MAX ran + how it reads.
    parts += ["", "**What the data shows**"]
    for line in digest.get("lines", []):
        parts.append(f"- {line}")
    read = _classifier_read(result)
    if read:
        parts.append(f"- {read}")
    # The 'low finding rate is not waste' note - only when the read above did not already cover the mandate.
    if result.get("do_not_optimize") and result.get("classifier_label") != "Governance Review Required":
        parts.append("- This is a do-not-optimize (mandatory / criticality-mandated) PM; a low finding rate is not treated as waste.")

    # Reliability read (EVIDENCE-ONLY, tools 25-27) - prominent, but never moves the label/gate.
    for b in _reliability_bullets(result):
        parts.append(f"- {b}")

    # Not enough data to conclude: name the specific SAP data needed.
    if needs:
        parts += ["", "**Not enough data to conclude**",
                  "- MAX is not asserting an Effective/Ineffective score for this PM; it describes and flags what the data shows."]
        for n in needs:
            parts.append(f"- Needs {n['need']} - SAP source: {n['sap_source']}.")

    # Recommendation + the gate on the change under review.
    parts += ["", "**Recommendation**",
              f"- MAX recommends {rec_label(rec_type)} (gate {gate_label(rec_gate)}). {rationale}"]
    if diverges:
        parts.append(
            f"- Note: MAX recommends {rec_label(rec_type)}, not the change under review ({change_label(change)}); "
            f"the SAP package drafts MAX's recommendation and is gate-checked separately."
        )
    parts.append(f"- Change under review: {verdict}" + (f" Reason: {reason}." if reason else ""))
    parts.append(f"- Next action: {next_action}. Required approvers: {', '.join(approvers) if approvers else 'none named yet'}.")
    parts.append("- Draft-only in Wave 1; humans approve; MDC/BPDO or the official Oxy process updates SAP.")
    return "\n".join(parts)


PREVIEW_SYSTEM = (
    "You are MAX, a governed preventive-maintenance strategy copilot for Oxy. Write a short, plain-"
    "language assessment of ONE PM for a reliability reviewer scanning a triage preview. One flowing "
    "paragraph (4-6 sentences), no bullets, no headers. Explain why this PM is in its current state, "
    "the key issues, what should be reviewed, and whether it warrants a deeper analysis. Use ONLY the "
    "facts you are given; cite the evidence numbers; never invent a value, a threshold, a saving, or a "
    "gate. Do not contradict the gate or the classifier label. Describe data readiness in plain language; "
    "NEVER print the internal RAG status code (GREEN / YELLOW / AMBER / RED) in your prose. Draft-only in "
    "Wave 1; MAX cannot write SAP."
)


def preview_narration_prompt(result: Dict[str, Any], concise: bool = False) -> str:
    d = result
    closing = (
        "Write a COMPACT assessment: 2-3 sentences, about HALF the length of a full review - the label + "
        "gate + why in the first sentence, the single most important evidence-backed issue next, and "
        "whether it warrants deeper analysis. The evidence figures are listed separately below the "
        "paragraph, so summarise at a high level; do NOT restate every number."
        if concise else
        "Write the one-paragraph assessment now."
    )
    lines = [
        f"Asset: {d.get('equipment_id')} ({d.get('asset_class')}), plant {d.get('plant')}, "
        f"criticality {d.get('criticality_code')} {d.get('criticality_label') or ''}.",
        f"Effectiveness label: {d.get('classifier_label')}; data readiness is {_readiness_phrase(d.get('data_readiness_rag'))}.",
        f"Governance gate: {d.get('gate_status')} - reason {_gate_reason(d) or '-'}.",
        f"MAX recommendation: {rec_label(d.get('recommendation_type'))} - {d.get('recommendation_rationale')}.",
        "Evidence MAX retrieved (cite these numbers, invent no others):",
        _evidence_block(result),
        _needs_block(result),
        "",
        closing,
    ]
    return "\n".join(l for l in lines if l is not None)


def preview_summary(result: Dict[str, Any], concise: bool = False) -> str:
    """Deterministic PM assessment (the fallback when no LLM is bound). concise=True is the shorter
    triage paragraph for the preview panel; the full version is kept for the Studio."""
    label = result.get("classifier_label")
    gate = result.get("gate_status")
    reason = _gate_reason(result)
    rec = result.get("recommendation_type")
    rationale = result.get("recommendation_rationale")
    digest = result.get("evidence_digest") or {}
    needs = result.get("data_needs") or []
    read = _classifier_read(result)

    if concise:
        # Compact triage paragraph (~half length): no full evidence dump - the 'Evidence MAX cited'
        # bullets rendered below the narrative already list the numbers.
        parts = [f"This PM is {label} with a {gate} gate" + (f" ({reason})" if reason else "") + "."]
        if read:
            parts.append(read)
        if needs:
            parts.append("It cannot be scored yet without " + "; ".join(n["need"] for n in needs[:2]) + ".")
        parts.append(f"MAX recommends {rec_label(rec)}: {rationale}")
        parts.append("The evidence below warrants a governed review before any change (draft-only; MAX does not write SAP).")
        return " ".join(p for p in parts if p)

    parts = [f"This PM is classified {label} and the governance gate is {gate}"
             + (f" ({reason})" if reason else "") + "."]
    lines = digest.get("lines") or []
    if lines:
        parts.append("What the data shows: " + " ".join(lines))
    if read:
        parts.append(read)
    if needs:
        parts.append("It cannot be scored yet - MAX needs "
                     + "; ".join(f"{n['need']} (SAP {n['sap_source']})" for n in needs[:3]) + ".")
    parts.append(f"MAX recommends {rec_label(rec)}: {rationale}")
    parts.append("This warrants a governed review before any change - draft-only in Wave 1; a human "
                 "approves and MAX does not write SAP.")
    return " ".join(p for p in parts if p)


# =====================================================================================================
# INTENT ROUTING + FREE-FLOW (conversational) path.
#
# MAX is free-flow by default; the governance DAG is a route the intent triggers. A turn is classified
# GOVERNED (needs a governed decision -> run the pipeline + fence) or FREE_FLOW (a follow-up / definition
# / greeting -> answer conversationally, read-only). The free-flow answer NEVER mints a governed value;
# it explains the LAST governed result + glossary. Fail-safe: when unsure, GOVERNED.
# =====================================================================================================

def _transcript_block(messages: List[Dict[str, Any]], limit: int = 6) -> str:
    lines = []
    for m in (messages or [])[-limit:]:
        if m.get("role") == "user":
            lines.append(f"User: {m.get('content', '')}")
        elif m.get("role") == "assistant":
            lines.append(f"MAX: {m.get('summary', '')}")
    return "\n".join(lines) or "(no prior turns)"


def _last_result_block(r: Dict[str, Any]) -> str:
    if not r:
        return "(no prior governed analysis in this conversation yet)"
    trig = _gate_reason(r) or "-"
    lines = [
        f"Asset: {r.get('equipment_id')} ({r.get('asset_class')}), criticality {r.get('criticality_code')} {r.get('criticality_label') or ''}.",
        f"Effectiveness label: {r.get('classifier_label')}.",
        f"Gate: {gate_label(r.get('gate_status'))} (trigger {trig}).",
        f"MAX's recommendation: {rec_label(r.get('recommendation_type'))} - {r.get('recommendation_rationale')}.",
        f"Required approvers: {', '.join(r.get('required_approvers') or []) or 'none named yet'}.",
    ]
    digest = (r.get("evidence_digest") or {}).get("lines") or []
    if digest:
        lines.append("Evidence MAX had: " + " ".join(digest))
    return "\n".join(lines)


def _glossary_block() -> str:
    from .labels import GATE_LABELS, RECOMMENDATION_LABELS
    lines = ["Governed terms (use these meanings; never invent others):"]
    for _code, (label, meaning) in RECOMMENDATION_LABELS.items():
        if meaning:
            lines.append(f"- {label}: {meaning}")
    for _code, label in GATE_LABELS.items():
        lines.append(f"- Gate '{label}': the governance outcome for a proposed change.")
    lines += [
        "- do-not-optimize / criticality mandate: a high-criticality PM whose coverage cannot be reduced "
        "on evidence alone; it routes to governance review, never an automatic reduce/retire.",
        "- keep-coverage improvement: improving the PM (task list, coding) WITHOUT reducing how often or "
        "how much it runs.",
        "- draft-only (Wave 1): MAX drafts a change package for a human to approve; it never writes SAP.",
    ]
    return "\n".join(lines)


INTENT_SYSTEM = (
    "You are the intent router for MAX, a governed preventive-maintenance copilot. Classify the user's "
    "LATEST message as exactly one word:\n"
    "- GOVERNED: it needs a governed DECISION or fresh analysis about an asset (is a PM effective; should "
    "we change / reduce / retire / extend / shorten / convert it; what is the gate or recommendation; "
    "analyse, compare, cost, or readiness of a specific PM or the fleet), OR it names a DIFFERENT asset "
    "than the one just analysed.\n"
    "- FREE_FLOW: it is a follow-up, clarification, or definition about the PREVIOUS answer, a general or "
    "explanatory question, or a greeting ('what does that mean', 'why', 'explain', 'what is X', 'how does "
    "this work', 'thanks', 'hi'). ALSO FREE_FLOW: a request to FETCH or SHOW existing DATA about the SAME "
    "asset just analysed (its work orders, cost, failures, reliability, readiness, components); APPROVING / "
    "rejecting / signing off on the recommendation just discussed ('approve it', 'reject this', 'sign "
    "off'); or asking whether a change is ALLOWED / would pass the gate / can bypass a review ('is that "
    "allowed', 'can I reduce it', 'would extending pass', 'can we skip review') for the SAME asset - MAX "
    "previews the gate (advisory) or surfaces the approval action; it does NOT run a fresh governed "
    "decision.\n"
    "When in doubt, answer GOVERNED. Reply with ONLY the single word GOVERNED or FREE_FLOW."
)


def intent_prompt(question: str, messages: List[Dict[str, Any]], has_last_result: bool = False) -> str:
    prior = ("There IS a prior governed result in this conversation to explain."
             if has_last_result else
             "There is NO prior governed result yet, so an explanatory / follow-up ask cannot be answered "
             "from one - if the message needs analysis, classify GOVERNED.")
    return (f"Conversation so far:\n{_transcript_block(messages)}\n\n"
            f"Context: {prior}\n\n"
            f"Latest user message: {question}\n\nClassify it (GOVERNED or FREE_FLOW):")


def _fix_preamble(gate_status, prior_text) -> str:
    """The ONE corrective re-prompt, shared by governed narration and free-flow. Prepended to the normal
    prompt when the first draft affirmed a change the gate did not pass."""
    return ("CORRECTION: your previous draft implied the change was approved / cleared / safe to "
            f"proceed, but the governance gate is {gate_status} and did NOT pass this change. "
            "Rewrite it: explain the gate outcome and the reviewer's next step, keep every factual "
            "number, and use NO approving language (no 'go ahead', 'safe to reduce/retire', "
            f"'cleared to proceed'). Your previous draft was:\n'''{prior_text}'''\n\nCorrected answer:\n\n")


# Deliberately NOT including bare "what is" / "what's" - they are ambiguous ("what's the cost view" is a
# governed ask, not a definition). The offline floor stays conservative (bias to GOVERNED); the LLM
# router handles the ambiguous cases when an endpoint is bound.
_EXPLAIN_HINTS = ("what does", "what do you mean", "explain", "meaning", "clarify", "elaborate",
                  "tell me more", "how does this work", "what makes", "why is", "why did", "why does")
_GREET_HINTS = ("hello", "hi", "hey", "thanks", "thank you", "who are you", "what can you do")

# Data-FETCH carve-out: a request to pull/show EXISTING data about the asset just analysed is a read,
# not a new decision - route it to the fast free-flow read loop. Kept narrow on purpose: it needs an
# explicit fetch verb AND a reference to the current asset, AND must not carry a decision verb or name
# a specific equipment id (a raw id may be a DIFFERENT asset -> let the governed pipeline resolve it).
# Bare read verbs (not just compound forms) so "show it" / "list this" / "display the components"
# also count as a fetch; the decision-hint + equipment-id + current-asset guards below keep this from
# ever misrouting a governed decision to free-flow (a false negative only ever fails safe to GOVERNED).
_FETCH_HINTS = ("fetch", "show", "list", "display", "pull", "read the", "give me the",
                "how many", "what data", "what records", "what's on")
_CURRENT_ASSET_HINTS = ("current asset", "this asset", "that asset", "the current", "current pm",
                        "this pm", "that pm", "the same", "same asset", "this one", "that one",
                        "this pump", "this compressor", "this valve", "this motor", "this equipment",
                        " it", " its ", "for it")
_DECISION_HINTS = ("effective", "should we", "should i", "change", "reduce", "retire", "extend",
                   "shorten", "convert", "recommend", "recommendation", "gate", "optimi", "analyse",
                   "analyze", "assess", "evaluate", "compare", "retain", "approve")
_EID_RE = re.compile(r"[A-Za-z]{2,}-\d{2,}")  # e.g. PUMP-4110, COMP-2201


def _is_data_fetch_followup(q: str, raw: str) -> bool:
    """A read/fetch of existing data about the CURRENT asset (not a new decision, not a different id)."""
    return (any(f in q for f in _FETCH_HINTS)
            and any(c in q for c in _CURRENT_ASSET_HINTS)
            and not any(d in q for d in _DECISION_HINTS)
            and not _EID_RE.search(raw or ""))


def deterministic_intent(question: str, has_last_result: bool) -> str:
    """Keyword floor used only when no LLM is bound. Biased hard toward GOVERNED (the safe direction)."""
    q = (question or "").lower().strip()
    if any(q == g or q.startswith(g + " ") or q.startswith(g + ",") for g in _GREET_HINTS):
        return "FREE_FLOW"
    if has_last_result and (q in ("why", "why?", "how", "how?", "what does it mean", "what does it mean?")
                            or any(h in q for h in _EXPLAIN_HINTS)):
        return "FREE_FLOW"
    if has_last_result and _is_data_fetch_followup(q, question or ""):
        return "FREE_FLOW"
    # Approve/reject and advisory "is X allowed / would it pass" follow-ups on the analysed asset are
    # free-flow: MAX previews the gate (advisory, read-only) or surfaces the approval action (the human
    # commits it) - neither runs a fresh governed decision. (Defined in the sub-intent section below.)
    if has_last_result and (any(h in q for h in _FF_APPROVAL_HINTS)
                            or any(h in q for h in _FF_GATECHECK_HINTS)):
        return "FREE_FLOW"
    return "GOVERNED"


FREE_FLOW_SYSTEM = (
    "You are MAX, a governed preventive-maintenance strategy copilot for Oxy. Answer the user's message "
    "conversationally in plain language, using the conversation so far and the LAST governed result "
    "provided.\n"
    "You MAY: explain or define the governed terms; explain WHY the last result is what it is (its gate, "
    "label, recommendation, approvers); discuss the data and the process; answer follow-ups and "
    "greetings.\n"
    "You must NEVER assert a NEW gate status, effectiveness label, recommendation, or any Oxy value "
    "(threshold, cost, approver, savings) for an asset - those come ONLY from running the governance "
    "tools. If the user is asking for a new decision or a fresh analysis, tell them you will run it. "
    "Never invent a value. Draft-only in Wave 1: MAX does not write SAP. No emoji. Be concise and "
    "genuinely helpful."
)


def free_flow_prompt(question: str, messages: List[Dict[str, Any]], last_result: Dict[str, Any]) -> str:
    return (f"{_glossary_block()}\n\n"
            f"LAST GOVERNED RESULT in this conversation (reference and explain it; do not state a new "
            f"decision):\n{_last_result_block(last_result)}\n\n"
            f"Conversation so far:\n{_transcript_block(messages)}\n\n"
            f"User's message: {question}\n\nAnswer it now, grounded in the above:")


def deterministic_free_flow(question: str, last_result: Dict[str, Any]) -> str:
    """Offline fallback: a governed, read-only explanation from the last result + glossary (no LLM)."""
    from .labels import gate_label, rec_label, rec_meaning
    if not last_result:
        return ("I can explain a PM once we have looked at one. Ask me about a specific PM (for example, "
                "'is the PM on PUMP-4110 effective?') and I will run the governed analysis - then I can "
                "explain any part of it.")
    r = last_result
    # Data-FETCH follow-up: surface the evidence MAX already has on file (no re-run, no new decision).
    if _is_data_fetch_followup((question or "").lower(), question or ""):
        lines = list((r.get("evidence_digest") or {}).get("lines") or [])
        for extra in (r.get("reliability_interpretation"), r.get("bom_interpretation")):
            if extra:
                lines.append(extra)
        if lines:
            body = " ".join(lines)
            return (f"Here is what MAX already has on file for {r.get('equipment_id')} "
                    f"(read-only; this does not change the governed decision): {body}")
    rec = r.get("recommendation_type")
    parts = [f"For {r.get('equipment_id')}, MAX's recommendation is **{rec_label(rec)}**."]
    if rec_meaning(rec):
        parts.append(rec_meaning(rec))
    trig = _gate_reason(r)
    parts.append(f"The gate is **{gate_label(r.get('gate_status'))}**" + (f" ({trig})." if trig else "."))
    if r.get("classifier_label"):
        parts.append(f"The effectiveness label is {r.get('classifier_label')}.")
    parts.append("This explains the last governed result - it does not change it. Ask me to analyse a "
                 "specific PM for a new decision.")
    return " ".join(parts)


# =====================================================================================================
# FREE-FLOW SUB-INTENT: a free-flow turn is one of
#   INFO       - explain / define / look up data (read-only tools, no gate).
#   GATE_CHECK - an ADVISORY "is X allowed / would it pass?" - runs the deterministic gate READ-ONLY and
#                reports the verdict; it is a preview, never the authoritative decision, and drafts nothing.
#   APPROVAL   - approve / reject / request-changes on the recommendation just discussed - the LLM only
#                SURFACES inline buttons; the authenticated human clicks and approval_workflow_state decides.
# Fail-safe: unclear -> INFO (the read-only, action-free branch).
# =====================================================================================================
_FF_APPROVAL_HINTS = ("approve", "sign off", "sign-off", "reject", "request change", "authorize",
                      "authorise", "i approve", "approve it", "reject it", "decline it", "endorse",
                      "give it the go-ahead", "green-light it", "greenlight it")
_FF_GATECHECK_HINTS = ("is it allowed", "is that allowed", "am i allowed", "are we allowed", "can i ",
                       "can we ", "would it pass", "would that pass", "would this pass", "does it pass",
                       "is it ok to", "ok to ", "allowed to", "bypass", "skip the review", "skip review",
                       "without a review", "without review", "is it blocked", "would extending",
                       "would shortening", "would retiring", "would reducing", "what if we", "would this clear",
                       "does this clear", "clear the gate", "pass the gate", "get past the gate")


def classify_free_flow_intent_deterministic(question: str, has_last_result: bool) -> str:
    """Keyword floor (used when no LLM is bound). Biased to INFO (read-only, action-free) when unsure."""
    q = (question or "").lower().strip()
    if not has_last_result:
        return "INFO"
    if any(h in q for h in _FF_APPROVAL_HINTS):
        return "APPROVAL"
    if any(h in q for h in _FF_GATECHECK_HINTS):
        return "GATE_CHECK"
    return "INFO"


FREE_FLOW_INTENT_SYSTEM = (
    "You classify a FOLLOW-UP chat message in a governed preventive-maintenance copilot as exactly one word:\n"
    "- APPROVAL: the user wants to APPROVE / reject / sign off / request changes on the recommendation just "
    "discussed ('approve it', 'reject this', 'sign off', 'request changes').\n"
    "- GATE_CHECK: the user asks whether a change is ALLOWED / would pass the gate / can be done / can "
    "bypass a review ('is that allowed', 'can I reduce it', 'would extending pass', 'can we skip review').\n"
    "- INFO: anything else - explain, define, look up data, 'why', compare.\n"
    "When unsure, answer INFO. Reply with ONLY one word: INFO, GATE_CHECK, or APPROVAL."
)


def free_flow_intent_prompt(question: str, messages: List[Dict[str, Any]]) -> str:
    return (f"Conversation so far:\n{_transcript_block(messages)}\n\nLatest message: {question}\n\n"
            "Classify it (INFO / GATE_CHECK / APPROVAL):")


GATE_CHECK_SYSTEM = (
    "You are MAX, a governed preventive-maintenance copilot for Oxy. The user is asking whether a change "
    "would be ALLOWED for the asset just analysed. Give an ADVISORY, READ-ONLY answer.\n"
    "You MAY call preview_gate_check(change_type, direction) to run the REAL deterministic Oxy gate on a "
    "HYPOTHETICAL change and read its verdict, and governed_decision to read the change already analysed. "
    "State the gate verdict (PASS / REVIEW_REQUIRED / BLOCKED / DRAFT_ONLY) and the reason in plain language.\n"
    "CRITICAL: this is a PREVIEW, not a decision. Never say a change is approved or safe to proceed - even "
    "on a PASS, say it 'would clear the gate' and that a GOVERNED REVIEW is still required to make it "
    "official (that run produces the change package and the approver list). You cannot bypass, waive, or "
    "skip a governance review; if asked to, say MAX cannot and explain the proper path. Never invent an Oxy "
    "value. No emoji. Be concise."
)


def gate_check_prompt(question: str, messages: List[Dict[str, Any]], last_result: Dict[str, Any]) -> str:
    return (f"{_glossary_block()}\n\nLAST GOVERNED RESULT (the change already analysed):\n"
            f"{_last_result_block(last_result)}\n\nConversation so far:\n{_transcript_block(messages)}\n\n"
            f"User's message: {question}\n\nGive the advisory gate answer now:")


def advisory_gate_answer(question: str, last_result: Dict[str, Any]) -> str:
    """Deterministic advisory gate answer from the last governed result (offline fallback for GATE_CHECK)."""
    from .labels import change_label, gate_label
    if not last_result:
        return ("I can preview the gate once we have analysed a PM. Ask me to review a specific PM first "
                "(for example, 'is the PM on PUMP-4110 effective?').")
    r = last_result
    change = change_label(r.get("change_under_review_type"))
    gl = gate_label(r.get("gate_status"))
    trig = _gate_reason(r)
    lead = (f"Advisory read (a preview, not a new decision) for {r.get('equipment_id')}: the change you "
            f"asked about ({change}) is **{gl}**" + (f" - {trig}." if trig else "."))
    if r.get("gate_status") == "PASS":
        tail = (" It would clear the gate, but a governed review is still required to make it official - "
                "that run produces the draft change package and the approver list. MAX cannot skip it.")
    else:
        tail = (" It cannot proceed as asked, and MAX cannot bypass or waive the review. A governed review "
                "is the path; to act on MAX's recommendation instead, ask me to run the governed review.")
    return lead + tail


def approval_leadin(last_result: Dict[str, Any]) -> str:
    """The short lead-in MAX writes before the inline approve/reject buttons (it only SURFACES them)."""
    from .labels import gate_label, rec_label
    r = last_result or {}
    return (f"Here is the governed recommendation for {r.get('equipment_id')} to act on: "
            f"**{rec_label(r.get('recommendation_type'))}** (package gate "
            f"{gate_label(r.get('package_gate_status'))}). Use the buttons below - your click is checked "
            "against your role and the gate, recorded to the audit trail, and never writes SAP. MAX "
            "surfaces the action; it cannot approve on your behalf.")
