"""Model pricing and cost calculation.

Spec §7: "every model call is logged with model, token counts, latency and cost."
You cannot optimise spend you cannot see.

Prices are USD per million tokens, verified 2026-09. The spec's §5.3 table is
stale for Sonnet — it lists $3/$15, but Sonnet 5 is $2/$10.

Cache economics matter more than the headline rate: reads cost ~0.1x base input,
writes 1.25x (5-minute TTL) or 2x (1-hour). Getting caching right is a bigger
lever on the bill than model choice, which is why the breakdown is tracked
separately rather than folded into one number.
"""

from __future__ import annotations

from dataclasses import dataclass

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_5M_MULTIPLIER = 1.25
CACHE_WRITE_1H_MULTIPLIER = 2.0
BATCH_DISCOUNT = 0.5


@dataclass(frozen=True)
class ModelPricing:
    input_per_mtok: float
    output_per_mtok: float
    # Minimum prompt prefix that can be cached at all. Below this the API
    # silently declines to cache while still charging the write premium — the
    # most likely quiet money leak in the system.
    min_cache_prefix_tokens: int


PRICING: dict[str, ModelPricing] = {
    "claude-opus-5": ModelPricing(5.00, 25.00, 512),
    "claude-sonnet-5": ModelPricing(2.00, 10.00, 1024),
    "claude-haiku-4-5": ModelPricing(1.00, 5.00, 4096),
}


def pricing_for(model: str) -> ModelPricing:
    if model not in PRICING:
        raise KeyError(
            f"no pricing for '{model}'. Add it to PRICING rather than guessing — "
            "an unpriced model silently logs $0 and hides spend."
        )
    return PRICING[model]


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    *,
    batch: bool = False,
    cache_ttl: str = "5m",
) -> float:
    """Cost in USD for one call.

    ``input_tokens`` is the uncached remainder only — total prompt size is
    input + cache_creation + cache_read.
    """
    price = pricing_for(model)
    write_multiplier = (
        CACHE_WRITE_1H_MULTIPLIER if cache_ttl == "1h" else CACHE_WRITE_5M_MULTIPLIER
    )

    cost = (
        input_tokens * price.input_per_mtok
        + cache_creation_tokens * price.input_per_mtok * write_multiplier
        + cache_read_tokens * price.input_per_mtok * CACHE_READ_MULTIPLIER
        + output_tokens * price.output_per_mtok
    ) / 1_000_000

    return cost * BATCH_DISCOUNT if batch else cost


def cost_from_usage(model: str, usage, *, batch: bool = False, cache_ttl: str = "5m") -> float:
    """Cost from an SDK ``response.usage`` object."""
    return compute_cost(
        model,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        batch=batch,
        cache_ttl=cache_ttl,
    )
