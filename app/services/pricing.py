"""Claude API pricing — USD per 1,000,000 tokens.

Source: claude-api skill (current as of 2026-01). Update when Anthropic changes
list prices. Cache reads bill ~0.1x input; cache writes ~1.25x input.
"""
from __future__ import annotations

from dataclasses import dataclass

_CACHE_READ_MULT = 0.10
_CACHE_WRITE_MULT = 1.25


@dataclass(frozen=True)
class ModelPrice:
    input_pmt: float   # per million tokens
    output_pmt: float


PRICES: dict[str, ModelPrice] = {
    "claude-opus-5": ModelPrice(5.0, 25.0),
    "claude-sonnet-5": ModelPrice(2.0, 10.0),
    "claude-haiku-4-5": ModelPrice(1.0, 5.0),
    "claude-fable-5-1": ModelPrice(2.0, 10.0),
}
_DEFAULT = PRICES["claude-sonnet-5"]


def price_for(model: str) -> ModelPrice:
    # tolerate dated/suffixed ids like "claude-sonnet-5-20260514"
    if model in PRICES:
        return PRICES[model]
    for key, p in PRICES.items():
        if model.startswith(key):
            return p
    return _DEFAULT


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    p = price_for(model)
    dollars = (
        input_tokens * p.input_pmt
        + output_tokens * p.output_pmt
        + cache_read_tokens * p.input_pmt * _CACHE_READ_MULT
        + cache_write_tokens * p.input_pmt * _CACHE_WRITE_MULT
    ) / 1_000_000
    return round(dollars, 6)


def estimate_article_cost(model: str, in_tokens: int = 6000, out_tokens: int = 8000) -> float:
    """Rough pre-flight estimate for one long-form article."""
    return cost_usd(model, in_tokens, out_tokens)
