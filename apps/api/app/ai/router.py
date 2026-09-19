"""Model routing.

Routes to a **pool**, not a bare model. A pool is one cache namespace: caches are
model-scoped, so every additional model fragments the prompt cache that §5.4
calls the biggest lever on spend. Naming pools makes the cost of adding one
visible rather than incidental.

Tasks stay separately named, as §5.3 asks, so any single task can be re-pointed
without a code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import structlog
import yaml

from app.config import CONFIG_DIR

log = structlog.get_logger()

CONFIG_PATH = CONFIG_DIR / "models.yaml"


@dataclass(frozen=True)
class TaskRoute:
    task: str
    pool: str
    model: str
    max_tokens: int
    effort: str | None
    cache_ttl: str
    batch: bool


@lru_cache
def _config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@lru_cache
def route_for(task: str) -> TaskRoute:
    config = _config()
    if task not in config["tasks"]:
        raise KeyError(f"no route for task '{task}' in {CONFIG_PATH}")

    task_config = config["tasks"][task]
    pool_name = task_config["pool"]
    pool = config["pools"][pool_name]
    defaults = config.get("defaults", {})

    model = pool["model"]
    # The cost ceiling is a decision, not a default. Assert it here so an
    # unreviewed config edit cannot quietly undo it.
    if "opus" in model:
        raise ValueError(
            f"pool '{pool_name}' routes to '{model}', but Opus is excluded for cost. "
            "Change this deliberately if you mean to."
        )

    return TaskRoute(
        task=task,
        pool=pool_name,
        model=model,
        max_tokens=task_config.get("max_tokens", defaults.get("max_tokens", 4096)),
        effort=pool.get("effort"),
        cache_ttl=pool.get("cache_ttl", "5m"),
        batch=task_config.get("batch", False),
    )


def check_cache_prefixes(client) -> None:
    """Warn when a pool's prompt prefix is too short to cache.

    Minimum cacheable prefix is model-dependent: 1024 tokens on Sonnet 5, 4096
    on Haiku 4.5. Below it the API silently declines to cache while still
    charging the write premium — the most likely quiet money leak in the system,
    and §5.4's "cache every skill file" advice causes it directly.
    """
    from app.skills.loader import available_skills, load_skill

    from app.ai.pricing import pricing_for

    config = _config()
    by_pool: dict[str, list[str]] = {}
    for skill_id in available_skills():
        skill = load_skill(skill_id)
        by_pool.setdefault(skill.pool, []).append(skill_id)

    for pool_name, skill_ids in by_pool.items():
        pool = config["pools"][pool_name]
        model = pool["model"]
        minimum = pricing_for(model).min_cache_prefix_tokens

        for skill_id in skill_ids:
            skill = load_skill(skill_id)
            counted = client.messages.count_tokens(
                model=model,
                system=skill.system_prompt,
                messages=[{"role": "user", "content": "x"}],
            )
            tokens = counted.input_tokens
            if tokens < minimum:
                log.warning(
                    "caching_disabled_prefix_too_short",
                    skill=skill_id,
                    pool=pool_name,
                    model=model,
                    tokens=tokens,
                    minimum=minimum,
                )
            else:
                log.info(
                    "cache_prefix_ok", skill=skill_id, tokens=tokens, minimum=minimum
                )


def clear_cache() -> None:
    _config.cache_clear()
    route_for.cache_clear()
