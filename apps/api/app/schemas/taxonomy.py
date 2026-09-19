"""Error taxonomy enums, generated from the YAML at import time.

Spec §5.6 requires the tagger to emit only categories from a controlled list,
because free-text categories make the metrics tab useless — nothing aggregates.

A prompt instruction is necessary but not sufficient. These closed StrEnums,
passed through ``client.messages.parse``, make an out-of-vocabulary value
structurally impossible rather than merely discouraged.

Generating them from ``skills/_shared/error-taxonomy.yaml`` means the enum and
the prompt cannot drift: one file feeds both.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Any

import yaml

from app.config import SKILLS_DIR

TAXONOMY_PATH = SKILLS_DIR / "_shared" / "error-taxonomy.yaml"


@lru_cache
def load_taxonomy() -> dict[str, Any]:
    with TAXONOMY_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not data.get("categories"):
        raise ValueError(f"{TAXONOMY_PATH} defines no categories")
    for name, body in data["categories"].items():
        if not body.get("subcategories"):
            raise ValueError(f"taxonomy category '{name}' has no subcategories")
    return data


_TAXONOMY = load_taxonomy()

# Sorted so enum member order is deterministic; the rendered prompt depends on
# it, and a reordered prompt is a different prompt_hash for no reason.
_CATEGORY_NAMES: list[str] = sorted(_TAXONOMY["categories"])
_SUBCATEGORY_NAMES: list[str] = sorted(
    {
        subcategory
        for category in _TAXONOMY["categories"].values()
        for subcategory in category["subcategories"]
    }
)

ErrorCategory = StrEnum("ErrorCategory", {n.upper(): n for n in _CATEGORY_NAMES})
ErrorSubcategory = StrEnum(
    "ErrorSubcategory", {n.upper(): n for n in _SUBCATEGORY_NAMES}
)
Severity = StrEnum(
    "Severity", {n.upper(): n for n in sorted(_TAXONOMY.get("severities", {}))}
)

# Which subcategories are legal under which category. The flat subcategory enum
# alone would accept `orthography/broken_plural`; this pairing check rejects it.
VALID_PAIRS: frozenset[tuple[str, str]] = frozenset(
    (category, subcategory)
    for category, body in _TAXONOMY["categories"].items()
    for subcategory in body["subcategories"]
)


def is_valid_pair(category: str, subcategory: str) -> bool:
    return (str(category), str(subcategory)) in VALID_PAIRS


def subcategories_for(category: str) -> list[str]:
    return sorted(_TAXONOMY["categories"][str(category)]["subcategories"])


def render_for_prompt() -> str:
    """Render the taxonomy as the markdown block injected into the prompt.

    Deterministic: categories and subcategories are emitted in sorted order, so
    two renders of an unchanged file are byte-identical and the prompt_hash is
    stable.
    """
    lines: list[str] = []
    for category in _CATEGORY_NAMES:
        body = _TAXONOMY["categories"][category]
        lines.append(f"### `{category}` — {body['label']}")
        lines.append(body["description"].strip())
        lines.append("")
        for subcategory in sorted(body["subcategories"]):
            sub = body["subcategories"][subcategory]
            lines.append(f"- `{subcategory}` — {sub['label']}: {sub['description'].strip()}")
            if sub.get("example"):
                lines.append(f"  - Example: {sub['example'].strip()}")
        lines.append("")

    lines.append("### Severity")
    for severity in sorted(_TAXONOMY.get("severities", {})):
        description = _TAXONOMY["severities"][severity]["description"].strip()
        lines.append(f"- `{severity}` — {description}")
    return "\n".join(lines).strip()
