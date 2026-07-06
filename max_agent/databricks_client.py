"""Databricks integration seam - thin, lazy, and optional.

The MAX Agent app runs with NO Databricks connection (local synthetic mode) and lights up the
real integrations automatically once a workspace, SQL warehouse, Genie space, and LLM serving
endpoint are bound via app.yaml / Databricks App resources. Nothing here hardcodes a token; all
config comes from environment variables set by the Databricks App runtime, and the app service
principal provides auth.

Design rules (from 04 / 06):
- Databricks SDK / SQL connector are imported LAZILY so the app imports and runs without them.
- If a resource is not bound, the method returns None and the caller falls back to synthetic/local
  behavior. No exception is raised for a missing binding.
- The LLM only narrates deterministic results; it never decides a gate or a label.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional


class MaxDatabricksClient:
    """Resolves Databricks resources from the environment; degrades to local synthetic mode."""

    def __init__(self) -> None:
        self.host = os.environ.get("DATABRICKS_HOST")
        self.warehouse_id = os.environ.get("SQL_WAREHOUSE_ID") or os.environ.get("DATABRICKS_WAREHOUSE_ID")
        self.genie_space_id = os.environ.get("GENIE_SPACE_ID")
        self.llm_endpoint = os.environ.get("LLM_AGENT_ENDPOINT") or os.environ.get("LLM_SUMMARY_ENDPOINT")
        self.catalog = os.environ.get("MAX_CATALOG")
        self.schema = os.environ.get("MAX_SCHEMA")

    # --- capability probes -------------------------------------------------
    def _sdk_available(self) -> bool:
        try:
            import databricks.sdk  # noqa: F401
            return True
        except Exception:
            return False

    def _workspace_reachable(self) -> bool:
        # Inside a Databricks App the WorkspaceClient auto-authenticates via the app service principal
        # (no DATABRICKS_HOST needed); locally the SDK is absent, so this is False and we stay synthetic.
        return self._sdk_available() and (bool(self.host) or bool(os.environ.get("DATABRICKS_APP_PORT")))

    def sql_bound(self) -> bool:
        return bool(self.warehouse_id and self._workspace_reachable())

    def genie_bound(self) -> bool:
        return bool(self.genie_space_id and self._workspace_reachable())

    def llm_bound(self) -> bool:
        return bool(self.llm_endpoint and self._workspace_reachable())

    def mode(self) -> str:
        return "databricks" if (self.sql_bound() or self.llm_bound()) else "local_synthetic"

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode(),
            "sql_bound": self.sql_bound(),
            "genie_bound": self.genie_bound(),
            "llm_bound": self.llm_bound(),
            "host": self.host,
            "warehouse_id": self.warehouse_id,
            "genie_space_id": self.genie_space_id,
            "llm_endpoint": self.llm_endpoint,
        }

    # --- SQL ---------------------------------------------------------------
    def sql_executor(self) -> Optional[Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]]:
        """Return a `(template_name, params) -> rows` callable, or None if SQL is not bound.

        When None, `run_scoped_sql` returns an empty scoped result and the orchestrator uses the
        local synthetic executor instead.
        """
        if not self.sql_bound():
            return None

        from databricks.sdk import WorkspaceClient  # lazy
        from databricks.sdk.service.sql import StatementParameterListItem  # lazy
        from .sql_templates import sql_execution_plan

        ws = WorkspaceClient()

        def _execute(template_name: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
            # Scope predicates are BOUND server-side (named parameters), never interpolated into the SQL
            # text - the warehouse enforces the scope filter and there is no injection surface. row_cap is
            # inlined as a trusted integer by sql_execution_plan.
            statement, named = sql_execution_plan(template_name, params, catalog=self.catalog, schema=self.schema)
            parameters = [StatementParameterListItem(name=p["name"], value=p["value"]) for p in named]
            resp = ws.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id, statement=statement,
                parameters=parameters or None, wait_timeout="30s",
            )
            result = getattr(resp, "result", None)
            data = getattr(result, "data_array", None) or []
            cols = [c.name for c in (getattr(getattr(resp, "manifest", None), "schema", None).columns or [])] if getattr(resp, "manifest", None) else []
            return [dict(zip(cols, row)) for row in data]

        return _execute

    # --- Genie (optional, scoped) -----------------------------------------
    def genie_query(self, question: str, scoped_params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Run a scoped Genie conversation, or None if Genie is not bound.

        `scoped_params` are the locked scope predicates that `genie_query_scoped` enforces. This
        never runs unscoped: the caller has already validated scope, and the question is answered
        within that scope.
        """
        if not self.genie_bound():
            return None
        try:
            from databricks.sdk import WorkspaceClient  # lazy
            ws = WorkspaceClient()
            scope_text = "; ".join(f"{k}={v}" for k, v in scoped_params.items() if v)
            conv = ws.genie.start_conversation_and_wait(
                self.genie_space_id, f"{question}\nScope (required): {scope_text}"
            )
            attachments = getattr(conv, "attachments", None) or []
            generated_sql, records, relations = None, [], []
            for att in attachments:
                q = getattr(att, "query", None)
                if q is not None:
                    generated_sql = getattr(q, "query", None)
            return {
                "conversation_id": getattr(conv, "conversation_id", None),
                "generated_sql": generated_sql, "records": records, "referenced_relations": relations,
            }
        except Exception:
            return None

    # --- LLM narration (optional) -----------------------------------------
    def llm_complete(self, prompt: str, system: Optional[str] = None, max_tokens: int = 1500) -> Optional[str]:
        """Narrate a deterministic result via the serving endpoint, or None if not bound.

        max_tokens defaults to 1500 so the full governed narration (Overview + evidence + reliability + BOM
        + recommendation) is never truncated mid-sentence; short calls (intent / entity extraction) stop
        early regardless. The WorkspaceClient is cached on the instance - constructing it per call re-runs
        auth discovery and adds real latency to every LLM turn (several per Ask)."""
        if not self.llm_bound():
            return None
        try:
            from databricks.sdk import WorkspaceClient  # lazy
            from databricks.sdk.service.serving import ChatMessage, ChatMessageRole  # lazy
            if getattr(self, "_ws", None) is None:
                self._ws = WorkspaceClient()
            ws = self._ws
            messages = []
            if system:
                messages.append(ChatMessage(role=ChatMessageRole.SYSTEM, content=system))
            messages.append(ChatMessage(role=ChatMessageRole.USER, content=prompt))
            resp = ws.serving_endpoints.query(name=self.llm_endpoint, messages=messages, max_tokens=max_tokens)
            choices = getattr(resp, "choices", None) or []
            if choices:
                msg = getattr(choices[0], "message", None)
                return getattr(msg, "content", None)
        except Exception:
            return None
        return None
