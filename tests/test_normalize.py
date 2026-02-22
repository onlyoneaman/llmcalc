from llmcalc.normalize import normalize_model_name, resolve_model_key


def test_normalize_model_name_prefixes() -> None:
    assert normalize_model_name(" openai:gpt-4o-mini ") == "gpt-4o-mini"
    assert normalize_model_name("openai/gpt-4.1-mini") == "gpt-4.1-mini"


def test_normalize_model_name_alias() -> None:
    assert normalize_model_name("gpt-4o-mini-latest") == "gpt-4o-mini"


def test_resolve_model_key_case_insensitive_and_prefixed() -> None:
    keys = ["GPT-4O-MINI", "claude-3-5-sonnet"]
    assert resolve_model_key("openai:gpt-4o-mini", keys) == "GPT-4O-MINI"


def test_resolve_model_key_missing() -> None:
    keys = ["gpt-4o-mini"]
    assert resolve_model_key("unknown-model", keys) is None
