"""Generated-SQL safety guard (70/05).

Genie can generate SQL; that SQL must never execute until it passes a deterministic guard. This
module is the guard, and it is pure/Databricks-free so it is unit-testable and always runs (even in
synthetic mode). It enforces four things from 70/05:

1. SELECT-only: reject anything that is not a single read query (no INSERT/UPDATE/DELETE/MERGE/DDL/
   security/maintenance statements, no multiple statements).
2. View allowlist: every relation the SQL reads must be in the curated Genie-space view allowlist.
3. Scope filter present: the locked scope predicate(s) must appear, so Genie never runs unscoped.
4. Structured result: a deterministic validation object the caller records in the Tool Trace.

The guard fails closed: if it cannot prove the SQL is a safe, scoped, allowlisted SELECT, it
REJECTS. Parameter binding (server-side `:name` params) is the separate execution-time protection
in databricks_client; this guard is the pre-execution gate.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Statement keywords that must never appear in Genie-generated SQL (whole-word match; `update_time`
# does NOT match \bUPDATE\b because `_` is a word char).
_BANNED = [
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "REPLACE", "COPY", "GRANT", "REVOKE", "VACUUM", "OPTIMIZE", "RESTORE", "REFRESH", "CALL",
    "EXECUTE", "SET", "USE", "COMMENT",
]
_BANNED_RE = re.compile(r"\b(" + "|".join(_BANNED) + r")\b", re.IGNORECASE)
_RELATION_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)

# scope predicate -> the column name(s) that must appear in the SQL when that predicate is locked.
_SCOPE_COLUMNS = {
    "equipment_id": ("equipment_id",),
    "functional_location_id": ("functional_location_id", "floc_id", "functional_location"),
    "plant": ("plant",),
    "time_window": ("time_window", "posting_date", "created_on", "reading_date", "start_date", "date"),
    "business_unit": ("business_unit", "bu", "bu_id"),
}


def _strip_noise(sql: str) -> str:
    """Remove comments and single-quoted string literals so keyword matching is on code only."""
    s = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)      # /* block */ comments
    s = re.sub(r"--[^\n]*", " ", s)                            # -- line comments
    s = re.sub(r"'(?:[^']|'')*'", "''", s)                     # '...' string literals -> ''
    return s


def _short_relation(name: str) -> str:
    """Reduce catalog.schema.view -> view (leaf), lowercased, for allowlist comparison."""
    return name.split(".")[-1].strip().lower()


def _bound_in_clause(body_low: str, col: str) -> bool:
    """Accept only IN-lists that are fully parameter-bound, e.g. ``col IN (:p1, :p2)``."""
    for match in re.finditer(rf"\b{col}\s+in\s*\(([^)]*)\)", body_low):
        contents = match.group(1).strip()
        if re.fullmatch(r":\w+(?:\s*,\s*:\w+)*", contents):
            return True
    return False


def _scope_bound(body_low: str, cols, value) -> bool:
    """True only if one of `cols` is VALUE-BOUND to the locked scope in the SQL.

    Accepts a server-side bind (`col = :param` / `col op :param`), a fully bound `IN (:param, ...)`,
    or an equality to the actual scope value. It deliberately does NOT accept `col IS [NOT] NULL`,
    a bare column mention, or inlined literals in an IN-list.
    """
    for c in cols:
        c = re.escape(c.lower())
        if re.search(rf"\b{c}\s*(?:>=|<=|=|>|<)\s*:", body_low):  # col op :param  (server-bound)
            return True
        if _bound_in_clause(body_low, c):                          # col IN (:p1, :p2)
            return True
        if value is not None and re.search(rf"\b{c}\s*=\s*'{re.escape(str(value).lower())}'", body_low):
            return True                                            # col = 'the actual scope value'
    return False


def validate_generated_sql(
    sql: Optional[str],
    allowed_relations: List[str],
    scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Deterministically validate Genie-generated SQL. Returns a structured, fail-closed verdict.

    status is one of: PASSED (safe to surface/execute), WARN (readable but scope/allowlist concern),
    REJECTED (must not execute). reasons is a list of distinct reason codes.
    """
    scope = scope or {}
    scope_predicates = [k for k in ("equipment_id", "functional_location_id", "plant", "time_window", "business_unit") if scope.get(k)]
    result: Dict[str, Any] = {
        "select_only": False,
        "single_statement": False,
        "allowlisted": False,
        "scope_filter_present": False,
        "referenced_relations": [],
        "disallowed_relations": [],
        "allowlisted_views": sorted({_short_relation(r) for r in (allowed_relations or [])}),
        "scope_predicates": scope_predicates,
        "status": "REJECTED",
        "reasons": [],
    }
    if not sql or not sql.strip():
        result["reasons"].append("NO_SQL")
        return result

    code = _strip_noise(sql)

    # 1. single statement (ignore one trailing semicolon)
    body = code.strip().rstrip(";")
    statements = [s for s in body.split(";") if s.strip()]
    result["single_statement"] = len(statements) <= 1
    if not result["single_statement"]:
        result["reasons"].append("MULTIPLE_STATEMENTS")

    # 2. SELECT-only: must start with SELECT or WITH (CTE), and contain no banned keyword
    head = re.match(r"\s*(\w+)", body)
    starts_read = bool(head) and head.group(1).upper() in ("SELECT", "WITH")
    banned_hit = _BANNED_RE.search(body)
    result["select_only"] = starts_read and not banned_hit
    if not starts_read:
        result["reasons"].append("NOT_A_SELECT")
    if banned_hit:
        result["reasons"].append(f"BANNED_KEYWORD:{banned_hit.group(1).upper()}")

    # 3. relations referenced must be in the allowlist
    refs = [_short_relation(m.group(1)) for m in _RELATION_RE.finditer(body)]
    result["referenced_relations"] = sorted(set(refs))
    allow = set(result["allowlisted_views"])
    disallowed = sorted({r for r in refs if r not in allow})
    result["disallowed_relations"] = disallowed
    result["allowlisted"] = len(refs) > 0 and not disallowed
    if disallowed:
        result["reasons"].append("RELATION_NOT_ALLOWLISTED")
    elif not refs:
        result["reasons"].append("NO_RELATION_FOUND")

    # 4. scope filter present AND VALUE-BOUND: each locked predicate must be bound to its scope value
    # (a param bind, IN(...), or equality to the value) - not merely have its column name appear.
    low = body.lower()
    result["row_cap_present"] = bool(re.search(r"\blimit\s+(?::\w+|\d+)", low))
    if scope_predicates:
        missing = [p for p in scope_predicates
                   if not _scope_bound(low, _SCOPE_COLUMNS.get(p, (p,)), scope.get(p))]
        result["scope_filter_present"] = not missing
        if missing:
            result["reasons"].append("SCOPE_FILTER_NOT_BOUND")
            result["missing_scope_predicates"] = missing
    else:
        # No locked scope predicates at all -> unscoped query is not allowed.
        result["scope_filter_present"] = False
        result["reasons"].append("NO_SCOPE_PREDICATES")

    # verdict: any hard-safety failure => REJECTED; scope/allowlist-only concern => WARN
    hard = result["reasons"] and any(
        r == "NOT_A_SELECT" or r == "MULTIPLE_STATEMENTS" or r.startswith("BANNED_KEYWORD")
        for r in result["reasons"]
    )
    if hard:
        result["status"] = "REJECTED"
    elif result["select_only"] and result["allowlisted"] and result["scope_filter_present"]:
        result["status"] = "PASSED"
        result["reasons"] = result["reasons"] or ["OK"]
    else:
        # readable SELECT but scope/allowlist not proven -> do not execute; surface as WARN
        result["status"] = "WARN"
    return result
