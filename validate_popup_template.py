from __future__ import annotations

import sys
from pathlib import Path

try:
    from ruamel.yaml import YAML  # type: ignore
except ImportError as exc:  # pragma: no cover - depends on environment
    YAML = None  # type: ignore
    _IMPORT_ERROR = exc
else:  # pragma: no cover - executed when ruamel is available
    _IMPORT_ERROR = None


def validate_template(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    placeholders = ["__AREA_NAME__", "__AREA_ID__", "__HASH__"]
    missing = [token for token in placeholders if token not in text]
    if missing:
        raise ValueError(f"Missing placeholders: {', '.join(missing)}")

    if YAML is None:
        raise ValueError(
            "ruamel.yaml is required for validation but is not installed"
        ) from _IMPORT_ERROR

    yaml = YAML(typ="rt")
    try:
        data = yaml.load(text)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"YAML parse error: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Root document is not a mapping")

    if data.get("type") != "vertical-stack":
        raise ValueError("Root 'type' is not 'vertical-stack'")

    cards = data.get("cards")
    if not isinstance(cards, list) or not cards:
        raise ValueError("'cards' must be a non-empty list")

    first_card = cards[0]
    if not isinstance(first_card, dict):
        raise ValueError("First card is not a mapping")

    if first_card.get("type") != "custom:bubble-card":
        raise ValueError("First card 'type' is not 'custom:bubble-card'")

    if first_card.get("card_type") != "pop-up":
        raise ValueError("First card 'card_type' is not 'pop-up'")


def main() -> int:
    path = Path("popup_template.yaml")
    try:
        validate_template(path)
    except Exception as exc:  # noqa: BLE001
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 1
    print("OK popup_template.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
