"""Runtime configuration. Everything here is an environment variable, not code."""

import os
import socket
import uuid
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql://agent:agent@localhost:5432/agent_runs"
# Settings.model no longer names which model runs; PROVIDERS does that per
# provider. This default only has to be something other than "stub".
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_EMBEDDING_MODEL = "voyage-3"
# Two minutes, per docs/mercury.md. The Python worker heartbeats once per loop
# step, and a model step can run 112 seconds (4 attempts of 25 seconds plus
# 2, 4 and 6 second waits). The checks worker heartbeats every 30 seconds.
DEFAULT_LEASE_SECONDS = 120.0
# Thirty minutes, per docs/mercury.md. A lighthouse or broken_links check that
# no self hosted worker claims in this long goes to the cloud PageSpeed path.
# CHECK_CLAIM_WINDOW is in seconds.
DEFAULT_CHECK_CLAIM_WINDOW_SECONDS = 1800.0


@dataclass(frozen=True)
class ProviderConfig:
    """One entry of PROVIDERS. api_key_env names the secret, never holds it."""

    kind: str  # "openai_compatible" or "anthropic"
    base_url: str | None
    api_key_env: str
    model: str
    # What the monthly cap charges per million tokens. Runs store total
    # tokens only, so this is one rate for input and output alike.
    usd_per_million_tokens: float = 0.0
    # A provider on Thomas's own machine (Phase 5, decisions 23, 25 and 26 of
    # docs/build-brief-evals.md). Its runs count against
    # MAX_LOCAL_RUNS_PER_DAY instead of MAX_RUNS_PER_DAY, its tokens against no
    # daily cap, and a run on it never falls back to a cloud rung.
    home: bool = False
    # Read when the model is built, for an address and a tag that differ per machine.
    base_url_env: str | None = None
    model_env: str | None = None
    # None takes MODEL_TIMEOUT_SECONDS.
    timeout_seconds: float | None = None
    max_tokens: int = 2048
    # Ask the endpoint for a JSON object, so the reply always parses.
    json_mode: bool = False


# Chosen per task type by the registry in app/tasks.py, not by MODEL, which
# also names the provider each type falls back to. MODEL_API_KEY is Gemini's
# free tier key, OLLAMA_API_KEY is Ollama's cloud free tier, and
# ANTHROPIC_API_KEY is for Haiku 4.5, which no type uses today.
# LOCAL_MODEL_TOKEN is the bearer Caddy checks in front of Ollama on the home
# PC (local/README.md).
PROVIDERS: dict[str, ProviderConfig] = {
    "gemini": ProviderConfig(
        kind="openai_compatible",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_env="MODEL_API_KEY",
        model="gemini-3.5-flash-lite",
        # The free tier.
        usd_per_million_tokens=0.0,
    ),
    "ollama": ProviderConfig(
        kind="openai_compatible",
        base_url="https://ollama.com/v1",
        api_key_env="OLLAMA_API_KEY",
        model="gpt-oss:120b",
        # The free tier, one request at a time, which the single worker keeps to.
        usd_per_million_tokens=0.0,
    ),
    "local": ProviderConfig(
        kind="openai_compatible",
        base_url=None,
        api_key_env="LOCAL_MODEL_TOKEN",
        # qwen2.5-coder:7b with a 16K context window (local/Modelfile.base).
        model="mercury-local:base",
        home=True,
        base_url_env="LOCAL_MODEL_URL",
        model_env="LOCAL_MODEL",
        # A cold load plus a whole file reply on the 4060. The chore's own
        # heartbeat thread keeps the lease meanwhile.
        timeout_seconds=120.0,
        max_tokens=8192,
        json_mode=True,
    ),
    "haiku": ProviderConfig(
        kind="anthropic",
        base_url=None,
        api_key_env="ANTHROPIC_API_KEY",
        model="claude-haiku-4-5-20251001",
        # Haiku 4.5's output price, charged on every token, so the monthly
        # figure can only overstate the bill.
        usd_per_million_tokens=5.0,
    ),
}

# The providers on Thomas's own machine (decisions 25 and 26 of
# docs/build-brief-evals.md): counted apart, never fallen back from, and kept
# by an advised rerun or an outage retry.
HOME_PROVIDERS = [name for name, provider in PROVIDERS.items() if provider.home]


@dataclass(frozen=True)
class Settings:
    database_url: str
    keepalive_seconds: float
    model: str
    token_budget: int
    max_runs_per_day: int
    worker_id: str
    poll_seconds: float
    verify_timeout_seconds: float
    lease_seconds: float
    model_timeout_seconds: float
    replica_id: str
    voyage_api_key: str | None
    mercury_bearer_token: str | None
    api_base_url: str
    mercury_config_path: str
    embedding_model: str
    check_claim_window_seconds: float = DEFAULT_CHECK_CLAIM_WINDOW_SECONDS
    pagespeed_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    telegram_api_url: str = "https://api.telegram.org"
    daily_tokens_per_provider: int = 500_000
    monthly_budget_usd: float = 5.0
    # Repo chores. The token is contents and pull requests only, on the named
    # repos. GITHUB_CLONE_BASE is a file:// directory in the tests.
    mercury_github_token: str | None = None
    github_api_url: str = "https://api.github.com"
    github_clone_base: str = "https://github.com"
    repo_test_timeout_seconds: float = 600.0
    # The dependency audit's advisory database. No key.
    osv_api_url: str = "https://api.osv.dev"
    # Runs on a home provider a day, apart from max_runs_per_day (decision 25
    # of docs/build-brief-evals.md).
    max_local_runs_per_day: int = 200


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        keepalive_seconds=float(os.environ.get("KEEPALIVE_SECONDS", "15")),
        model=os.environ.get("MODEL", DEFAULT_MODEL),
        token_budget=int(os.environ.get("TOKEN_BUDGET", "50000")),
        max_runs_per_day=int(os.environ.get("MAX_RUNS_PER_DAY", "20")),
        worker_id=os.environ.get("WORKER_ID") or _default_worker_id(),
        poll_seconds=float(os.environ.get("POLL_SECONDS", "1")),
        verify_timeout_seconds=float(os.environ.get("VERIFY_TIMEOUT_SECONDS", "10")),
        lease_seconds=float(os.environ.get("LEASE_SECONDS", DEFAULT_LEASE_SECONDS)),
        model_timeout_seconds=float(os.environ.get("MODEL_TIMEOUT_SECONDS", "25")),
        replica_id=os.environ.get("REPLICA_ID") or socket.gethostname(),
        voyage_api_key=os.environ.get("VOYAGE_API_KEY") or None,
        mercury_bearer_token=os.environ.get("MERCURY_BEARER_TOKEN") or None,
        api_base_url=os.environ.get("API_BASE_URL", "http://localhost:8000"),
        mercury_config_path=os.environ.get("MERCURY_CONFIG_PATH", "/config/mercury.yaml"),
        embedding_model=os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        check_claim_window_seconds=float(
            os.environ.get("CHECK_CLAIM_WINDOW", DEFAULT_CHECK_CLAIM_WINDOW_SECONDS)
        ),
        pagespeed_api_key=os.environ.get("PAGESPEED_API_KEY") or None,
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_webhook_secret=os.environ.get("TELEGRAM_WEBHOOK_SECRET") or None,
        telegram_api_url=os.environ.get("TELEGRAM_API_URL") or "https://api.telegram.org",
        daily_tokens_per_provider=int(os.environ.get("DAILY_TOKENS_PER_PROVIDER", "500000")),
        monthly_budget_usd=float(os.environ.get("MONTHLY_BUDGET_USD", "5")),
        mercury_github_token=os.environ.get("MERCURY_GITHUB_TOKEN") or None,
        github_api_url=os.environ.get("GITHUB_API_URL") or "https://api.github.com",
        github_clone_base=os.environ.get("GITHUB_CLONE_BASE") or "https://github.com",
        repo_test_timeout_seconds=float(os.environ.get("REPO_TEST_TIMEOUT_SECONDS", "600")),
        osv_api_url=os.environ.get("OSV_API_URL") or "https://api.osv.dev",
        max_local_runs_per_day=int(os.environ.get("MAX_LOCAL_RUNS_PER_DAY", "200")),
    )
