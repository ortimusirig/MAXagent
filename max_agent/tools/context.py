"""Context tools: ``resolve_context`` and ``validate_scope``.

``validate_scope`` is the deterministic scope gate specified in
``70 - MAX Agent Build/10 - Core Deterministic Tool Specs and Unit Tests``. It runs
immediately after ``resolve_context`` and *before* any retrieval, classification, or gate
call, and it emits the ``scope`` object that ``oxy_gate_check`` consumes (08 truth-table
cases 32-35). It never authorizes an action; it gates entry, fail-closed.

Policy vs asset state are kept separate: BU policy (operated_only, exemption policy) comes
from ``bu_profile.scope_applicability``; per-asset ``operated_status`` / ``exemption_status``
/ ``exemption_id`` / criticality / provenance come from the master-data lookup, passed in as
``master_data`` so the tool stays Databricks-free and unit-testable.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..schemas import (
    STATUS_BLOCKED,
    STATUS_SUCCESS,
    STATUS_WARNING,
    tool_envelope,
)

# Scope blocked-reason codes surfaced by oxy_gate_check (08 cases 32-35).
NO_VALIDATED_SCOPE = "NO_VALIDATED_SCOPE"
EMPTY_PM_POPULATION = "EMPTY_PM_POPULATION"
NON_OPERATED_OR_JV_OUT_OF_SCOPE = "NON_OPERATED_OR_JV_OUT_OF_SCOPE"
EXEMPT_ASSET_OUT_OF_SCOPE = "EXEMPT_ASSET_OUT_OF_SCOPE"

# Non-blocking scope flags.
FLAG_OUT_OF_PILOT_SCOPE = "OUT_OF_PILOT_SCOPE"
FLAG_CRITICALITY_UNVALIDATED = "CRITICALITY_UNVALIDATED"
FLAG_CRITICALITY_STALE = "CRITICALITY_STALE"
FLAG_CRITICALITY_FLOC_CONFLICT = "CRITICALITY_FLOC_CONFLICT"
FLAG_PROVENANCE_SYNTHETIC = "PROVENANCE_SYNTHETIC"

PROVENANCE_SYNTHETIC = "SYNTHETIC"
PROVENANCE_GOVERNED = "GOVERNED"


def resolve_context(
    equipment_id: Optional[str] = None,
    functional_location_id: Optional[str] = None,
    plant: Optional[str] = None,
    business_unit: Optional[str] = None,
    bu_profile_id: str = "default_oxy",
    asset_class: Optional[str] = None,
    time_window: str = "LAST_24_MONTHS",
    review_type: Optional[str] = None,
    pm_population: Optional[Any] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Convert free-form intent / filters into a locked run context.

    This is the deterministic side of context resolution (an LLM may pre-fill the fields,
    but the locked context returned here is what every downstream tool reads). It does not
    hit any data source; ``validate_scope`` is what confirms the scope against master data.
    """
    context = {
        "equipment_id": equipment_id,
        "functional_location_id": functional_location_id,
        "plant": plant,
        "business_unit": business_unit,
        "bu_profile_id": bu_profile_id,
        "asset_class": asset_class,
        "time_window": time_window,
        "review_type": review_type,
        "pm_population": pm_population,
    }
    context.update(extra)
    return tool_envelope(
        tool="resolve_context",
        status=STATUS_SUCCESS,
        summary="Locked run context.",
        data={"context": context},
        params_used={"bu_profile_id": bu_profile_id, "time_window": time_window},
        confidence="high",
        scope_validated=True,
    )


def _criticality_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a master-data criticality record to the fields downstream tools read."""
    return {
        "code": raw.get("code"),
        "label": raw.get("label"),
        "validation_status": raw.get("validation_status"),
    }


def validate_scope(
    context: Dict[str, Any],
    bu_profile: Dict[str, Any],
    master_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Confirm the requested scope is real, in-scope, and safe to analyze.

    See 10 for the predicate table. The order matters: an unresolved asset / empty
    population fails closed first (``scope_validated = false``); non-operated / JV / exempt
    assets are held (``in_scope = false``); criticality and provenance are non-blocking
    flags that drive downstream gate review but do not stop scope validation.
    """
    master_data = master_data or {}
    scope_applicability = bu_profile.get("scope_applicability", {}) or {}
    operated_only = bool(scope_applicability.get("operated_only"))

    params_used = {
        "equipment_id": context.get("equipment_id"),
        "functional_location_id": context.get("functional_location_id"),
        "time_window": context.get("time_window"),
    }

    criticality = _criticality_view(master_data.get("criticality", {}) or {})
    provenance = (
        PROVENANCE_SYNTHETIC
        if master_data.get("synthetic_data_flag")
        else PROVENANCE_GOVERNED
    )

    def _blocked(reason: str, summary: str, in_scope: bool) -> Dict[str, Any]:
        data = {
            "scope_validated": reason not in (NO_VALIDATED_SCOPE, EMPTY_PM_POPULATION),
            "in_scope": in_scope,
            "criticality": criticality,
            "pm_population_count": master_data.get("pm_population_count", 0),
            "provenance": provenance,
            "scope_flags": [],
            "blocked_reason": reason,
        }
        # scope_validated is only false for the unresolved / empty-population reasons.
        scope_ok = data["scope_validated"]
        return tool_envelope(
            tool="validate_scope",
            status=STATUS_BLOCKED,
            summary=summary,
            data=data,
            params_used=params_used,
            confidence="high",
            scope_validated=scope_ok,
            blocked_reason=reason,
        )

    # --- Predicate 1: asset_or_population_resolved (fail closed first) ---
    is_population_request = context.get("pm_population") is not None
    if is_population_request:
        count = int(master_data.get("pm_population_count", 0) or 0)
        if count < 1:
            return _blocked(
                EMPTY_PM_POPULATION,
                "PM population resolves to zero assets; scope not validated.",
                in_scope=False,
            )
        pm_population_count = count
    else:
        if not master_data.get("asset_resolved"):
            return _blocked(
                NO_VALIDATED_SCOPE,
                "Requested asset id could not be resolved to a master record; scope not validated.",
                in_scope=False,
            )
        pm_population_count = int(master_data.get("pm_population_count", 1) or 1)

    # --- Predicate 2/3: applicability holds (non-operated / JV / exempt -> in_scope false) ---
    operated_status = str(master_data.get("operated_status", "OPERATED") or "OPERATED").upper()
    if operated_only and operated_status in ("NON_OPERATED", "JV", "NON-OPERATED"):
        return _blocked(
            NON_OPERATED_OR_JV_OUT_OF_SCOPE,
            "Asset is non-operated / JV; out of analysis scope (procedure p.3, E1).",
            in_scope=False,
        )

    exemption_status = master_data.get("exemption_status")
    if exemption_status not in (None, "", "NONE"):
        return _blocked(
            EXEMPT_ASSET_OUT_OF_SCOPE,
            "Asset is exempt; out of analysis scope (60.400.003, E1).",
            in_scope=False,
        )

    # --- Non-blocking flags: pilot class, criticality freshness, provenance ---
    scope_flags = []

    pilot_classes = bu_profile.get("pilot_equipment_classes")  # P4 - may be unset
    asset_class = context.get("asset_class")
    if pilot_classes and asset_class and asset_class not in pilot_classes:
        scope_flags.append(FLAG_OUT_OF_PILOT_SCOPE)

    crit_raw = master_data.get("criticality", {}) or {}
    code = crit_raw.get("code")
    if code in (None, "", "0") or crit_raw.get("validation_status") != "VALIDATED":
        scope_flags.append(FLAG_CRITICALITY_UNVALIDATED)
    if crit_raw.get("stale"):
        scope_flags.append(FLAG_CRITICALITY_STALE)
    if crit_raw.get("equipment_floc_conflict"):
        scope_flags.append(FLAG_CRITICALITY_FLOC_CONFLICT)

    if provenance == PROVENANCE_SYNTHETIC:
        scope_flags.append(FLAG_PROVENANCE_SYNTHETIC)

    status = STATUS_WARNING if scope_flags else STATUS_SUCCESS
    summary = (
        "Scope validated and in scope."
        if not scope_flags
        else "Scope validated and in scope, with flags: " + ", ".join(scope_flags) + "."
    )
    data = {
        "scope_validated": True,
        "in_scope": True,
        "criticality": criticality,
        "pm_population_count": pm_population_count,
        "provenance": provenance,
        "scope_flags": scope_flags,
        "blocked_reason": None,
    }
    return tool_envelope(
        tool="validate_scope",
        status=status,
        summary=summary,
        data=data,
        params_used=params_used,
        confidence="high",
        scope_validated=True,
        blocked_reason=None,
    )
