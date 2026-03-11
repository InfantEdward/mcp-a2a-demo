from __future__ import annotations

from typing import Any


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def extract_tokens_from_response(message: Any) -> tuple[int, int, int]:
    """
    Extract token usage from LangChain AIMessage-like objects.
    Supports common shapes from providers and wrappers.
    """
    if message is None:
        return (0, 0, 0)

    usage = getattr(message, "usage_metadata", None) or {}
    response_metadata = getattr(message, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage", {})
    usage_meta_nested = response_metadata.get("usage_metadata", {})

    input_tokens = (
        _as_int(usage.get("input_tokens"))
        or _as_int(usage_meta_nested.get("input_tokens"))
        or _as_int(token_usage.get("prompt_token_count"))
        or _as_int(token_usage.get("input_tokens"))
    )
    output_tokens = (
        _as_int(usage.get("output_tokens"))
        or _as_int(usage_meta_nested.get("output_tokens"))
        or _as_int(token_usage.get("candidates_token_count"))
        or _as_int(token_usage.get("output_tokens"))
    )
    total_tokens = (
        _as_int(usage.get("total_tokens"))
        or _as_int(usage_meta_nested.get("total_tokens"))
        or _as_int(token_usage.get("total_token_count"))
        or _as_int(token_usage.get("total_tokens"))
    )

    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens

    return (input_tokens, output_tokens, total_tokens)
