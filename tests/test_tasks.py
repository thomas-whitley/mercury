"""The task type registry: one row per type, in code."""

import httpx2

from app.config import PROVIDERS
from app.mercury_config import TaskSettings
from app.tasks import TASK_TYPES, configure_task_types

EXPECTED_NAMES = {"pytest", "chat", "repo_chore", "site_check", "digest"}


def test_the_five_task_types_are_registered():
    assert set(TASK_TYPES) == EXPECTED_NAMES


def test_no_type_is_public():
    """pytest was public until the worker was found to run its task as code
    beside the worker's secrets. Every type now needs the bearer token."""
    assert all(TASK_TYPES[name].public is False for name in EXPECTED_NAMES)


def test_site_check_makes_no_model_call():
    assert TASK_TYPES["site_check"].provider is None
    assert TASK_TYPES["site_check"].budget_tokens == 0


def test_every_other_type_names_a_registered_provider():
    for name in EXPECTED_NAMES - {"site_check"}:
        provider = TASK_TYPES[name].provider
        assert provider in PROVIDERS, f"{name} names provider {provider!r}, not in PROVIDERS"


def test_pytest_keeps_its_current_budget():
    """50000 is the token budget the loop already runs with. Registering it must not change it."""
    assert TASK_TYPES["pytest"].budget_tokens == 50_000


def test_providers_map_a_name_to_its_connection_details():
    assert PROVIDERS["gemini"].kind == "openai_compatible"
    assert PROVIDERS["gemini"].base_url
    assert PROVIDERS["gemini"].api_key_env == "MODEL_API_KEY"

    assert PROVIDERS["haiku"].kind == "anthropic"
    assert PROVIDERS["haiku"].api_key_env == "ANTHROPIC_API_KEY"


def test_ollama_is_registered_as_an_openai_compatible_provider_at_no_cost():
    ollama = PROVIDERS["ollama"]
    assert ollama.kind == "openai_compatible"
    assert ollama.base_url == "https://ollama.com/v1"
    assert ollama.api_key_env == "OLLAMA_API_KEY"
    assert ollama.model == "gpt-oss:120b"
    assert ollama.usd_per_million_tokens == 0.0


def test_chat_runs_on_ollama_and_the_rest_on_gemini():
    assert TASK_TYPES["chat"].provider == "ollama"
    for name in ("pytest", "repo_chore", "digest"):
        assert TASK_TYPES[name].provider == "gemini", name


def test_every_model_type_falls_back_to_a_different_registered_provider():
    for name in EXPECTED_NAMES - {"site_check"}:
        ladder = TASK_TYPES[name].ladder
        assert len(ladder) >= 2, name
        assert len(set(ladder)) == len(ladder), name
        assert all(provider in PROVIDERS for provider in ladder), name


def test_the_shipped_ladders_are_free_and_start_where_they_did():
    assert TASK_TYPES["repo_chore"].ladder == ("gemini", "ollama")
    assert TASK_TYPES["chat"].ladder == ("ollama", "gemini")
    assert TASK_TYPES["site_check"].ladder == ()
    for name, task_type in TASK_TYPES.items():
        assert all(PROVIDERS[p].usd_per_million_tokens == 0 for p in task_type.ladder), name


def test_the_config_replaces_a_types_ladder_and_budget(restore_task_types):
    configure_task_types({"repo_chore": TaskSettings(ladder=("ollama",), budget_tokens=30_000)})

    assert TASK_TYPES["repo_chore"].provider == "ollama"
    assert TASK_TYPES["repo_chore"].ladder == ("ollama",)
    assert TASK_TYPES["repo_chore"].budget_tokens == 30_000
    assert TASK_TYPES["pytest"].ladder == ("gemini", "ollama")


def test_a_config_with_no_budget_keeps_the_types_own(restore_task_types):
    configure_task_types({"digest": TaskSettings(ladder=("ollama",), budget_tokens=None)})
    assert TASK_TYPES["digest"].budget_tokens == 20_000


def test_the_api_applies_the_configs_ladder_at_startup(
    start_server, auth_headers, monkeypatch, tmp_path, restore_task_types
):
    config = tmp_path / "mercury.yaml"
    config.write_text("tasks:\n  pytest:\n    ladder: [ollama, gemini]\n", encoding="utf-8")
    monkeypatch.setenv("MERCURY_CONFIG_PATH", str(config))
    base = start_server()

    created = httpx2.post(
        f"{base}/runs",
        json={"type": "pytest", "inputs": {"task": "def test_one():\n    assert 1\n"}},
        headers=auth_headers,
    )
    run = httpx2.get(f"{base}/runs/{created.json()['id']}", headers=auth_headers).json()

    assert run["provider"] == "ollama"
