"""Data-retrieval tools.

Only ``run_scoped_sql`` is stubbed here, and deliberately thin: the deterministic core is
Databricks-free (02, "Development Rule"). In production this wraps a Databricks SQL
warehouse and runs parameterized templates from ``sql_templates.py``; the Databricks client
is injected so nothing in ``max_agent.tools`` imports the SDK.

``genie_query_scoped`` (the LLM/Genie path) injects the locked scope, records the generated SQL /
referenced relations / row count / a deterministic scope-validation result, and never runs
unscoped (07). Genie itself is optional: without a bound Genie space it returns a scoped, empty
result rather than an unscoped query.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..schemas import STATUS_SUCCESS, STATUS_WARNING, tool_envelope
from .sql_guard import validate_generated_sql

_LOG = logging.getLogger(__name__)


def _row_cap_from(values: Optional[Dict[str, Any]]) -> Optional[int]:
    raw = (values or {}).get("row_cap")
    try:
        cap = int(raw)
    except (TypeError, ValueError):
        return None
    return cap if cap > 0 else None


def _enforce_row_cap(
    records: Optional[List[Dict[str, Any]]],
    row_cap: Optional[int],
    *,
    tool: str,
    subject: str,
) -> Tuple[List[Dict[str, Any]], int]:
    rows = list(records or [])
    if row_cap is None or len(rows) <= row_cap:
        return rows, 0
    dropped = len(rows) - row_cap
    _LOG.warning("%s truncated %s to row_cap=%s; dropped_rows=%s", tool, subject, row_cap, dropped)
    return rows[:row_cap], dropped


def run_scoped_sql(
    template_name: str,
    scope: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
    executor: Optional[Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Run a parameterized SQL template within a locked scope.

    ``executor`` is a callable ``(template_name, params) -> list[rows]`` injected by the
    app (Databricks SQL) or by a test (in-memory synthetic backend). When no executor is
    provided the tool returns a warning envelope instead of touching any live system - the
    deterministic core must never require a warehouse to run or to be tested.

    Scope predicates are always echoed so Evidence / Tool Trace can prove the query was
    scoped (Genie / SQL must never run unscoped, per 07).
    """
    params = params or {}
    row_cap = _row_cap_from(params)
    scope_predicates = [
        key
        for key in ("equipment_id", "functional_location_id", "plant", "time_window")
        if scope.get(key)
    ]

    if executor is None:
        return tool_envelope(
            tool="run_scoped_sql",
            status=STATUS_WARNING,
            summary=(
                "No SQL executor bound (deterministic core is Databricks-free); "
                "returning an empty, scoped result."
            ),
            data={
                "template_name": template_name,
                "scope_predicates": scope_predicates,
                "row_count": 0,
                "records": [],
                "executor_bound": False,
                "row_cap": row_cap,
                "row_cap_truncated": False,
                "dropped_row_count": 0,
            },
            params_used=params,
            confidence="low",
            scope_validated=bool(scope.get("scope_validated", True)),
        )

    records = executor(template_name, {**params, **{k: scope.get(k) for k in scope_predicates}})
    records, dropped = _enforce_row_cap(records, row_cap, tool="run_scoped_sql", subject=template_name)
    summary = f"Ran template {template_name}; {len(records)} row(s)."
    if dropped:
        summary += f" Truncated to row cap {row_cap}; dropped {dropped} row(s)."
    return tool_envelope(
        tool="run_scoped_sql",
        status=STATUS_SUCCESS,
        summary=summary,
        data={
            "template_name": template_name,
            "scope_predicates": scope_predicates,
            "row_count": len(records),
            "records": records,
            "executor_bound": True,
            "row_cap": row_cap,
            "row_cap_truncated": bool(dropped),
            "dropped_row_count": dropped,
        },
        params_used=params,
        confidence="medium",
        scope_validated=bool(scope.get("scope_validated", True)),
    )


def genie_query_scoped(
    question: str,
    scope: Dict[str, Any],
    client: Optional[Any] = None,
    allowed_relations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Conversational retrieval through Genie, with the locked scope injected and validated.

    The scope predicates are always enforced so Genie never runs unscoped. Genie is optional: when
    no Genie space is bound (``client`` is None or not ``genie_bound``), this returns a scoped, empty
    result and marks ``genie_bound = False`` - it does NOT fall back to an unscoped query.
    """
    scope = scope or {}
    scope_predicates = [k for k in ("equipment_id", "functional_location_id", "plant", "time_window") if scope.get(k)]
    row_cap = _row_cap_from(scope)
    relations = allowed_relations or ["v_pm_plan_current", "v_work_order_history", "v_notification_history"]

    # Scope is authoritative and fail-closed (mirrors the governed lane's out-of-scope short-circuit): an
    # out-of-scope (JV / exempt / held) asset NEVER triggers a scoped Genie read, even when a Genie space is
    # bound. Only an EXPLICIT in_scope False fails closed; an absent key is the normal in-scope governed lane.
    if scope.get("in_scope") is False:
        return tool_envelope(
            tool="genie_query_scoped", status=STATUS_WARNING,
            summary="Asset is out of analysis scope; no Genie read is run (scope is authoritative).",
            data={"conversation_id": None, "generated_sql": None, "referenced_relations": relations,
                  "sql_validation": {"status": "NOT_RUN_OUT_OF_SCOPE", "scope_predicates": scope_predicates},
                  "row_count": 0, "records": [], "genie_bound": False,
                  "row_cap": row_cap, "row_cap_truncated": False, "dropped_row_count": 0},
            params_used={"question": question, **{k: scope.get(k) for k in scope_predicates}},
            confidence="low", scope_validated=bool(scope.get("scope_validated", True)),
            blocked_reason="OUT_OF_ANALYSIS_SCOPE",
        )

    bound = bool(client) and getattr(client, "genie_bound", lambda: False)()
    if not bound:
        return tool_envelope(
            tool="genie_query_scoped", status=STATUS_WARNING,
            summary="Genie not bound; returning a scoped empty result (no unscoped query is run).",
            data={"conversation_id": None, "generated_sql": None, "referenced_relations": relations,
                  "sql_validation": {"status": "NOT_RUN_NO_GENIE", "scope_predicates": scope_predicates},
                  "row_count": 0, "records": [], "genie_bound": False,
                  "row_cap": row_cap, "row_cap_truncated": False, "dropped_row_count": 0},
            params_used={"question": question, **{k: scope.get(k) for k in scope_predicates}},
            confidence="low", scope_validated=bool(scope.get("scope_validated", True)),
        )

    # Bound path: delegate to the client (Genie), then GUARD the generated SQL before surfacing rows.
    result = client.genie_query(question, {k: scope.get(k) for k in scope_predicates}) or {}
    generated_sql = result.get("generated_sql")
    validation = validate_generated_sql(generated_sql, relations, scope)

    # Fail closed: a REJECTED query never surfaces rows, regardless of what Genie returned.
    if validation["status"] == "REJECTED":
        return tool_envelope(
            tool="genie_query_scoped", status=STATUS_WARNING,
            summary=f"Genie SQL rejected by safety guard ({', '.join(validation['reasons'])}); no rows surfaced.",
            data={"conversation_id": result.get("conversation_id"), "generated_sql": generated_sql,
                  "referenced_relations": validation["referenced_relations"] or result.get("referenced_relations", relations),
                  "sql_validation": validation, "row_count": 0, "records": [], "genie_bound": True,
                  "row_cap": row_cap, "row_cap_truncated": False, "dropped_row_count": 0},
            params_used={"question": question, **{k: scope.get(k) for k in scope_predicates}},
            confidence="low", scope_validated=bool(scope.get("scope_validated", True)),
            blocked_reason="GENERATED_SQL_FAILED_SAFETY_GUARD",
        )

    records = result.get("records", []) if validation["status"] == "PASSED" else []
    records, dropped = _enforce_row_cap(records, row_cap, tool="genie_query_scoped", subject="generated SQL")
    status = STATUS_SUCCESS if validation["status"] == "PASSED" else STATUS_WARNING
    summary = (
        f"Genie returned {len(records)} scoped row(s)." if validation["status"] == "PASSED"
        else f"Genie SQL readable but not fully scoped/allowlisted ({', '.join(validation['reasons'])}); rows withheld."
    )
    if dropped:
        summary += f" Truncated to row cap {row_cap}; dropped {dropped} row(s)."
    return tool_envelope(
        tool="genie_query_scoped", status=status, summary=summary,
        data={"conversation_id": result.get("conversation_id"), "generated_sql": generated_sql,
              "referenced_relations": validation["referenced_relations"] or result.get("referenced_relations", relations),
              "sql_validation": validation, "row_count": len(records), "records": records, "genie_bound": True,
              "row_cap": row_cap, "row_cap_truncated": bool(dropped), "dropped_row_count": dropped},
        params_used={"question": question, **{k: scope.get(k) for k in scope_predicates}},
        confidence="medium" if validation["status"] == "PASSED" else "low",
        scope_validated=bool(scope.get("scope_validated", True)),
    )
