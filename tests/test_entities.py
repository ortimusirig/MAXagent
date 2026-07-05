"""LLM entity extraction for the chat (entities.py) with the deterministic resolver as the fail-closed
floor. The model may PROPOSE typed entities; a fabricated/out-of-fleet id or out-of-vocab value is
rejected, and with no LLM bound it degrades to the deterministic resolver."""

from __future__ import annotations

from max_agent.entities import extract_entities
from max_agent.orchestrator import MaxAgent


class _FakeClient:
    def __init__(self, bound: bool, reply=None):
        self._bound, self._reply = bound, reply

    def llm_bound(self):
        return self._bound

    def llm_complete(self, prompt, system=None):
        return self._reply


def _fleet():
    return MaxAgent()._fleet_index


def test_deterministic_floor_when_no_llm():
    ent = extract_entities(_FakeClient(False), "is PUMP-4102 PM effective?", _fleet())
    assert ent["equipment_id"] == "PUMP-4102"
    assert ent["time_window"] == "LAST_24_MONTHS"       # default when not extracted
    assert ent["provenance"] == "deterministic"


def test_llm_proposes_typed_entities():
    fleet = _fleet()
    eid = next(iter(fleet))
    reply = ('{"equipment_id": "%s", "time_window": "LAST_12_MONTHS", '
             '"review_type": "Frequency change review"}') % eid
    ent = extract_entities(_FakeClient(True, reply), "can we stretch this pump, last year?", fleet)
    assert ent["equipment_id"] == eid
    assert ent["time_window"] == "LAST_12_MONTHS"
    assert ent["review_type"] == "Frequency change review"
    assert ent["provenance"] == "llm+deterministic"


def test_fabricated_asset_is_rejected_to_deterministic_floor():
    # Governance floor: an LLM-proposed id that is not a real fleet id is rejected; the deterministic
    # match from the text wins. Valid vocab values (time_window) are still kept.
    reply = '{"equipment_id": "PUMP-9999-FAKE", "time_window": "LAST_36_MONTHS"}'
    ent = extract_entities(_FakeClient(True, reply), "is PUMP-4102 effective?", _fleet())
    assert ent["equipment_id"] == "PUMP-4102"
    assert ent["time_window"] == "LAST_36_MONTHS"


def test_out_of_vocab_values_are_dropped():
    reply = '{"time_window": "LAST_5_YEARS", "criticality": "9", "review_type": "made up review"}'
    ent = extract_entities(_FakeClient(True, reply), "a general fleet question", _fleet())
    assert ent["time_window"] == "LAST_24_MONTHS"   # invalid window -> safe default
    assert ent["criticality"] is None
    assert ent["review_type"] is None


def test_bad_llm_json_degrades_gracefully():
    ent = extract_entities(_FakeClient(True, "sorry, I cannot help with that"), "is PUMP-4102 effective?", _fleet())
    assert ent["equipment_id"] == "PUMP-4102"        # falls back to the deterministic match
    assert ent["time_window"] == "LAST_24_MONTHS"


def test_agent_extract_entities_method():
    agent = MaxAgent()  # no LLM bound locally -> deterministic
    ent = agent.extract_entities("why does COMP-2201 keep failing?")
    assert ent["equipment_id"] == "COMP-2201"
