from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from ll_popups import (
    compute_diff,
    deep_apply_template,
    find_existing_stack,
    process_rooms,
    slugify_area,
    _validate_grid,
)


GRID_SAMPLE = {
    "type": "grid",
    "cards": [
        {
            "type": "vertical-stack",
            "cards": [
                {
                    "type": "custom:bubble-card",
                    "card_type": "pop-up",
                    "name": "Saloon",
                    "hash": "#saloon-popup",
                    "icon": "mdi:glass-mug",
                },
                {
                    "type": "entities",
                    "entities": [
                        {
                            "entity": "light.saloon",
                            "name": "Saloon Licht",
                            "domain": "Selecht",
                            "area": "saloon",
                        }
                    ],
                },
            ],
        },
        {
            "type": "vertical-stack",
            "cards": [
                {
                    "type": "custom:bubble-card",
                    "card_type": "pop-up",
                    "name": "Wohnzimmer",
                    "hash": "#wohnzimmer-popup",
                },
                {
                    "type": "tile",
                    "target": {"area_id": "wohnzimmer"},
                },
            ],
        },
    ],
}


TEMPLATE_PLACEHOLDER = {
    "type": "vertical-stack",
    "cards": [
        {
            "type": "custom:bubble-card",
            "card_type": "pop-up",
            "name": "__AREA_NAME__",
            "hash": "__HASH__",
            "icon": "__ICON__",
        },
        {
            "type": "entities",
            "entities": [
                {"area": "__AREA_ID__", "name": "Status"},
                {
                    "type": "custom:some-card",
                    "target": {"area_id": "__AREA_ID__"},
                },
            ],
        },
    ],
}


TEMPLATE_NO_PLACEHOLDER = {
    "type": "vertical-stack",
    "cards": [
        {
            "type": "custom:bubble-card",
            "card_type": "pop-up",
        },
        {
            "type": "entities",
            "entities": [
                {"area": "dummy"},
                {"target": {"area_id": "dummy"}},
            ],
        },
    ],
}


def clone(obj):
    return copy.deepcopy(obj)


def test_slugify_area_handles_umlauts():
    assert slugify_area("Wohnzimmer") == "wohnzimmer"
    assert slugify_area("Außen") == "aussen"
    assert slugify_area("Große Küche") == "grosse_kueche"


@pytest.mark.parametrize(
    "strategy,room,expected",
    [
        ("name", "Saloon", 0),
        ("hash", "Wohnzimmer", 1),
        ("area", "Wohnzimmer", 1),
    ],
)
def test_find_existing_stack(strategy, room, expected):
    grid = clone(GRID_SAMPLE)
    data = _validate_grid(grid)
    area_id = slugify_area(room)
    match = find_existing_stack(data, room, area_id, strategy)
    assert match.index == expected


def test_deep_apply_template_placeholder_and_icon_map():
    template = clone(TEMPLATE_PLACEHOLDER)
    stack = deep_apply_template(template, "Wohnzimmer", "wohnzimmer", {"Wohnzimmer": "mdi:sofa"})
    bubble = stack["cards"][0]
    assert bubble["name"] == "Wohnzimmer"
    assert bubble["hash"] == "#wohnzimmer-popup"
    assert bubble["icon"] == "mdi:sofa"
    entities = stack["cards"][1]["entities"]
    assert entities[0]["area"] == "wohnzimmer"
    assert entities[1]["target"]["area_id"] == "wohnzimmer"


def test_deep_apply_template_without_placeholders_uses_heuristics():
    template = clone(TEMPLATE_NO_PLACEHOLDER)
    stack = deep_apply_template(template, "Galerie", "galerie")
    entities = stack["cards"][1]["entities"]
    assert entities[0]["area"] == "galerie"
    assert entities[1]["target"]["area_id"] == "galerie"


def test_process_rooms_is_idempotent():
    grid = clone(GRID_SAMPLE)
    template = clone(TEMPLATE_PLACEHOLDER)
    rooms = ["Saloon", "Wohnzimmer"]

    first_before = json.dumps(grid, default=str)
    process_rooms(grid, rooms, template, "name", "append", {"Saloon": "mdi:glass"})
    second_before = json.dumps(grid, default=str)
    process_rooms(grid, rooms, template, "name", "append", {"Saloon": "mdi:glass"})
    second_after = json.dumps(grid, default=str)

    assert first_before != second_before
    assert second_before == second_after


def test_compute_diff_has_output():
    diff = compute_diff("a\n", "b\n")
    assert diff.startswith("--- before")
