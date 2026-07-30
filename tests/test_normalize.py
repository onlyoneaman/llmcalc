from llmcalc.normalize import normalize_model_name, resolve_model_key


def test_normalize_model_name_prefixes() -> None:
    assert normalize_model_name(" openai:gpt-5.1 ") == "gpt-5.1"
    assert normalize_model_name("openai/gpt-5.1") == "gpt-5.1"


def test_normalize_model_name_alias() -> None:
    assert normalize_model_name("gpt-5.1-latest") == "gpt-5.1"


def test_resolve_model_key_case_insensitive_and_prefixed() -> None:
    keys = ["GPT-5.1", "claude-3-5-sonnet"]
    assert resolve_model_key("openai:gpt-5.1", keys) == "GPT-5.1"


def test_resolve_model_key_missing() -> None:
    keys = ["gpt-5.1"]
    assert resolve_model_key("unknown-model", keys) is None


def test_bedrock_version_suffix_is_not_stripped() -> None:
    model = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    assert normalize_model_name(model) == model


def test_fine_tune_prefix_is_not_stripped() -> None:
    assert normalize_model_name("ft:gpt-3.5-turbo") == "ft:gpt-3.5-turbo"


def test_bare_version_number_resolves_to_nothing() -> None:
    keys = [
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "anthropic.claude-sonnet-4-20250514-v1:0",
    ]
    assert resolve_model_key("0", keys) is None


def test_bedrock_ids_still_resolve_exactly() -> None:
    keys = ["anthropic.claude-sonnet-4-20250514-v1:0"]
    assert (
        resolve_model_key("anthropic.claude-sonnet-4-20250514-v1:0", keys)
        == "anthropic.claude-sonnet-4-20250514-v1:0"
    )


def test_known_provider_colon_prefix_still_strips() -> None:
    assert normalize_model_name("openai:gpt-5.1") == "gpt-5.1"


def test_multi_separator_keeps_remainder() -> None:
    assert normalize_model_name("openai/foo/bar") == "foo/bar"


def test_version_suffixes_one_and_two_are_preserved() -> None:
    assert normalize_model_name("ai21.jamba-instruct-v1:1") == "ai21.jamba-instruct-v1:1"
    assert normalize_model_name("cohere.command-text-v14:2") == "cohere.command-text-v14:2"
