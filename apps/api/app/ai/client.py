"""Anthropic client wrapper.

Every model call goes through here, so three things happen without fail:

1. **Structured output.** ``client.messages.parse(output_format=Model)`` uses
   constrained decoding, so the response validates against the Pydantic model by
   construction. This replaces §5.5's parse-and-retry loop, which was written
   before structured outputs existed.
2. **Prompt caching.** The skill prompt is the cached prefix; the variable
   content goes after it. Cache hits are verified, not assumed — see
   ``CallResult.cache_hit``.
3. **Cost telemetry.** §7: "every model call is logged with model, token counts,
   latency and cost." A call that fails is logged too; spend you cannot see is
   spend you cannot control.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TypeVar

import anthropic
import structlog
from pydantic import BaseModel

from app.ai.pricing import cost_from_usage
from app.ai.router import route_for
from app.config import get_settings
from app.skills.loader import load_skill

log = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)


@dataclass
class CallResult:
    """One model call: its output plus everything needed to audit it."""

    parsed: Any
    model: str
    pool: str
    skill_id: str
    skill_version: int
    prompt_hash: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float
    latency_ms: int
    status: str = "ok"
    error_detail: str | None = None

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0

    def telemetry_row(self, user_id: str | None = None) -> dict:
        """A row for ``model_calls``."""
        return {
            "user_id": user_id,
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "prompt_hash": self.prompt_hash,
            "model": self.model,
            "pool": self.pool,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_tokens,
            "cache_read_input_tokens": self.cache_read_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error_detail": self.error_detail,
        }


@lru_cache
def get_client() -> anthropic.Anthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set; see .env.example")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def call_skill(
    skill_id: str,
    user_content: str,
    *,
    task: str | None = None,
    output_model: type[T] | None = None,
) -> CallResult:
    """Run one skill against one input.

    The skill prompt is the cached prefix and ``user_content`` the variable tail,
    so repeated calls for the same skill read the cache rather than rewriting it.
    """
    skill = load_skill(skill_id)
    route = route_for(task or skill_id)
    model = output_model or skill.resolve_output_model()
    if model is None:
        raise ValueError(f"skill '{skill_id}' declares no output_model")

    client = get_client()
    started = time.perf_counter()

    request: dict[str, Any] = {
        "model": route.model,
        "max_tokens": route.max_tokens,
        # cache_control on the system block: the skill prompt is stable across
        # calls, the user content is not.
        "system": [
            {
                "type": "text",
                "text": skill.system_prompt,
                "cache_control": {"type": "ephemeral", "ttl": route.cache_ttl},
            }
        ],
        "messages": [{"role": "user", "content": user_content}],
        "output_format": model,
    }
    # Haiku 4.5 rejects `effort`; Sonnet 5 rejects `budget_tokens`.
    if route.effort:
        request["output_config"] = {"effort": route.effort}

    try:
        response = client.messages.parse(**request)
    except Exception as exc:
        # A max_tokens cutoff surfaces here as an opaque "Invalid JSON: EOF"
        # from Pydantic. Name it, because the fix (raise max_tokens) is
        # completely different from the fix for a genuine schema violation.
        detail = str(exc)
        if "EOF while parsing" in detail or "Invalid JSON" in detail:
            detail = (
                f"response truncated before the JSON closed — max_tokens "
                f"({route.max_tokens}) was consumed, most likely by thinking at "
                f"effort={route.effort}. Raise max_tokens for task "
                f"'{route.task}' in config/models.yaml. Original: {detail[:200]}"
            )
            exc = RuntimeError(detail)
        latency = int((time.perf_counter() - started) * 1000)
        log.error("model_call_failed", skill=skill_id, model=route.model, error=str(exc))
        return CallResult(
            parsed=None,
            model=route.model,
            pool=route.pool,
            skill_id=skill.id,
            skill_version=skill.version,
            prompt_hash=skill.prompt_hash,
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
            latency_ms=latency,
            status="api_error",
            error_detail=str(exc)[:500],
        )

    latency = int((time.perf_counter() - started) * 1000)
    if getattr(response, "stop_reason", None) == "max_tokens":
        log.warning(
            "response_hit_max_tokens",
            skill=skill_id,
            max_tokens=route.max_tokens,
            hint="output may be incomplete; raise max_tokens in config/models.yaml",
        )
    usage = response.usage
    result = CallResult(
        parsed=response.parsed_output,
        model=route.model,
        pool=route.pool,
        skill_id=skill.id,
        skill_version=skill.version,
        prompt_hash=skill.prompt_hash,
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cost_usd=cost_from_usage(route.model, usage, cache_ttl=route.cache_ttl),
        latency_ms=latency,
    )

    log.info(
        "model_call",
        skill=skill_id,
        model=route.model,
        cost_usd=round(result.cost_usd, 6),
        latency_ms=latency,
        cache_read=result.cache_read_tokens,
        cache_write=result.cache_creation_tokens,
    )
    return result


def record_call(client, result: CallResult, user_id: str | None = None) -> str | None:
    """Persist telemetry. Returns the ``model_calls`` row id."""
    try:
        row = client.table("model_calls").insert(result.telemetry_row(user_id)).execute()
        return row.data[0]["id"] if row.data else None
    except Exception as exc:  # noqa: BLE001 — telemetry must not break the request
        log.error("telemetry_write_failed", error=str(exc))
        return None
