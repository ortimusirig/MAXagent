"""genie_query_scoped - scope is always enforced; unbound Genie fails safe (never runs unscoped).

Per 07 the Genie/SQL path must never run unscoped. When no Genie space is bound the tool returns a
scoped, empty result (genie_bound=False) instead of falling back to an unscoped query. When bound,
it delegates to the client but still passes only the locked scope predicates.
"""

from __future__ import annotations

from max_agent.tools import genie_query_scoped

_SCOPE = {"equipment_id": "PUMP-4110", "time_window": "LAST_24_MONTHS", "scope_validated": True}


class _BoundClient:
    """Fake Genie-bound client; echoes the scoped params it was handed."""

    def __init__(self):
        self.received = None

    def genie_bound(self):
        return True

    def genie_query(self, question, scoped_params):
        self.received = scoped_params
        return {"conversation_id": "conv-1", "generated_sql": "SELECT 1", "records": [{"x": 1}],
                "referenced_relations": ["v_work_order_history"]}


def test_unbound_returns_scoped_empty_not_unscoped():
    env = genie_query_scoped("why so many failures?", _SCOPE, client=None)
    d = env["data"]
    assert d["genie_bound"] is False
    assert d["records"] == []
    assert d["sql_validation"]["status"] == "passed"
    assert "equipment_id" in d["sql_validation"]["scope_predicates"]


def test_scope_predicates_are_recorded_in_params():
    env = genie_query_scoped("why so many failures?", _SCOPE, client=None)
    assert env["params_used"]["equipment_id"] == "PUMP-4110"
    assert env["params_used"]["time_window"] == "LAST_24_MONTHS"


def test_bound_client_receives_only_scope_predicates():
    client = _BoundClient()
    env = genie_query_scoped("why so many failures?", _SCOPE, client=client)
    assert env["data"]["genie_bound"] is True
    assert env["data"]["row_count"] == 1
    # The client only ever sees the locked scope predicates (never scope_validated flag).
    assert set(client.received) == {"equipment_id", "time_window"}


def test_no_scope_predicates_is_flagged():
    env = genie_query_scoped("global question", {"scope_validated": True}, client=None)
    assert env["data"]["sql_validation"]["status"] == "no_scope_predicates"
