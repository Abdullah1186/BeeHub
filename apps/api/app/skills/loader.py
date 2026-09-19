"""Skill loading, rendering, and hashing.

Spec §5.1: one markdown file per AI task, and **no prompt text inline in Python**.
Each file is the complete, versioned specification for that task.

The load-bearing detail is ``prompt_hash``: sha256 over the *fully rendered*
prompt — shared prefix, includes, body, and the taxonomy block — not over the
single file. A change to ``error-taxonomy.yaml`` must change the hash of every
skill that includes it, or evals will attribute a result to the wrong prompt and
you will tune against a lie.

Rendering is byte-deterministic: includes in declared order, sorted YAML, no
timestamps, no user IDs. Two renders of an unchanged tree produce identical
bytes, so the hash is stable across processes and machines.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import SKILLS_DIR

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

# Placeholder the taxonomy block is substituted into. Kept explicit so a skill
# file declares where it wants the controlled vocabulary.
TAXONOMY_TOKEN = "{{ERROR_TAXONOMY}}"


@dataclass(frozen=True)
class RenderedSkill:
    id: str
    version: int
    pool: str
    output_model: str | None
    system_prompt: str
    prompt_hash: str
    content_hash: str

    def resolve_output_model(self) -> type | None:
        """Import the Pydantic model this skill's output must validate against."""
        if not self.output_model:
            return None
        module_path, _, class_name = self.output_model.rpartition(".")
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name)


def _read(path: Path) -> tuple[dict, str]:
    """Split a skill file into frontmatter and body."""
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    if not match:
        raise ValueError(f"{path} has no YAML frontmatter")
    meta = yaml.safe_load(match.group(1)) or {}
    return meta, match.group(2).strip()


def _render_includes(names: list[str]) -> str:
    """Concatenate shared reference files, in declared order.

    Order is the author's, not sorted: these read as a document, and reordering
    them would change the hash without changing meaning.
    """
    parts: list[str] = []
    for name in names:
        path = SKILLS_DIR / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"skill include not found: {path}")
        parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n".join(parts)


@lru_cache
def load_skill(skill_id: str) -> RenderedSkill:
    """Load and render one skill.

    Cached: skills are read once at startup and never hot-reloaded in
    production. A mid-request change would break the cached prompt prefix and
    produce two different results recorded under one prompt_hash.
    """
    path = SKILLS_DIR / f"{skill_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"no skill file at {path}")

    meta, body = _read(path)
    for field in ("id", "version", "pool"):
        if field not in meta:
            raise ValueError(f"{path} frontmatter is missing '{field}'")
    if meta["id"] != skill_id:
        raise ValueError(f"{path} declares id '{meta['id']}' but is named '{skill_id}'")

    includes = _render_includes(meta.get("includes", []))

    # Substitute the taxonomy where the skill asked for it, so the enum and the
    # prompt cannot drift (see app/schemas/taxonomy.py).
    if TAXONOMY_TOKEN in body or TAXONOMY_TOKEN in includes:
        from app.schemas.taxonomy import render_for_prompt

        taxonomy = render_for_prompt()
        body = body.replace(TAXONOMY_TOKEN, taxonomy)
        includes = includes.replace(TAXONOMY_TOKEN, taxonomy)

    system_prompt = f"{includes}\n\n{body}".strip() if includes else body

    return RenderedSkill(
        id=skill_id,
        version=int(meta["version"]),
        pool=meta["pool"],
        output_model=meta.get("output_model"),
        system_prompt=system_prompt,
        # Hash the RENDERED prompt, so a shared-include edit propagates.
        prompt_hash=hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        # Hash the file alone, to identify *which* file changed.
        content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def available_skills() -> list[str]:
    return sorted(
        p.stem
        for p in SKILLS_DIR.glob("*.md")
        if not p.name.startswith("_")
    )


def clear_cache() -> None:
    """For tests and the dev --reload-skills flag."""
    load_skill.cache_clear()
