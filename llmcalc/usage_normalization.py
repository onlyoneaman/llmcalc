"""Normalize provider usage objects into billable token subsets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

MAX_SAFE_INTEGER = 2**53 - 1

TEXT_INPUT_MESSAGE = (
    "llmcalc takes token counts, not text. Pass integer input/output token counts, "
    "or the provider's usage object (for example response.usage). llmcalc does not "
    "tokenize strings or message lists."
)

_INPUT_KEYS = ("input_tokens", "prompt_tokens", "inputTokens", "promptTokens")
_OUTPUT_KEYS = ("output_tokens", "completion_tokens", "outputTokens", "completionTokens")
_GEMINI_INPUT_KEYS = ("prompt_token_count", "promptTokenCount")
_GEMINI_OUTPUT_KEYS = (
    "candidates_token_count",
    "candidatesTokenCount",
    "response_token_count",
    "responseTokenCount",
)
_GEMINI_CACHE_KEYS = ("cached_content_token_count", "cachedContentTokenCount")
_GEMINI_REASONING_KEYS = ("thoughts_token_count", "thoughtsTokenCount")
_GEMINI_TOOL_USE_KEYS = ("tool_use_prompt_token_count", "toolUsePromptTokenCount")
_GEMINI_TOTAL_KEYS = ("total_token_count", "totalTokenCount")
_PROMPT_DETAIL_KEYS = ("prompt_tokens_details", "promptTokensDetails", "input_tokens_details")
_COMPLETION_DETAIL_KEYS = (
    "completion_tokens_details",
    "completionTokensDetails",
    "output_tokens_details",
    "candidates_tokens_details",
    "candidatesTokensDetails",
    "response_tokens_details",
    "responseTokensDetails",
)
_CACHE_READ_KEYS = ("cache_read_input_tokens", "cacheReadInputTokens")
_CACHE_CREATION_KEYS = (
    "cache_creation_input_tokens",
    "cacheCreationInputTokens",
    "cache_write_input_tokens",
    "cacheWriteInputTokens",
)
_CACHED_SUBSET_KEYS = ("cached_tokens", "cachedTokens")
_CACHE_WRITE_SUBSET_KEYS = ("cache_write_tokens", "cacheWriteTokens")
_REASONING_KEYS = (
    "reasoning_tokens",
    "reasoningTokens",
    "thinking_tokens",
    "thinkingTokens",
)
_CACHE_CREATION_DETAIL_KEYS = ("cache_creation", "cacheCreation")
_FIVE_MINUTE_CACHE_KEYS = ("ephemeral_5m_input_tokens", "ephemeral5mInputTokens")
_ONE_HOUR_CACHE_KEYS = ("ephemeral_1h_input_tokens", "ephemeral1hInputTokens")
_BEDROCK_CACHE_DETAIL_KEYS = ("cache_details", "cacheDetails")
_BEDROCK_DETAIL_TOKEN_KEYS = ("input_tokens", "inputTokens")
_SERVICE_TIER_KEYS = ("service_tier", "serviceTier", "traffic_type", "trafficType")
_STANDARD_SERVICE_TIERS = {
    "0",
    "default",
    "standard",
    "standard_only",
    "on_demand",
    "service_tier_unspecified",
    "unspecified",
    "traffic_type_unspecified",
}
@dataclass(frozen=True)
class NormalizedUsage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0
    processing_mode: str | None = None
    cache_creation_tokens_1h: int = 0
    cache_creation_audio_tokens: int = 0
    cached_audio_tokens: int = 0
    cached_image_tokens: int = 0
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0
    input_image_tokens: int = 0
    output_image_tokens: int = 0
    query_count: int = 0
    web_search_requests: int = 0
    maps_grounding_requests: int = 0


def validate_token_count(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    if value > MAX_SAFE_INTEGER:
        raise ValueError(f"{field_name} must not exceed {MAX_SAFE_INTEGER}")


def _coerce_token_value(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if type(value) is int:
        validate_token_count(value, field_name)
        return value
    raise ValueError(f"{field_name} must be an integer, got {type(value).__name__}")


def _value_from_mapping(
    usage: Mapping[str, Any], key_options: tuple[str, ...], field_name: str
) -> int | None:
    for key in key_options:
        if key in usage:
            value = _coerce_token_value(usage[key], field_name)
            if value is not None:
                return value
    return None


def _attr_token(usage: Any, names: tuple[str, ...], field_name: str) -> int | None:
    for name in names:
        value = getattr(usage, name, None)
        if value is not None:
            return _coerce_token_value(value, field_name)
    return None


def _nested(usage: Any, container_keys: tuple[str, ...], names: tuple[str, ...]) -> int:
    for container_key in container_keys:
        container = (
            usage.get(container_key)
            if isinstance(usage, Mapping)
            else getattr(usage, container_key, None)
        )
        if container is None:
            continue
        value = (
            _value_from_mapping(container, names, container_key)
            if isinstance(container, Mapping)
            else _attr_token(container, names, container_key)
        )
        if value is not None:
            return value
    return 0


def _flat(usage: Any, names: tuple[str, ...], field_name: str) -> int | None:
    if isinstance(usage, Mapping):
        return _value_from_mapping(usage, names, field_name)
    return _attr_token(usage, names, field_name)


def _raw_value(value: object, names: tuple[str, ...]) -> object | None:
    for name in names:
        candidate = value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)
        if candidate is not None:
            return cast(object, candidate)
    return None


def _processing_mode(usage: object) -> str | None:
    tier = _raw_value(usage, _SERVICE_TIER_KEYS)
    if tier is None:
        return None
    raw_tier = getattr(tier, "value", tier)
    normalized = str(raw_tier).strip().lower().replace("-", "_")
    if normalized in _STANDARD_SERVICE_TIERS or normalized in {
        "auto",
        "on_demand",
        "provisioned_throughput",
    }:
        return "standard"
    if normalized in {"priority", "fast", "on_demand_priority"}:
        return "priority"
    if normalized in {"flex", "on_demand_flex"}:
        return "flex"
    if normalized in {"batch", "batches"}:
        return "batch"
    raise ValueError(f"service tier {raw_tier!s} is not supported")


def _modality_counts(details: object | None, field_name: str) -> tuple[int, int]:
    if details is None:
        return 0, 0
    if isinstance(details, (list, tuple)):
        audio = 0
        image = 0
        for detail in details:
            modality = _raw_value(detail, ("modality",))
            tokens = _flat(detail, ("token_count", "tokenCount"), field_name)
            if modality is None or tokens is None:
                continue
            normalized = str(getattr(modality, "value", modality)).strip().lower()
            if normalized == "audio":
                audio += tokens
            elif normalized in {"image", "document"}:
                image += tokens
            elif normalized not in {"text", "modality_unspecified"} and tokens > 0:
                raise ValueError(f"unsupported token modality: {normalized}")
        validate_token_count(audio, f"{field_name}.audio_tokens")
        validate_token_count(image, f"{field_name}.image_tokens")
        return audio, image

    audio = _flat(details, ("audio_tokens", "audioTokens"), f"{field_name}.audio_tokens") or 0
    image = _flat(details, ("image_tokens", "imageTokens"), f"{field_name}.image_tokens") or 0
    video = _flat(details, ("video_tokens", "videoTokens"), f"{field_name}.video_tokens") or 0
    if video > 0:
        raise ValueError("video token pricing is not supported")
    return audio, image


def _first_details(usage: object, keys: tuple[str, ...]) -> object | None:
    for key in keys:
        details = _raw_value(usage, (key,))
        if details is not None:
            return details
    return None


def _cache_duration_counts(usage: object) -> tuple[int, int]:
    five_minute = _nested(usage, _CACHE_CREATION_DETAIL_KEYS, _FIVE_MINUTE_CACHE_KEYS)
    one_hour = _nested(usage, _CACHE_CREATION_DETAIL_KEYS, _ONE_HOUR_CACHE_KEYS)
    detail_total = five_minute + one_hour
    details = _raw_value(usage, _BEDROCK_CACHE_DETAIL_KEYS)
    if isinstance(details, (list, tuple)):
        for detail in details:
            tokens = _flat(detail, _BEDROCK_DETAIL_TOKEN_KEYS, "cache_details.input_tokens")
            if tokens is None:
                continue
            detail_total += tokens
            if str(_raw_value(detail, ("ttl",))).strip().lower() == "1h":
                one_hour += tokens
    validate_token_count(detail_total, "cache_details.input_tokens")
    validate_token_count(one_hour, "cache_creation_tokens_1h")
    return detail_total, one_hour


def _get_base_usage_tokens(usage: object) -> tuple[int, int, int, int, int]:
    """Normalize provider usage to input, output, cache and reasoning counts."""
    if isinstance(usage, (str, list, tuple)):
        raise ValueError(TEXT_INPUT_MESSAGE)

    if isinstance(usage, Mapping) and "messages" in usage:
        raise ValueError(TEXT_INPUT_MESSAGE)

    gemini_input = _flat(usage, _GEMINI_INPUT_KEYS, "prompt_token_count")
    if gemini_input is not None:
        gemini_output = _flat(usage, _GEMINI_OUTPUT_KEYS, "candidates_token_count") or 0
        cached = _flat(usage, _GEMINI_CACHE_KEYS, "cached_content_token_count") or 0
        reasoning = _flat(usage, _GEMINI_REASONING_KEYS, "thoughts_token_count") or 0
        tool_use = _flat(usage, _GEMINI_TOOL_USE_KEYS, "tool_use_prompt_token_count") or 0
        total = _flat(usage, _GEMINI_TOTAL_KEYS, "total_token_count")
        validate_token_count(gemini_input, "prompt_token_count")
        validate_token_count(gemini_output, "candidates_token_count")
        validate_token_count(cached, "cached_content_token_count")
        validate_token_count(reasoning, "thoughts_token_count")
        validate_token_count(tool_use, "tool_use_prompt_token_count")
        if total is not None:
            validate_token_count(total, "total_token_count")
        if cached > gemini_input:
            raise ValueError("cached_content_token_count must not exceed prompt_token_count")

        output_total = gemini_output + reasoning
        total_without_tool = gemini_input + output_total
        validate_token_count(output_total, "output_tokens")
        validate_token_count(total_without_tool, "total_token_count")

        if tool_use == 0:
            if total is not None and total != total_without_tool:
                raise ValueError("total_token_count is inconsistent with Gemini token details")
            return gemini_input, output_total, cached, 0, reasoning

        if total is None:
            raise ValueError(
                "total_token_count is required to determine whether "
                "tool_use_prompt_token_count is additive"
            )
        if total == total_without_tool:
            return gemini_input, output_total, cached, 0, reasoning
        if total == total_without_tool + tool_use:
            input_total = gemini_input + tool_use
            validate_token_count(input_total, "input_tokens")
            return input_total, output_total, cached, 0, reasoning
        raise ValueError("total_token_count is inconsistent with Gemini token details")

    input_tokens = _flat(usage, _INPUT_KEYS, "input_tokens")
    output_tokens = _flat(usage, _OUTPUT_KEYS, "output_tokens")

    if input_tokens is None or output_tokens is None:
        raise ValueError("usage must provide input/prompt tokens and output/completion tokens")

    validate_token_count(input_tokens, "input_tokens")
    validate_token_count(output_tokens, "output_tokens")
    additive_read = _flat(usage, _CACHE_READ_KEYS, "cache_read_input_tokens")
    additive_creation = _flat(usage, _CACHE_CREATION_KEYS, "cache_creation_input_tokens")

    if additive_read is not None or additive_creation is not None:
        cached = additive_read or 0
        creation = additive_creation or 0
        validate_token_count(cached, "cache_read_input_tokens")
        validate_token_count(creation, "cache_creation_input_tokens")
        input_tokens += cached + creation
        validate_token_count(input_tokens, "input_tokens")
    else:
        cached = _nested(usage, _PROMPT_DETAIL_KEYS, _CACHED_SUBSET_KEYS)
        creation = _nested(usage, _PROMPT_DETAIL_KEYS, _CACHE_WRITE_SUBSET_KEYS)

    reasoning = _nested(usage, _COMPLETION_DETAIL_KEYS, _REASONING_KEYS)
    return input_tokens, output_tokens, cached, creation, reasoning


def _usage_counter(usage: object, names: tuple[str, ...], field_name: str) -> int:
    direct = _flat(usage, names, field_name)
    if direct is not None:
        return direct
    prompt_details = _first_details(usage, _PROMPT_DETAIL_KEYS)
    if prompt_details is not None and not isinstance(prompt_details, (list, tuple)):
        nested = _flat(prompt_details, names, field_name)
        if nested is not None:
            return nested
    return 0


def normalize_usage(usage: object) -> NormalizedUsage:
    input_tokens, output_tokens, cached, creation, reasoning = _get_base_usage_tokens(usage)
    prompt_details = _first_details(usage, _PROMPT_DETAIL_KEYS)
    completion_details = _first_details(usage, _COMPLETION_DETAIL_KEYS)
    input_audio, input_image = _modality_counts(prompt_details, "prompt_tokens_details")
    output_audio, output_image = _modality_counts(
        completion_details, "completion_tokens_details"
    )

    cache_details = _first_details(
        usage,
        ("cache_tokens_details", "cacheTokensDetails"),
    )
    if cache_details is None and prompt_details is not None and not isinstance(
        prompt_details, (list, tuple)
    ):
        cache_details = _raw_value(
            prompt_details,
            ("cached_tokens_details", "cachedTokensDetails"),
        )
    cached_audio, cached_image = _modality_counts(cache_details, "cache_tokens_details")

    detail_total, one_hour = _cache_duration_counts(usage)
    if detail_total > 0:
        if creation > 0 and detail_total != creation:
            raise ValueError(
                "cache duration token details must sum to cache_creation_input_tokens"
            )
        if creation == 0:
            creation = detail_total
            input_tokens += detail_total
            validate_token_count(input_tokens, "input_tokens")
    if one_hour > creation:
        raise ValueError("1-hour cache tokens must not exceed cache creation tokens")

    server_tool_use = _raw_value(usage, ("server_tool_use", "serverToolUse"))
    web_search_requests = _usage_counter(
        usage,
        ("web_search_requests", "webSearchRequests"),
        "web_search_requests",
    )
    if web_search_requests == 0 and server_tool_use is not None:
        web_search_requests = (
            _flat(
                server_tool_use,
                ("web_search_requests", "webSearchRequests"),
                "server_tool_use.web_search_requests",
            )
            or 0
        )
    server_side_tool_use = _raw_value(
        usage,
        ("server_side_tool_usage_details", "serverSideToolUsageDetails"),
    )
    if web_search_requests == 0 and server_side_tool_use is not None:
        web_search_requests = (
            _flat(
                server_side_tool_use,
                ("web_search_calls", "webSearchCalls"),
                "server_side_tool_usage_details.web_search_calls",
            )
            or 0
        )

    normalized = NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached,
        cache_creation_tokens=creation,
        reasoning_tokens=reasoning,
        processing_mode=_processing_mode(usage),
        cache_creation_tokens_1h=one_hour,
        cache_creation_audio_tokens=_usage_counter(
            usage,
            ("cache_creation_audio_tokens", "cacheCreationAudioTokens"),
            "cache_creation_audio_tokens",
        ),
        cached_audio_tokens=cached_audio,
        cached_image_tokens=cached_image,
        input_audio_tokens=input_audio,
        output_audio_tokens=output_audio,
        input_image_tokens=input_image,
        output_image_tokens=output_image,
        query_count=_usage_counter(
            usage,
            ("query_count", "queryCount", "search_units", "searchUnits"),
            "query_count",
        ),
        web_search_requests=web_search_requests,
        maps_grounding_requests=_usage_counter(
            usage,
            ("google_maps_grounding_requests", "googleMapsGroundingRequests"),
            "google_maps_grounding_requests",
        ),
    )
    for field_name, value in normalized.__dict__.items():
        if field_name != "processing_mode":
            validate_token_count(value, field_name)
    return normalized


def get_usage_tokens(usage: object) -> tuple[int, int, int, int, int]:
    normalized = normalize_usage(usage)
    return (
        normalized.input_tokens,
        normalized.output_tokens,
        normalized.cached_tokens,
        normalized.cache_creation_tokens,
        normalized.reasoning_tokens,
    )
