"""JSON-safe values for neomodel JSONProperty writes, and the mapping a read hands back."""


from __future__ import annotations

from datetime import UTC, date, datetime
import json

from django_neomodel.util.json_safe import coerce_json_mapping, json_safe_structure


def test_json_safe_structure_converts_nested_dates_sets_and_keys() -> None:
    payload = {
        'shelves': [
            {'opened': datetime(2026, 5, 23, tzinfo=UTC), 'inventoried': date(2026, 5, 24)},
        ],
        'genres': {'poetry', 'essays'},
        7: ('a', 'b'),
    }
    safe = json_safe_structure(payload)
    json.dumps(safe)
    assert safe['shelves'][0]['opened'].startswith('2026-05-23')
    assert safe['shelves'][0]['inventoried'] == '2026-05-24'
    assert safe['genres'] == ['essays', 'poetry']
    assert safe['7'] == ['a', 'b']


def test_coerce_json_mapping_reads_a_dict_or_its_json_text() -> None:
    assert coerce_json_mapping({'pages': 3}) == {'pages': 3}
    assert coerce_json_mapping('{"pages": 3}') == {'pages': 3}


def test_coerce_json_mapping_turns_anything_else_into_an_empty_mapping() -> None:
    for value in (None, '', '   ', 'not json', '[1, 2]', 42):
        assert coerce_json_mapping(value) == {}
