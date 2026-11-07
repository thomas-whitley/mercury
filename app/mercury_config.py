"""Loads mercury.yaml: the portfolio's sites, checked hourly for uptime, its
pages, checked weekly with Lighthouse and the broken link crawl, its repos,
which a repo_chore may touch, the one Telegram chat the bot answers and its
timezone, the retention windows the cleanup applies, and each task type's
provider ladder and token budget.

budgets: and providers: were in the first sample and never read. A config
that still has them, or a tasks: entry in the old provider: shape, is
refused at startup rather than left to state something false.
"""

from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

import yaml

from app.cleanup import EVENT_BODIES_DAYS, RUNS_DAYS


@dataclass(frozen=True)
class RepoConfig:
    """owner/name, and the command that runs its tests from the repo root.
    A repo with no test command cannot have a chore, since a chore opens a
    pull request only when the tests pass."""

    name: str
    test_command: str | None = None
    # true in mercury.yaml lets a chore from the API, MCP or n8n start without
    # the Approve button. Meant for the throwaway fixture the evals run on.
    auto_approve: bool = False
    # Seconds the test command may run. None keeps REPO_TEST_TIMEOUT_SECONDS.
    test_timeout_seconds: float | None = None


@dataclass(frozen=True)
class TaskSettings:
    """One entry under tasks: in mercury.yaml. ladder is the providers a run
    of this type tries in order when one fails; budget_tokens None keeps the
    type's own budget from app/tasks.py."""

    ladder: tuple[str, ...]
    budget_tokens: int | None = None


def _as_path_entry(entry: str) -> str:
    """A path entry as the guard reads it. An entry whose last part has no
    extension is a folder and gets a trailing "/", as the spec writes folders
    without one. A misread fails closed: a file with no extension (LICENSE)
    becomes a folder that matches nothing, and a folder with a dot in its name
    is matched exactly, so it allows nothing under it until written with "/"."""
    if entry.endswith("/") or "." in entry.rsplit("/", 1)[-1]:
        return entry
    return entry + "/"


def path_entry_covers(entry: str, path: str) -> bool:
    """A path is covered by an entry it equals, or by a folder entry (one
    ending in "/") it sits under. The diff guard and the diff flags both use
    this, on entries ReviewNotesConfig has already read."""
    return path == entry or (entry.endswith("/") and path.startswith(entry))


@dataclass(frozen=True)
class ReviewNotesConfig:
    """The review_notes: section. Notes left on a site are read from the
    Cloudflare D1 database account_id/database_id and become chores on repo.
    Only a note on one of live_hosts starts one. preview_pattern holds {alias},
    a branch preview's hostname label. reviewer_name is how a pull request
    names the person who left the note. allowed_paths is the diff guard: a
    note chore may write a file that path_entry_covers allows. shared_paths and
    sensitive_files are the guard's flags. allowed_paths and shared_paths are
    read as folders, with a "/" added, unless their last part has an
    extension (see _as_path_entry). daily_cap is the most note chores started in any
    24 hours."""

    enabled: bool
    repo: str
    reviewer_name: str
    live_hosts: tuple[str, ...]
    preview_pattern: str
    account_id: str
    database_id: str
    allowed_paths: tuple[str, ...]
    shared_paths: tuple[str, ...]
    sensitive_files: tuple[str, ...]
    daily_cap: int = 10

    def __post_init__(self) -> None:
        # However the config is built, the guard and the flags read the same entries.
        for name in ("allowed_paths", "shared_paths"):
            entries = tuple(_as_path_entry(entry) for entry in getattr(self, name))
            object.__setattr__(self, name, entries)


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# The YAML names of the rating steps, and the letter each is kept under. The
# letters are the ones the rating buttons send back (app/deals.py).
STEP_KEYS = {"great": "g", "good": "o", "not_for_me": "n", "silence": "silence"}
DEFAULT_STEPS = {"g": 1.0, "o": 0.5, "n": -0.5, "silence": -0.2}
# The parts of a deal's community score and what each is multiplied by
# (app/deal_score.py states the formula).
DEFAULT_COMMUNITY = {"votes_per_hour": 2.0, "net": 1.0, "comments": 0.3, "front_page": 1.0}


@dataclass(frozen=True)
class DealsConfig:
    """The deals: section. Every number is a starting value Thomas can tune.
    roundup_weekday counts Monday as 0, and roundup_time is read in
    telegram.timezone. A rating's weight halves every half_life_days.
    overpriced_step is how far one Overpriced raises its category's bar on
    community score. alert_bar is the total an alert must reach, moved by
    bar_step per /deals more or less."""

    enabled: bool = False
    roundup_weekday: int = 6
    roundup_time: time = time(10, 0)
    roundup_size: int = 10
    size_step: int = 3
    alerts_after: int = 30
    alert_bar: float = 6.0
    bar_step: float = 1.0
    silence_days: int = 7
    half_life_days: float = 90.0
    overpriced_step: float = 0.5
    steps: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_STEPS))
    community: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_COMMUNITY))


@dataclass(frozen=True)
class MercuryConfig:
    sites: tuple[str, ...]
    pages: tuple[str, ...] = ()
    # The one chat the bot answers. None, including the sample's 0, answers no one.
    telegram_chat_id: int | None = None
    repos: tuple[RepoConfig, ...] = ()
    event_bodies_days: int = EVENT_BODIES_DAYS
    # The digest's local time is read in this zone.
    timezone: str = "Australia/Melbourne"
    runs_days: int = RUNS_DAYS
    tasks: dict[str, TaskSettings] = field(default_factory=dict)
    review_notes: ReviewNotesConfig | None = None
    deals: DealsConfig = field(default_factory=DealsConfig)


def load_mercury_config(path: str | Path) -> MercuryConfig:
    """Read mercury.yaml. Raises FileNotFoundError if it is not there,
    which is what a scheduler started with no config mounted should do."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    for gone in ("budgets", "providers"):
        if gone in data:
            raise ValueError(
                f"mercury.yaml: {gone}: is not read. Caps are DAILY_TOKENS_PER_PROVIDER and "
                "MONTHLY_BUDGET_USD in the environment, and providers are PROVIDERS in "
                "app/config.py."
            )
    portfolio = data.get("portfolio") or {}
    telegram = data.get("telegram") or {}
    chat_id = telegram.get("chat_id")
    retention = data.get("retention") or {}
    repos = tuple(_repo(entry) for entry in portfolio.get("repos") or [])
    return MercuryConfig(
        sites=tuple(portfolio.get("sites") or []),
        pages=tuple(portfolio.get("pages") or []),
        telegram_chat_id=int(chat_id) if chat_id else None,
        repos=repos,
        event_bodies_days=int(retention.get("event_bodies_days", EVENT_BODIES_DAYS)),
        runs_days=int(retention.get("runs_days", RUNS_DAYS)),
        timezone=telegram.get("timezone") or "Australia/Melbourne",
        tasks=_tasks(data.get("tasks") or {}),
        review_notes=_review_notes(data.get("review_notes"), repos),
        deals=_deals(data.get("deals")),
    )


def _deals(section: object) -> DealsConfig:
    if section is None:
        return DealsConfig()
    if not isinstance(section, dict):
        raise ValueError("mercury.yaml: deals: must be a mapping")
    defaults = DealsConfig()

    def number(key: str, *, whole: bool = False) -> float:
        value = section.get(key, getattr(defaults, key))
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        if not ok or (whole and not isinstance(value, int)):
            kind = "a positive whole number" if whole else "a positive number"
            raise ValueError(f"mercury.yaml: deals.{key} must be {kind}")
        return value

    day = str(section.get("roundup_day", "sunday")).strip().lower()
    if day not in WEEKDAYS:
        raise ValueError("mercury.yaml: deals.roundup_day must be a day of the week")
    try:
        roundup_time = time.fromisoformat(str(section.get("roundup_time", "10:00")))
    except ValueError:
        raise ValueError("mercury.yaml: deals.roundup_time must be HH:MM") from None

    steps = dict(DEFAULT_STEPS)
    for name, value in (section.get("steps") or {}).items():
        if name not in STEP_KEYS:
            raise ValueError(f"mercury.yaml: deals.steps.{name} is not a rating step")
        # Great and Good raise a weight, Not for me and silence lower it.
        rising = name in ("great", "good")
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not numeric or (value <= 0 if rising else value >= 0):
            sign = "positive" if rising else "negative"
            raise ValueError(f"mercury.yaml: deals.steps.{name} must be a {sign} number")
        steps[STEP_KEYS[name]] = float(value)

    community = dict(DEFAULT_COMMUNITY)
    for name, value in (section.get("community") or {}).items():
        if name not in DEFAULT_COMMUNITY:
            raise ValueError(f"mercury.yaml: deals.community.{name} is not a part of the score")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"mercury.yaml: deals.community.{name} must be 0 or more")
        community[name] = float(value)

    return DealsConfig(
        # Only a YAML boolean true. A quoted "true" keeps deals off.
        enabled=section.get("enabled") is True,
        roundup_weekday=WEEKDAYS.index(day),
        roundup_time=roundup_time,
        roundup_size=int(number("roundup_size", whole=True)),
        size_step=int(number("size_step", whole=True)),
        alerts_after=int(number("alerts_after", whole=True)),
        alert_bar=float(number("alert_bar")),
        bar_step=float(number("bar_step")),
        silence_days=int(number("silence_days", whole=True)),
        half_life_days=float(number("half_life_days")),
        overpriced_step=float(number("overpriced_step")),
        steps=steps,
        community=community,
    )


def _review_notes(section: object, repos: tuple[RepoConfig, ...]) -> ReviewNotesConfig | None:
    if section is None:
        return None
    if not isinstance(section, dict):
        raise ValueError("mercury.yaml: review_notes: must be a mapping")

    def text(key: str) -> str:
        value = section.get(key)
        if value is None or isinstance(value, (bool, dict, list)) or not str(value).strip():
            raise ValueError(f"mercury.yaml: review_notes.{key} is required")
        return str(value).strip()

    def names(key: str, *, required: bool) -> tuple[str, ...]:
        value = section.get(key)
        if value is None and not required:
            return ()
        listed = isinstance(value, list) and all(
            isinstance(item, str) and item.strip() for item in value
        )
        if not listed or (required and not value):
            kind = "a non empty list of strings" if required else "a list of strings"
            raise ValueError(f"mercury.yaml: review_notes.{key} must be {kind}")
        return tuple(item.strip() for item in value)

    repo = text("repo")
    if not any(entry.name == repo and entry.test_command for entry in repos):
        raise ValueError(
            f"mercury.yaml: review_notes.repo {repo!r} must be listed under portfolio.repos "
            "with a test_command"
        )
    preview_pattern = text("preview_pattern")
    if "{alias}" not in preview_pattern:
        raise ValueError("mercury.yaml: review_notes.preview_pattern must contain {alias}")
    daily_cap = section.get("daily_cap", 10)
    if not isinstance(daily_cap, int) or isinstance(daily_cap, bool) or daily_cap < 1:
        raise ValueError("mercury.yaml: review_notes.daily_cap must be a positive whole number")
    return ReviewNotesConfig(
        # Only a YAML boolean true. A quoted "true" keeps notes off.
        enabled=section.get("enabled") is True,
        repo=repo,
        reviewer_name=text("reviewer_name"),
        live_hosts=names("live_hosts", required=True),
        preview_pattern=preview_pattern,
        account_id=text("account_id"),
        database_id=text("database_id"),
        allowed_paths=names("allowed_paths", required=True),
        shared_paths=names("shared_paths", required=False),
        sensitive_files=names("sensitive_files", required=False),
        daily_cap=daily_cap,
    )


def _tasks(section: dict) -> dict[str, TaskSettings]:
    # Imported here because app.tasks imports this module's TaskSettings.
    from app.config import PROVIDERS
    from app.tasks import TASK_TYPES

    tasks = {}
    for name, entry in section.items():
        entry = entry or {}
        if name not in TASK_TYPES:
            raise ValueError(f"mercury.yaml: unknown task type {name!r} under tasks")
        if "provider" in entry:
            raise ValueError(
                f"mercury.yaml: tasks.{name}.provider is no longer read; "
                f"write tasks.{name}.ladder: [first, second] instead"
            )
        ladder = tuple(entry.get("ladder") or ())
        if TASK_TYPES[name].provider is None:
            if ladder:
                raise ValueError(f"mercury.yaml: {name} calls no model, so it takes no ladder")
        elif not ladder:
            raise ValueError(f"mercury.yaml: tasks.{name}.ladder needs at least one provider")
        for provider in ladder:
            if provider not in PROVIDERS:
                raise ValueError(f"mercury.yaml: unknown provider {provider!r} in tasks.{name}")
        budget = entry.get("budget_tokens")
        tasks[name] = TaskSettings(ladder=ladder, budget_tokens=int(budget) if budget else None)
    return tasks


def _repo(entry: str | dict) -> RepoConfig:
    if isinstance(entry, str):
        return RepoConfig(name=entry)
    return RepoConfig(
        name=entry["name"],
        test_command=entry.get("test_command"),
        # Only a YAML boolean true. A quoted "yes" keeps the gate.
        auto_approve=entry.get("auto_approve") is True,
        test_timeout_seconds=(
            float(entry["test_timeout_seconds"]) if "test_timeout_seconds" in entry else None
        ),
    )
