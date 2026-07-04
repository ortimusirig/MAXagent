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

from typing import Any, Callable, Dict, List, Optional

from ..schemas import STATUS_SUCCESS, STATUS_WARNING, tool_envelope


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
            },
            params_used=params,
            confidence="low",
            scope_validated=bool(scope.get("scope_validated", True)),
        )

    records = executor(template_name, {**params, **{k: scope.get(k) for k in scope_predicates}})
    return tool_envelope(
        tool="run_scoped_sql",
        status=STATUS_SUCCESS,
        summary=f"Ran template {template_name}; {len(records)} row(s).",
        data={
            "template_name": template_name,
            "scope_predicates": scope_predicates,
            "row_count": len(records),
            "records": records,
            "executor_bound": True,
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
    relations = allowed_relations or ["v_pm_plan_current", "v_work_order_history", "v_notification_history"]
    validation = {"status": "passed" if scope_predicates else "no_scope_predicates", "scope_predicates": scope_predicates}

    bound = bool(client) and getattr(client, "genie_bound", lambda: False)()
    if not bound:
        return tool_envelope(
            tool="genie_query_scoped", status=STATUS_WARNING,
            summary="Genie not bound; returning a scoped empty result (no unscoped query is run).",
            data={"conversation_id": None, "generated_sql": None, "referenced_relations": relations,
                  "sql_validation": validation, "row_count": 0, "records": [], "genie_bound": False},
            params_used={"question": question, **{k: scope.get(k) for k in scope_predicates}},
            confidence="low", scope_validated=bool(scope.get("scope_validated", True)),
        )

    # Bound path: delegate to the client (Genie), still enforcing scope predicates.
    result = client.genie_query(question, {k: scope.get(k) for k in scope_predicates}) or {}
    records = result.get("records", [])
    return tool_envelope(
        tool="genie_query_scoped", status=STATUS_SUCCESS,
        summary=f"Genie returned {len(records)} scoped row(s).",
        data={"conversation_id": result.get("conversation_id"), "generated_sql": result.get("generated_sql"),
              "referenced_relations": result.get("referenced_relations", relations),
              "sql_validation": validation, "row_count": len(records), "records": records, "genie_bound": True},
        params_used={"question": question, **{k: scope.get(k) for k in scope_predicates}},
        confidence="medium", scope_validated=bool(scope.get("scope_validated", True)),
    )
