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

    def sql_bound(self) -> bool:
        return bool(self.host and self.warehouse_id and self._sdk_available())

    def genie_bound(self) -> bool:
        return bool(self.host and self.genie_space_id and self._sdk_available())

    def llm_bound(self) -> bool:
        return bool(self.host and self.llm_endpoint and self._sdk_available())

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
        from .sql_templates import render_sql

        ws = WorkspaceClient()

        def _execute(template_name: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
            statement = render_sql(template_name, params, catalog=self.catalog, schema=self.schema)
            resp = ws.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id, statement=statement, wait_timeout="30s"
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
    def llm_complete(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        """Narrate a deterministic result via the serving endpoint, or None if not bound."""
        if not self.llm_bound():
            return None
        try:
            from databricks.sdk import WorkspaceClient  # lazy
            ws = WorkspaceClient()
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            resp = ws.serving_endpoints.query(name=self.llm_endpoint, messages=messages, max_tokens=400)
            choices = getattr(resp, "choices", None) or []
            if choices:
                msg = getattr(choices[0], "message", None)
                return getattr(msg, "content", None)
        except Exception:
            return None
        return None
