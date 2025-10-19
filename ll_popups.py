"""CLI tool to manage Home Assistant Lovelace pop-up stacks."""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, MutableMapping, MutableSequence, Optional, Tuple

try:  # pragma: no cover - import is environment specific
    from ruamel.yaml import YAML  # type: ignore
except ImportError as exc:  # pragma: no cover - exercised when ruamel is missing
    YAML = None  # type: ignore
    _RUAMEL_IMPORT_ERROR = exc
else:  # pragma: no cover - executed when ruamel is available
    _RUAMEL_IMPORT_ERROR = None


logger = logging.getLogger(__name__)


def _yaml_loader() -> YAML:
    """Return a ruamel YAML loader configured for round-trip parsing."""

    if YAML is None:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "ruamel.yaml is required for YAML parsing. Please install it to run this tool."
        ) from _RUAMEL_IMPORT_ERROR
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    return yaml


def load_yaml_roundtrip(path: Path) -> Any:
    """Load YAML content with ruamel.yaml while preserving comments and order."""

    loader = _yaml_loader()
    try:
        with path.open("r", encoding="utf-8") as handle:
            return loader.load(handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"YAML file not found: {path}") from exc
    except Exception as exc:  # pragma: no cover - precise error messages vary
        raise ValueError(f"Failed to parse YAML file {path}: {exc}") from exc


def save_yaml_roundtrip(data: Any, path: Path, indent: int = 2, pretty: bool = False) -> None:
    """Persist YAML content while keeping formatting details where possible."""

    dumper = _yaml_loader()
    if pretty:
        dumper.default_flow_style = False
        dumper.indent(mapping=indent, sequence=indent, offset=0)
    try:
        with path.open("w", encoding="utf-8") as handle:
            dumper.dump(data, handle)
    except Exception as exc:  # pragma: no cover - filesystem errors are rare in tests
        raise ValueError(f"Failed to write YAML file {path}: {exc}") from exc


def slugify_area(name: str) -> str:
    """Return a Home Assistant compatible slug for an area name."""

    translit = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
    result: List[str] = []
    for char in name.strip().lower():
        if char in translit:
            result.append(translit[char])
            continue
        if char.isalnum():
            result.append(char)
            continue
        if char in {" ", "/"}:
            result.append("_")
    slug = "".join(result)
    return slug


def _normalise_room(value: str) -> str:
    return value.strip().casefold()


def _is_bubble_popup(stack: Any) -> bool:
    if not isinstance(stack, MutableMapping):
        return False
    if stack.get("type") != "vertical-stack":
        return False
    cards = stack.get("cards")
    if not isinstance(cards, MutableSequence) or not cards:
        return False
    first = cards[0]
    if not isinstance(first, MutableMapping):
        return False
    return first.get("type") == "custom:bubble-card" and first.get("card_type") == "pop-up"


def _extract_area_from_node(node: Any) -> Optional[str]:
    if isinstance(node, MutableMapping):
        if "area" in node and isinstance(node["area"], str):
            return node["area"]
        if "target" in node:
            target = node["target"]
            if isinstance(target, MutableMapping):
                area_id = target.get("area_id")
                if isinstance(area_id, str):
                    return area_id
        for value in node.values():
            extracted = _extract_area_from_node(value)
            if extracted:
                return extracted
    elif isinstance(node, MutableSequence):
        for item in node:
            extracted = _extract_area_from_node(item)
            if extracted:
                return extracted
    return None


@dataclass
class StackMatch:
    index: Optional[int]
    duplicates: List[int]


def find_existing_stack(
    grid: MutableMapping[str, Any],
    room: str,
    area_id: str,
    strategy: str,
) -> StackMatch:
    cards = grid.get("cards")
    if not isinstance(cards, MutableSequence):
        raise ValueError("Grid card structure is malformed: expected 'cards' list")

    wanted_name = _normalise_room(room)
    wanted_hash = f"#{area_id}-popup"

    found_index: Optional[int] = None
    duplicates: List[int] = []

    for idx, stack in enumerate(cards):
        if not _is_bubble_popup(stack):
            continue

        first_card = stack["cards"][0]
        match = False
        if strategy == "name":
            name = first_card.get("name")
            if isinstance(name, str) and _normalise_room(name) == wanted_name:
                match = True
        elif strategy == "hash":
            hash_value = first_card.get("hash")
            if isinstance(hash_value, str) and hash_value == wanted_hash:
                match = True
        elif strategy == "area":
            area = _extract_area_from_node(stack)
            if isinstance(area, str) and area == area_id:
                match = True
        else:  # pragma: no cover - guarded by argparse choices
            raise ValueError(f"Unknown detection strategy: {strategy}")

        if match:
            if found_index is None:
                found_index = idx
            else:
                duplicates.append(idx)

    return StackMatch(found_index, duplicates)


def _deepcopy_template(template: Any) -> Any:
    return copy.deepcopy(template)


def _replace_placeholders(node: Any, replacements: Dict[str, str], icon_value: Optional[str]) -> Tuple[Any, bool]:
    icon_consumed = False
    if isinstance(node, str):
        if node in replacements:
            return replacements[node], icon_consumed
        if node == "__ICON__":
            if icon_value is not None:
                icon_consumed = True
                return icon_value, icon_consumed
            return node, icon_consumed
        return node, icon_consumed
    if isinstance(node, MutableMapping):
        for key, value in list(node.items()):
            replaced, consumed = _replace_placeholders(value, replacements, icon_value)
            if consumed:
                icon_consumed = True
            node[key] = replaced
        return node, icon_consumed
    if isinstance(node, MutableSequence):
        for idx in range(len(node)):
            replaced, consumed = _replace_placeholders(node[idx], replacements, icon_value)
            if consumed:
                icon_consumed = True
            node[idx] = replaced
        return node, icon_consumed
    return node, icon_consumed


def _apply_area_heuristics(node: Any, area_id: str) -> None:
    if isinstance(node, MutableMapping):
        for key, value in list(node.items()):
            if key == "area":
                node[key] = area_id
            elif key == "target" and isinstance(value, MutableMapping):
                if "area_id" in value:
                    value["area_id"] = area_id
                _apply_area_heuristics(value, area_id)
            else:
                _apply_area_heuristics(value, area_id)
    elif isinstance(node, MutableSequence):
        for item in node:
            _apply_area_heuristics(item, area_id)


def deep_apply_template(
    template: MutableMapping[str, Any],
    room: str,
    area_id: str,
    icon_map: Optional[Dict[str, str]] = None,
) -> MutableMapping[str, Any]:
    stack_copy = _deepcopy_template(template)
    icon_value = None
    if icon_map:
        icon_value = icon_map.get(room)

    replacements = {
        "__AREA_NAME__": room,
        "__AREA_ID__": area_id,
        "__HASH__": f"#{area_id}-popup",
    }
    stack_copy, icon_consumed = _replace_placeholders(stack_copy, replacements, icon_value)

    _apply_area_heuristics(stack_copy, area_id)

    cards = stack_copy.get("cards") if isinstance(stack_copy, MutableMapping) else None
    if isinstance(cards, MutableSequence) and cards:
        bubble = cards[0]
        if isinstance(bubble, MutableMapping):
            if "name" in bubble:
                bubble["name"] = room
            if "hash" in bubble:
                bubble["hash"] = f"#{area_id}-popup"
            if "icon" in bubble:
                if icon_value is not None:
                    bubble["icon"] = icon_value
                elif icon_consumed:
                    bubble["icon"] = icon_value
    return stack_copy


def replace_or_append(
    cards: MutableSequence[Any],
    new_stack: MutableMapping[str, Any],
    index: Optional[int],
    insert_mode: str,
) -> Tuple[int, str]:
    action = "appended"
    if index is not None:
        cards[index] = new_stack
        action = "replaced"
        return index, action

    if insert_mode == "append":
        cards.append(new_stack)
        return len(cards) - 1, action

    # keep-index without existing entry -> append
    cards.append(new_stack)
    return len(cards) - 1, action


def compute_diff(before: str, after: str, context: int = 3) -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile="before",
        tofile="after",
        n=context,
    )
    lines = list(diff)
    return "\n".join(lines)


def _stringify_yaml(data: Any, indent: int = 2, pretty: bool = False) -> str:
    dumper = _yaml_loader()
    if pretty:
        dumper.default_flow_style = False
        dumper.indent(mapping=indent, sequence=indent, offset=0)
    stream = sys.modules.get("io").StringIO() if "io" in sys.modules else None
    if stream is None:
        import io

        stream = io.StringIO()
    dumper.dump(data, stream)
    return stream.getvalue()


def _load_icon_map() -> Optional[Dict[str, str]]:
    raw = os.getenv("LL_ICON_MAP")
    if not raw:
        return None
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid LL_ICON_MAP JSON: {exc}") from exc
    if not isinstance(mapping, dict):
        raise ValueError("LL_ICON_MAP must be a JSON object mapping room names to icons")
    return {str(key): str(value) for key, value in mapping.items()}


def _validate_grid(data: Any) -> MutableMapping[str, Any]:
    if not isinstance(data, MutableMapping):
        raise ValueError("Grid YAML must be a mapping at the root")
    if data.get("type") != "grid":
        raise ValueError("Grid root must have type: grid")
    cards = data.get("cards")
    if not isinstance(cards, MutableSequence):
        raise ValueError("Grid must contain a 'cards' list")
    return data


def _validate_template(data: Any) -> MutableMapping[str, Any]:
    if not isinstance(data, MutableMapping):
        raise ValueError("Template YAML must be a mapping at the root")
    if data.get("type") != "vertical-stack":
        raise ValueError("Template root must have type: vertical-stack")
    cards = data.get("cards")
    if not isinstance(cards, MutableSequence) or not cards:
        raise ValueError("Template must contain a non-empty 'cards' list")
    first = cards[0]
    if not isinstance(first, MutableMapping):
        raise ValueError("Template first card must be a mapping")
    if first.get("type") != "custom:bubble-card" or first.get("card_type") != "pop-up":
        raise ValueError("Template must start with a custom:bubble-card pop-up")
    return data


def process_rooms(
    grid: MutableMapping[str, Any],
    rooms: Iterable[str],
    template: MutableMapping[str, Any],
    strategy: str,
    insert_mode: str,
    icon_map: Optional[Dict[str, str]],
) -> List[str]:
    cards = grid["cards"]
    reports: List[str] = []
    for room in rooms:
        area_id = slugify_area(room)
        match = find_existing_stack(grid, room, area_id, strategy)
        if match.duplicates:
            logger.warning(
                "Multiple stacks detected for room '%s' (indices %s); only the first (%s) will be replaced.",
                room,
                match.duplicates,
                match.index,
            )
        new_stack = deep_apply_template(template, room, area_id, icon_map)
        index, action = replace_or_append(cards, new_stack, match.index, insert_mode)
        reports.append(f"{room}: {action} at index {index}")
    return reports


def load_rooms(path: Path) -> List[str]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Rooms file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse rooms JSON {path}: {exc}") from exc
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError("Rooms JSON must be a list of strings")
    return data


def _handle_backup(grid_in: Path, grid_out: Optional[Path], backup: bool) -> None:
    if not backup or grid_out is None:
        return
    if grid_in.resolve() != grid_out.resolve():
        return
    backup_path = grid_in.with_suffix(grid_in.suffix + ".bak")
    if backup_path.exists():
        logger.info("Backup file already exists: %s", backup_path)
        return
    backup_path.write_bytes(grid_in.read_bytes())
    logger.info("Created backup at %s", backup_path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid-in", required=True, type=Path)
    parser.add_argument("--rooms", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--grid-out", type=Path)
    parser.add_argument("--insert-mode", choices=["append", "keep-index"], default="append")
    parser.add_argument("--detect-by", choices=["name", "hash", "area"], default="name")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--indent", type=int, default=2)
    parser.add_argument(
        "--example",
        action="store_true",
        help="Show example usage and exit",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.example:
        print(
            "python ll_popups.py --grid-in grid.yaml --rooms rooms.json --template popup.yaml "
            "--grid-out out.yaml --detect-by name --insert-mode keep-index --backup --pretty"
        )
        return 0

    grid_in: Path = args.grid_in
    grid_out: Optional[Path] = args.grid_out
    rooms_path: Path = args.rooms
    template_path: Path = args.template

    grid_data = _validate_grid(load_yaml_roundtrip(grid_in))
    template_data = _validate_template(load_yaml_roundtrip(template_path))
    rooms = load_rooms(rooms_path)
    icon_map = _load_icon_map()

    before_yaml = _stringify_yaml(grid_data, indent=args.indent, pretty=args.pretty)
    reports = process_rooms(
        grid_data,
        rooms,
        template_data,
        args.detect_by,
        args.insert_mode,
        icon_map,
    )

    after_yaml = _stringify_yaml(grid_data, indent=args.indent, pretty=args.pretty)

    if args.dry_run:
        for report in reports:
            print(report)
        diff = compute_diff(before_yaml, after_yaml)
        if diff:
            print(diff)
        else:
            print("No changes detected.")
        return 0

    if grid_out is None:
        sys.stdout.write(after_yaml)
        return 0

    _handle_backup(grid_in, grid_out, args.backup)
    save_yaml_roundtrip(grid_data, grid_out, indent=args.indent, pretty=args.pretty)
    for report in reports:
        logger.info(report)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via CLI invocation
    raise SystemExit(main())
