"""Governance tools: ``oxy_gate_check`` and ``approval_workflow_state``.

``oxy_gate_check`` is the deterministic business-rule gate. It is implemented to match the
truth table, predicate definitions, status precedence, and Python pseudocode in
``70 - MAX Agent Build/08 - oxy_gate_check Specification and Unit Tests`` line for line. The
LLM may explain the gate result but must never invent it.

Two design points that protect the safety property:

1. Scope is checked FIRST, fail-closed, before any predicate reads criticality /
   recommendation / readiness (08 pseudocode). validate_scope produces the ``scope`` object.
2. The rule order IS the precedence: hard BLOCKs, then DRAFT_ONLY holds, then REVIEW_REQUIRED
   routes, then PASS. To keep unit tests from being masked by the final "criticality 2/3/4 or
   changes_strategy -> REVIEW" catch-all, every REVIEW_REQUIRED result carries a distinct
   ``review_trigger`` and every BLOCKED / DRAFT_ONLY a distinct ``blocked_reason``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import (
    STATUS_BLOCKED,
    STATUS_SUCCESS,
    STATUS_WARNING,
    tool_envelope,
)

# --- Gate status values (carried inside data.gate_status) ---
GATE_PASS = "PASS"
GATE_REVIEW_REQUIRED = "REVIEW_REQUIRED"
GATE_BLOCKED = "BLOCKED"
GATE_DRAFT_ONLY = "DRAFT_ONLY"

_CRITICAL_CODES = {"2", "3", "4"}
_STRONG_DATA_TYPES = {
    "PM_FREQUENCY_CHANGE",
    "RETIRE_PM",
    "MOVE_TO_RTF",
    "ADD_CBM",
    "CBM_CONVERSION",
    "SAP_OBJECT_CHANGE",
    "STRATEGY_PACKAGE",
    "STRATEGY_TYPE_CHANGE",
}
_SCORECARD_TYPES = {
    "PM_FREQUENCY_CHANGE",
    "RETIRE_PM",
    "MOVE_TO_RTF",
    "STRATEGY_TYPE_CHANGE",
    "STRATEGY_PACKAGE",
}
_NON_STRATEGY_TYPES = {"RETAIN_PM", "DATA_CLEANUP", None}
_APPROVAL_PATH_ACTIONS = {"DRAFT_PACKAGE", "SUBMIT_FOR_APPROVAL", "MASTER_DATA_SUBMIT"}
_BEYOND_DRAFT_ACTIONS = {"SUBMIT_FOR_APPROVAL", "MASTER_DATA_SUBMIT"}


# ---------------------------------------------------------------------------
# Predicates (each mirrors a row in the 08 "Predicate Definitions" table)
# ---------------------------------------------------------------------------

def recommendation_reduces_pm_coverage(recommendation: Dict[str, Any]) -> bool:
    rtype = recommendation.get("type")
    if rtype == "PM_FREQUENCY_CHANGE" and recommendation.get("direction") == "EXTEND":
        return True
    if rtype in {"RETIRE_PM", "REMOVE_TASK", "MOVE_TO_RTF"}:
        return True
    if recommendation.get("strategy_type") == "RTF":
        return True
    if rtype == "CONSOLIDATE" and recommendation.get("results_in_fewer_checks"):
        return True
    return False


def recommendation_changes_strategy(recommendation: Dict[str, Any]) -> bool:
    return recommendation.get("type") not in _NON_STRATEGY_TYPES


def risk_scorecard_required(criticality: Dict[str, Any], recommendation: Dict[str, Any]) -> bool:
    if recommendation_reduces_pm_coverage(recommendation):
        return True
    if recommendation.get("type") in _SCORECARD_TYPES:
        return True
    if recommendation.get("strategy_type") == "RTF":
        return True
    return False


def recommendation_requires_strong_data(recommendation: Dict[str, Any]) -> bool:
    if recommendation.get("type") in _STRONG_DATA_TYPES:
        return True
    if recommendation.get("strategy_type") == "RTF":
        return True
    return False


def recommendation_requires_approval_path(recommendation: Dict[str, Any]) -> bool:
    return recommendation.get("type") not in {"DATA_CLEANUP", "CHAT", None}


def execution_dependency_blocked(readiness: Dict[str, Any]) -> bool:
    # A readiness domain required by the recommendation is RED. Non-required domains carry
    # NOT_REQUIRED / GREEN, so a RED value implies the domain is both needed and blocked.
    return any(
        readiness.get(domain) == "RED"
        for domain in ("component_readiness", "contractor_service_readiness", "cbm_readiness")
    )


def criticality_not_validated(criticality: Dict[str, Any]) -> bool:
    code = criticality.get("code")
    if code in {"0", "", None}:
        return True
    if criticality.get("validation_status") != "VALIDATED":
        return True
    if criticality.get("equipment_floc_conflict"):
        return True
    if criticality.get("stale"):
        return True
    return False


def resolve_pm_requirement(criticality_code: Any, overrides: Dict[str, Any]) -> str:
    return overrides.get(str(criticality_code), "BU_DISCRETION")


def mandatory_pm(pm_governance: Dict[str, Any], criticality_mandate: str) -> bool:
    per_pm_mandatory = pm_governance.get("mandatory_pm") is True
    return criticality_mandate == "MANDATORY" or per_pm_mandatory


def cbm_readings_missing(recommendation: Dict[str, Any], readiness: Dict[str, Any]) -> bool:
    adds_cbm = recommendation.get("type") in {"ADD_CBM", "CBM_CONVERSION"}
    if not adds_cbm:
        return False
    return readiness.get("cbm_real_readings_available") is not True


def critical_work_catalog_codes(bu_profile: Dict[str, Any]) -> set:
    return {
        item.get("code")
        for item in bu_profile.get("critical_work_code_catalog", [])
        if item.get("code")
    }


def abc4_object_dependency_missing(
    criticality: Dict[str, Any], readiness: Dict[str, Any], bu_profile: Dict[str, Any]
) -> bool:
    if criticality.get("code") != "4":
        return False
    allowed_codes = critical_work_catalog_codes(bu_profile)
    return readiness.get("object_dependency_code") not in allowed_codes


def level_loading_required_but_deferred(
    bu_profile: Dict[str, Any], readiness: Dict[str, Any], requested_action: str
) -> bool:
    # Stage-7 level loading is a deployment gate. It only constrains master-data submission.
    if requested_action != "MASTER_DATA_SUBMIT":
        return False
    # A completed / attested level load (or a future attestation workflow) clears the hold.
    if readiness.get("level_loading_status") in {"COMPLETE", "ATTESTED"}:
        return False
    # Otherwise: deferred in Wave 1 (toggle off) or required-but-incomplete -> hold draft-only.
    # Consumed for completeness: the profile toggle distinguishes "deferred" from
    # "required-incomplete"; both converge on the same safe DRAFT_ONLY outcome.
    _toggled_on = bool((bu_profile.get("optional_step_toggles") or {}).get("level_loading"))
    return True


def strategy_type_disabled(recommendation: Dict[str, Any], bu_profile: Dict[str, Any]) -> bool:
    strategy_type = recommendation.get("strategy_type")
    if strategy_type is None:
        return False
    return strategy_type not in bu_profile.get("enabled_strategy_types", [])


def acceptance_criterion_rejected_without_follow_on(readiness: Dict[str, Any]) -> bool:
    if readiness.get("acceptance_criteria_result") != "REJECTED":
        return False
    if readiness.get("follow_on_crmn_expected") or readiness.get("follow_on_crmn_created"):
        return False
    return True


def moc_threshold_exceeded(recommendation: Dict[str, Any], bu_profile: Dict[str, Any]) -> bool:
    if recommendation.get("moc_threshold_exceeded") is True:
        return True
    threshold = (bu_profile.get("moc_threshold") or {}).get("change_magnitude_requires_moc")
    if threshold is None:
        # Unset threshold raises no MOC-specific escalation (Register C3, accepted risk).
        return False
    magnitude = recommendation.get("change_magnitude")
    if magnitude is None:
        return False
    return magnitude > threshold


def rbi_method_disabled(recommendation: Dict[str, Any], bu_profile: Dict[str, Any]) -> bool:
    return recommendation.get("analysis_method") == "RBI" and not bu_profile.get(
        "rbi_by_jurisdiction_enabled", False
    )


def analysis_method_not_enabled(recommendation: Dict[str, Any], bu_profile: Dict[str, Any]) -> bool:
    method = recommendation.get("analysis_method")
    if method is None:
        return False
    return method not in bu_profile.get("enabled_analysis_methods", [])


def rtf_barred_for_criticality(recommendation: Dict[str, Any], criticality: Dict[str, Any]) -> bool:
    # Hard bar independent of the mandatory-PM flag.
    return recommendation.get("strategy_type") == "RTF" and criticality.get("code") in _CRITICAL_CODES


def reevaluation_cadence_exceeds_ceiling(bu_profile: Dict[str, Any]) -> bool:
    cadence = bu_profile.get("reevaluation_cadence", {})
    days = cadence.get("days")
    max_days = cadence.get("max_days")
    if days is None or max_days is None:
        return False
    return days > max_days


def strategy_past_reevaluation_cadence(
    recommendation: Dict[str, Any], bu_profile: Dict[str, Any]
) -> bool:
    cadence = bu_profile.get("reevaluation_cadence", {})
    days = cadence.get("days")
    if days is None:
        return False
    age = recommendation.get("strategy_review_age_days")
    if age is None:
        return False
    return age > days


def beyond_draft_action(requested_action: str) -> bool:
    return requested_action in _BEYOND_DRAFT_ACTIONS


def practicality_incomplete(readiness: Dict[str, Any], requested_action: str) -> bool:
    if not beyond_draft_action(requested_action):
        return False
    return readiness.get("practicality_status") != "COMPLETE"


def peer_review_incomplete(approval_state: Dict[str, Any], requested_action: str) -> bool:
    if not beyond_draft_action(requested_action):
        return False
    return approval_state.get("peer_review_complete") is False


# ---------------------------------------------------------------------------
# Approver resolution
# ---------------------------------------------------------------------------

def required_approvers_for(
    criticality: Dict[str, Any], recommendation: Dict[str, Any], approval: Dict[str, Any]
) -> List[str]:
    """Attach approver roles by criticality and change type (08 Required Approver Logic)."""
    approvers: List[str] = ["Planner", "Reliability Engineer"]
    if (
        recommendation.get("type")
        in _SCORECARD_TYPES | {"TASK_LIST_CLEANUP", "ADD_COMPONENT"}
        or recommendation_reduces_pm_coverage(recommendation)
    ):
        approvers.append("Work Strategy Owner")
    code = criticality.get("code")
    if code == "3":
        approvers.append("Maintenance Manager")
    if code == "4":
        approvers.extend(["Maintenance Manager", "Compliance/Safety"])
    if recommendation.get("type") == "SAP_OBJECT_CHANGE" or recommendation.get(
        "affects_sap_master_data"
    ):
        approvers.append("Master Data Coordinator / SAP PM Owner")
    # Dedupe preserving order.
    seen: set = set()
    ordered: List[str] = []
    for role in approvers:
        if role not in seen:
            seen.add(role)
            ordered.append(role)
    return ordered


# ---------------------------------------------------------------------------
# Result builders (map gate_status -> standard envelope)
# ---------------------------------------------------------------------------

def _gate_envelope(
    gate_status: str,
    summary: str,
    *,
    blocked_reason: Optional[str] = None,
    review_trigger: Optional[str] = None,
    required_approvers: Optional[List[str]] = None,
    allowed_next_actions: Optional[List[str]] = None,
    blocked_actions: Optional[List[str]] = None,
    scope_validated: bool = True,
    run_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    envelope_status = {
        GATE_BLOCKED: STATUS_BLOCKED,
        GATE_DRAFT_ONLY: STATUS_WARNING,
        GATE_REVIEW_REQUIRED: STATUS_WARNING,
        GATE_PASS: STATUS_SUCCESS,
    }[gate_status]
    data = {
        "gate_status": gate_status,
        "required_approvers": required_approvers or [],
        "allowed_next_actions": allowed_next_actions or [],
        "blocked_actions": blocked_actions or [],
        "review_trigger": review_trigger,
        "run_context": run_context or {},
        "gates": [
            {
                "name": review_trigger or blocked_reason or gate_status,
                "status": gate_status,
                "reason": summary,
            }
        ],
    }
    return tool_envelope(
        tool="oxy_gate_check",
        status=envelope_status,
        summary=summary,
        data=data,
        confidence="high",
        scope_validated=scope_validated,
        blocked_reason=blocked_reason,
    )


def oxy_gate_check(
    context: Dict[str, Any],
    scope: Optional[Dict[str, Any]],
    bu_profile: Dict[str, Any],
    criticality: Dict[str, Any],
    pm_governance: Dict[str, Any],
    recommendation: Dict[str, Any],
    readiness: Dict[str, Any],
    risk: Dict[str, Any],
    approval: Dict[str, Any],
    approval_state: Dict[str, Any],
    requested_action: str,
) -> Dict[str, Any]:
    """Deterministic Oxy business-rule gate. See 08 for the truth table and pseudocode.

    ``context`` is retained for run identity (equipment / plant / bu_profile_id / time
    window) in the envelope and Tool Trace; the scope decision comes from ``scope``.
    """
    context = context or {}
    run_context = {
        "equipment_id": context.get("equipment_id"),
        "plant": context.get("plant"),
        "bu_profile_id": context.get("bu_profile_id"),
        "time_window": context.get("time_window"),
    }

    def blocked(reason: str, scope_ok: bool = True) -> Dict[str, Any]:
        return _gate_envelope(
            GATE_BLOCKED,
            f"Blocked: {reason}.",
            blocked_reason=reason,
            required_approvers=required_approvers_for(criticality, recommendation, approval),
            allowed_next_actions=["Remediate the blocker", "Keep current PM"],
            blocked_actions=[requested_action],
            scope_validated=scope_ok,
            run_context=run_context,
        )

    def draft_only(reason: str) -> Dict[str, Any]:
        return _gate_envelope(
            GATE_DRAFT_ONLY,
            f"Draft only: {reason}.",
            blocked_reason=reason,
            required_approvers=required_approvers_for(criticality, recommendation, approval),
            allowed_next_actions=["Save draft artifact"],
            blocked_actions=["Submit for approval", "Master data submit"],
            run_context=run_context,
        )

    def review_required(trigger: str) -> Dict[str, Any]:
        return _gate_envelope(
            GATE_REVIEW_REQUIRED,
            f"Review required: {trigger}.",
            review_trigger=trigger,
            required_approvers=required_approvers_for(criticality, recommendation, approval),
            allowed_next_actions=["Route to human review"],
            blocked_actions=["Auto-approve", "Direct SAP update"],
            run_context=run_context,
        )

    def pass_gate() -> Dict[str, Any]:
        return _gate_envelope(
            GATE_PASS,
            "Recommendation has enough evidence, data readiness, risk support, and readiness.",
            required_approvers=required_approvers_for(criticality, recommendation, approval),
            allowed_next_actions=["Move draft package to review workflow"],
            blocked_actions=["Direct SAP update"],
            run_context=run_context,
        )

    # --- Scope is checked FIRST, fail-closed (08 pseudocode). ---
    scope = scope or {}
    if not scope.get("scope_validated"):
        return blocked(scope.get("blocked_reason") or "NO_VALIDATED_SCOPE", scope_ok=False)
    if scope.get("in_scope") is False:
        return blocked(scope.get("blocked_reason") or "OUT_OF_ANALYSIS_SCOPE", scope_ok=True)

    reduces_coverage = recommendation_reduces_pm_coverage(recommendation)
    changes_strategy = recommendation_changes_strategy(recommendation)
    criticality_unvalidated = criticality_not_validated(criticality)
    criticality_mandate = resolve_pm_requirement(
        criticality.get("code"),
        bu_profile.get("criticality_pm_requirement_overrides", {}),
    )
    is_mandatory_pm = mandatory_pm(pm_governance, criticality_mandate)
    cbm_missing = cbm_readings_missing(recommendation, readiness)
    object_dependency_missing = abc4_object_dependency_missing(criticality, readiness, bu_profile)
    level_loading_deferred = level_loading_required_but_deferred(bu_profile, readiness, requested_action)
    disabled_strategy = strategy_type_disabled(recommendation, bu_profile)
    acceptance_missing_follow_on = acceptance_criterion_rejected_without_follow_on(readiness)
    moc_required = moc_threshold_exceeded(recommendation, bu_profile)
    rbi_disabled = rbi_method_disabled(recommendation, bu_profile)
    method_not_enabled = analysis_method_not_enabled(recommendation, bu_profile)
    rtf_barred = rtf_barred_for_criticality(recommendation, criticality)
    cadence_exceeds_ceiling = reevaluation_cadence_exceeds_ceiling(bu_profile)
    practicality_not_confirmed = practicality_incomplete(readiness, requested_action)
    peer_review_not_confirmed = peer_review_incomplete(approval_state, requested_action)
    past_reevaluation_cadence = strategy_past_reevaluation_cadence(recommendation, bu_profile)
    requires_scorecard = risk_scorecard_required(criticality, recommendation)
    approval_path_requested = requested_action in _APPROVAL_PATH_ACTIONS

    if requested_action == "DIRECT_SAP_UPDATE":
        return blocked("DIRECT_SAP_UPDATE_OUT_OF_SCOPE")

    if rtf_barred:
        return blocked("RTF_BARRED_FOR_CRITICAL_2_3_4")

    if disabled_strategy:
        return blocked("STRATEGY_TYPE_DISABLED_BY_BU_PROFILE")

    if rbi_disabled:
        return blocked("RBI_DISABLED_BY_BU_PROFILE")

    if method_not_enabled:
        return blocked("ANALYSIS_METHOD_NOT_ENABLED")

    if is_mandatory_pm and reduces_coverage:
        return blocked("MANDATORY_PM_CANNOT_REDUCE_COVERAGE")

    if cbm_missing:
        if readiness.get("cbm_synthetic_data_flag") and requested_action == "DRAFT_PACKAGE":
            return draft_only("CBM_SYNTHETIC_DEMO_ONLY")
        return blocked("CBM_REQUIRES_REAL_MEASUREMENT_READINGS")

    if object_dependency_missing:
        return blocked("ABC4_OBJECT_DEPENDENCY_REQUIRED")

    if level_loading_deferred:
        return draft_only("LEVEL_LOADING_DEFERRED_WAVE_1")

    if practicality_not_confirmed:
        return draft_only("PRACTICALITY_NOT_CONFIRMED")

    if peer_review_not_confirmed:
        return draft_only("PEER_REVIEW_NOT_CONFIRMED")

    if requires_scorecard:
        if not risk.get("risk_scorecard_available"):
            return blocked("RISK_SCORECARD_REQUIRED")
        if risk.get("risk_result") == "BLOCK" or risk.get("risk_threshold_met") is False:
            return blocked("RISK_THRESHOLD_NOT_MET")
        if risk.get("risk_result") == "PASS" and risk.get("risk_threshold_met") is not True:
            return blocked("RISK_THRESHOLD_NOT_CONFIRMED")
        if risk.get("risk_result") not in {"PASS", "REVIEW"}:
            return blocked("RISK_RESULT_REQUIRED")

    if recommendation_requires_strong_data(recommendation) and readiness.get("data_readiness") == "RED":
        return blocked("DATA_READINESS_RED")

    if recommendation_requires_strong_data(recommendation) and readiness.get("evidence_sufficiency") == "WEAK":
        return blocked("EVIDENCE_WEAK")

    if criticality.get("code") == "4" and reduces_coverage:
        # Defense-in-depth: under the default profile criticality 4 already resolves to
        # MANDATORY (blocked above); this holds the HSE bar even if a BU profile mis-set
        # criticality 4 to non-mandatory.
        if not approval.get("compliance_safety_named"):
            return blocked("HSE_CRITICAL_REQUIRES_COMPLIANCE_REVIEW")

    if execution_dependency_blocked(readiness):
        return blocked("EXECUTION_READINESS_BLOCKED")

    if approval_path_requested and recommendation_requires_approval_path(recommendation):
        if not approval.get("work_strategy_owner_named"):
            return draft_only("WORK_STRATEGY_OWNER_REQUIRED")
        if approval.get("sap_pm_owner_required") and not approval.get("sap_pm_owner_named"):
            return draft_only("SAP_PM_OWNER_REQUIRED")

    if recommendation.get("type") == "DATA_CLEANUP":
        return draft_only("DATA_CLEANUP_ONLY")

    if acceptance_missing_follow_on:
        return review_required("ACCEPTANCE_CRITERION_REJECTED_NO_FOLLOW_ON")

    if moc_required:
        return review_required("MOC_THRESHOLD_EXCEEDED")

    if past_reevaluation_cadence:
        return review_required("STRATEGY_PAST_REEVALUATION_CADENCE")

    if cadence_exceeds_ceiling:
        return review_required("REEVALUATION_CADENCE_EXCEEDS_CEILING")

    if criticality_unvalidated and changes_strategy:
        return review_required("CRITICALITY_NOT_VALIDATED")

    if requires_scorecard and risk.get("risk_result") == "REVIEW":
        return review_required("RISK_REVIEW_REQUIRED")

    if criticality.get("code") in _CRITICAL_CODES or changes_strategy:
        return review_required("CRITICALITY_OR_STRATEGY_CHANGE")

    if readiness.get("data_readiness") == "YELLOW":
        return review_required("DATA_READINESS_YELLOW")

    return pass_gate()


# ---------------------------------------------------------------------------
# approval_workflow_state
# ---------------------------------------------------------------------------

# States MAX can drive. MASTER_DATA_SUBMITTED is the last MAX-produced state.
STATE_DRAFT = "DRAFT"
STATE_ANALYST_REVIEWED = "ANALYST_REVIEWED"
STATE_SME_REVIEWED = "SME_REVIEWED"
STATE_CHANGES_REQUESTED = "CHANGES_REQUESTED"
STATE_REJECTED = "REJECTED"
STATE_WSO_APPROVED = "WSO_APPROVED"
STATE_MASTER_DATA_SUBMITTED = "MASTER_DATA_SUBMITTED"
# Post-submission states are status-only reflections (manually updated / imported), never a
# MAX write-back (see 10, and 40 SAP Write-Back and HITL Rules).
STATE_IMPLEMENTED = "IMPLEMENTED"
STATE_MONITORED = "MONITORED"
STATE_CLOSED = "CLOSED"
STATUS_ONLY_STATES = {STATE_IMPLEMENTED, STATE_MONITORED, STATE_CLOSED}

# (from_state, to_state) -> {roles, beyond_draft, independent_review}
_TRANSITIONS: Dict[tuple, Dict[str, Any]] = {
    (STATE_DRAFT, STATE_ANALYST_REVIEWED): {
        "roles": {"planner_scheduler", "work_management_engineer"},
    },
    (STATE_ANALYST_REVIEWED, STATE_SME_REVIEWED): {
        "roles": {"equipment_sme", "work_management_engineer"},
    },
    (STATE_SME_REVIEWED, STATE_WSO_APPROVED): {
        "roles": {"work_strategy_owner"},
        "independent_review": True,
    },
    (STATE_WSO_APPROVED, STATE_MASTER_DATA_SUBMITTED): {
        "roles": {"mdc_bpdo"},
        "beyond_draft": True,
    },
    # A first-line reviewer may bounce a DRAFT package (request changes / reject) before it advances,
    # so the Studio Request-changes / Reject buttons are real transitions, not silent denials.
    (STATE_DRAFT, STATE_CHANGES_REQUESTED): {"roles": {"planner_scheduler", "work_management_engineer"}},
    (STATE_DRAFT, STATE_REJECTED): {"roles": {"planner_scheduler", "work_management_engineer"}},
    (STATE_ANALYST_REVIEWED, STATE_CHANGES_REQUESTED): {"roles": {"planner_scheduler", "work_management_engineer"}},
    (STATE_SME_REVIEWED, STATE_CHANGES_REQUESTED): {"roles": {"equipment_sme", "work_management_engineer"}},
    (STATE_ANALYST_REVIEWED, STATE_REJECTED): {"roles": {"planner_scheduler", "work_management_engineer"}},
    (STATE_SME_REVIEWED, STATE_REJECTED): {"roles": {"work_strategy_owner", "equipment_sme"}},
}


def _next_transitions(current_state: str, gate_status: str) -> List[str]:
    """Structural next states (before auth). Nothing is offered when the gate is BLOCKED."""
    if gate_status == GATE_BLOCKED:
        return []
    nexts = []
    for (frm, to), meta in _TRANSITIONS.items():
        if frm != current_state:
            continue
        # Beyond-draft moves are not offered while the gate is DRAFT_ONLY.
        if meta.get("beyond_draft") and gate_status == GATE_DRAFT_ONLY:
            continue
        nexts.append(to)
    return nexts


def approval_workflow_state(
    package_id: str,
    current_state: str,
    requested_transition: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    gate_status: str = GATE_PASS,
    readiness: Optional[Dict[str, Any]] = None,
    approval_state: Optional[Dict[str, Any]] = None,
    creator_user_id: Optional[str] = None,
    independent_review_required: bool = True,
    event_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Track HITL workflow state, reviewer action, and next allowed transition. No SAP write.

    Authorization uses verified role membership from the actor (resolved from Databricks auth
    upstream, not self-typed). Self-approval is rejected where independent review is required.
    Post-submission states are status-only reflections, never a MAX write.
    """
    actor = actor or {}
    readiness = readiness or {}
    approval_state = approval_state or {}
    actor_roles = set(actor.get("roles", []) or [])
    actor_user_id = actor.get("user_id")

    next_allowed = _next_transitions(current_state, gate_status)

    def _result(
        summary: str,
        *,
        status: str,
        transition_allowed: bool,
        role_verified: bool,
        blocked_transition_reason: Optional[str],
        to_state: Optional[str],
        is_status_only: bool = False,
        required_roles: Optional[set] = None,
    ) -> Dict[str, Any]:
        new_state = to_state if transition_allowed else current_state
        data = {
            "current_state": new_state,
            "from_state": current_state,
            "requested_transition": requested_transition,
            "transition_allowed": transition_allowed,
            "next_allowed_transitions": _next_transitions(new_state, gate_status),
            "required_roles": sorted(required_roles) if required_roles else [],
            "role_verified": role_verified,
            "blocked_transition_reason": blocked_transition_reason,
            "is_status_only": is_status_only,
            "max_writes_sap": False,  # invariant: MAX never writes SAP
            "audit": {
                "actor_user_id": actor_user_id,
                "package_id": package_id,
                "from_state": current_state,
                "to_state": new_state,
                "decision": requested_transition,
                "gate_status": gate_status,
                "event_timestamp": event_timestamp,
            },
        }
        return tool_envelope(
            tool="approval_workflow_state",
            status=status,
            summary=summary,
            data=data,
            params_used={"package_id": package_id, "requested_transition": requested_transition},
            confidence="high",
            scope_validated=True,
            blocked_reason=blocked_transition_reason,
        )

    # Report-only call.
    if requested_transition is None:
        return _result(
            f"Package {package_id} is in state {current_state}.",
            status=STATUS_SUCCESS,
            transition_allowed=False,
            role_verified=False,
            blocked_transition_reason=None,
            to_state=None,
        )

    # Post-submission states are status-only reflections, never a MAX write.
    if requested_transition in STATUS_ONLY_STATES or current_state in STATUS_ONLY_STATES:
        return _result(
            f"{requested_transition} is a status-only reflection; MAX records status, it does not write SAP.",
            status=STATUS_WARNING,
            transition_allowed=True,
            role_verified=False,
            blocked_transition_reason=None,
            to_state=requested_transition,
            is_status_only=True,
        )

    transition = (current_state, requested_transition)
    meta = _TRANSITIONS.get(transition)
    if meta is None:
        return _result(
            f"Transition {current_state} -> {requested_transition} is not a valid workflow move.",
            status=STATUS_BLOCKED,
            transition_allowed=False,
            role_verified=False,
            blocked_transition_reason="INVALID_TRANSITION",
            to_state=None,
        )

    required_roles = meta["roles"]

    # Gate gates the workflow: nothing moves while BLOCKED; beyond-draft needs a non-DRAFT_ONLY gate.
    if gate_status == GATE_BLOCKED:
        return _result(
            "Gate is BLOCKED; no transition is offered.",
            status=STATUS_BLOCKED,
            transition_allowed=False,
            role_verified=False,
            blocked_transition_reason="GATE_BLOCKED",
            to_state=None,
            required_roles=required_roles,
        )
    if meta.get("beyond_draft") and gate_status == GATE_DRAFT_ONLY:
        return _result(
            "Gate is DRAFT_ONLY; a master-data submission cannot proceed.",
            status=STATUS_WARNING,
            transition_allowed=False,
            role_verified=False,
            blocked_transition_reason="GATE_DRAFT_ONLY",
            to_state=None,
            required_roles=required_roles,
        )

    # Beyond-draft preconditions: practicality COMPLETE, peer review complete, level loading not deferred.
    if requested_transition == STATE_MASTER_DATA_SUBMITTED:
        if readiness.get("practicality_status") != "COMPLETE":
            return _result(
                "Master-data submit requires practicality COMPLETE.",
                status=STATUS_WARNING,
                transition_allowed=False,
                role_verified=False,
                blocked_transition_reason="PRACTICALITY_INCOMPLETE",
                to_state=None,
                required_roles=required_roles,
            )
        if approval_state.get("peer_review_complete") is False:
            return _result(
                "Master-data submit requires peer review complete.",
                status=STATUS_WARNING,
                transition_allowed=False,
                role_verified=False,
                blocked_transition_reason="PEER_REVIEW_INCOMPLETE",
                to_state=None,
                required_roles=required_roles,
            )
        if readiness.get("level_loading_status") not in {"COMPLETE", "ATTESTED"}:
            return _result(
                "Master-data submit requires level loading not to be a deferred blocker.",
                status=STATUS_WARNING,
                transition_allowed=False,
                role_verified=False,
                blocked_transition_reason="LEVEL_LOADING_DEFERRED",
                to_state=None,
                required_roles=required_roles,
            )

    # Self-approval: the creator cannot approve their own recommendation where independent review is required.
    if meta.get("independent_review") and independent_review_required and actor_user_id is not None and actor_user_id == creator_user_id:
        return _result(
            "Self-approval is not allowed where independent review is required.",
            status=STATUS_BLOCKED,
            transition_allowed=False,
            role_verified=bool(required_roles & actor_roles),
            blocked_transition_reason="SELF_APPROVAL_NOT_ALLOWED",
            to_state=None,
            required_roles=required_roles,
        )

    # Authorization: verified role membership (not self-typed).
    role_verified = bool(required_roles & actor_roles)
    if not role_verified:
        return _result(
            "Actor does not hold a verified role for this transition.",
            status=STATUS_BLOCKED,
            transition_allowed=False,
            role_verified=False,
            blocked_transition_reason="ROLE_NOT_VERIFIED",
            to_state=None,
            required_roles=required_roles,
        )

    return _result(
        f"Transition {current_state} -> {requested_transition} allowed.",
        status=STATUS_SUCCESS,
        transition_allowed=True,
        role_verified=True,
        blocked_transition_reason=None,
        to_state=requested_transition,
        required_roles=required_roles,
    )
