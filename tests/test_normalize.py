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
