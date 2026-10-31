"""Loads the parts of mercury.yaml that something reads: the portfolio, the
Telegram chat and the retention windows.

tasks: is parsed into each type's provider ladder and budget. budgets: and
providers: were never read, so a config that still has them is refused
rather than left to say something false.
"""

import re
from datetime import time

import pytest
import yaml

from app.mercury_config import ReviewNotesConfig, TaskSettings, load_mercury_config


def test_load_mercury_config_reads_the_site_list(tmp_path):
    config_file = tmp_path / "mercury.yaml"
    config_file.write_text(
        yaml.dump({"portfolio": {"sites": ["https://a.example", "https://b.example"]}})
    )

    config = load_mercury_config(config_file)

    assert config.sites == ("https://a.example", "https://b.example")


def test_load_mercury_config_defaults_to_no_sites_when_the_section_is_missing(tmp_path):
    config_file = tmp_path / "mercury.yaml"
    config_file.write_text(yaml.dump({"telegram": {"chat_id": 1}}))

    config = load_mercury_config(config_file)

    assert config.sites == ()


def test_load_mercury_config_raises_when_the_file_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_mercury_config(tmp_path / "does-not-exist.yaml")


def test_load_mercury_config_reads_the_pages_for_weekly_browser_checks(tmp_path):
    config_file = tmp_path / "mercury.yaml"
    config_file.write_text(
        yaml.dump(
            {"portfolio": {"sites": ["https://a.example/health"], "pages": ["https://a.example/"]}}
        )
    )

    config = load_mercury_config(config_file)

    assert config.pages == ("https://a.example/",)


def test_load_mercury_config_defaults_to_no_pages(tmp_path):
    config_file = tmp_path / "mercury.yaml"
    config_file.write_text(yaml.dump({"portfolio": {"sites": ["https://a.example"]}}))

    assert load_mercury_config(config_file).pages == ()


def test_load_mercury_config_reads_the_telegram_chat_id(tmp_path):
    config_file = tmp_path / "mercury.yaml"
    config_file.write_text(yaml.dump({"telegram": {"chat_id": 123456789}}))

    assert load_mercury_config(config_file).telegram_chat_id == 123456789


@pytest.mark.parametrize("telegram", [{"chat_id": 0}, {}, None])
def test_a_zero_or_missing_chat_id_allows_no_chat(tmp_path, telegram):
    config_file = tmp_path / "mercury.yaml"
    config_file.write_text(yaml.dump({"telegram": telegram}))

    assert load_mercury_config(config_file).telegram_chat_id is None


def test_load_mercury_config_reads_the_retention_windows(tmp_path):
    config_file = tmp_path / "mercury.yaml"
    config_file.write_text(yaml.dump({"retention": {"event_bodies_days": 14, "runs_days": 90}}))

    config = load_mercury_config(config_file)

    assert (config.event_bodies_days, config.runs_days) == (14, 90)


def test_the_retention_windows_default_to_30_days_and_a_year(tmp_path):
    config_file = tmp_path / "mercury.yaml"
    config_file.write_text(yaml.dump({"portfolio": {}}))

    config = load_mercury_config(config_file)

    assert (config.event_bodies_days, config.runs_days) == (30, 365)


def test_load_mercury_config_reads_the_timezone_and_defaults_to_melbourne(tmp_path):
    config_file = tmp_path / "mercury.yaml"
    config_file.write_text(yaml.dump({"telegram": {"timezone": "Europe/London"}}))
    default_file = tmp_path / "default.yaml"
    default_file.write_text(yaml.dump({"portfolio": {}}))

    assert load_mercury_config(config_file).timezone == "Europe/London"
    assert load_mercury_config(default_file).timezone == "Australia/Melbourne"


def write(tmp_path, text: str):
    path = tmp_path / "mercury.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_type_reads_its_ladder_and_budget(tmp_path):
    config = load_mercury_config(
        write(
            tmp_path,
            "tasks:\n  repo_chore:\n    ladder: [ollama, gemini]\n    budget_tokens: 40000\n",
        )
    )
    assert config.tasks["repo_chore"] == TaskSettings(
        ladder=("ollama", "gemini"), budget_tokens=40000
    )


def test_a_type_with_no_tasks_entry_is_absent(tmp_path):
    assert load_mercury_config(write(tmp_path, "portfolio: {}\n")).tasks == {}


@pytest.mark.parametrize(
    "text, words",
    [
        ("tasks:\n  repo_chore:\n    provider: haiku\n", "tasks.repo_chore.provider"),
        ("tasks:\n  repo_chore:\n    ladder: [nobody]\n", "unknown provider 'nobody'"),
        ("tasks:\n  homework:\n    ladder: [gemini]\n", "unknown task type 'homework'"),
        ("tasks:\n  site_check:\n    ladder: [gemini]\n", "site_check calls no model"),
        ("tasks:\n  repo_chore:\n    ladder: []\n", "needs at least one provider"),
        ("budgets:\n  per_month_usd: 5\n", "budgets"),
        ("providers:\n  gemini: {}\n", "providers"),
    ],
)
def test_a_config_mercury_would_misread_stops_it_at_startup(tmp_path, text, words):
    with pytest.raises(ValueError, match=re.escape(words)):
        load_mercury_config(write(tmp_path, text))


def test_a_repo_may_set_its_own_test_timeout(tmp_path):
    config = load_mercury_config(
        write(
            tmp_path,
            "portfolio:\n  repos:\n"
            "    - name: o/slow\n      test_command: npm test\n      test_timeout_seconds: 900\n"
            "    - name: o/fast\n      test_command: npm test\n",
        )
    )
    slow, fast = config.repos
    assert slow.test_timeout_seconds == 900.0
    assert fast.test_timeout_seconds is None


REVIEW_NOTES_YAML = """portfolio:
  repos:
    - name: owner/site
      test_command: npm test
review_notes:
  enabled: true
  repo: owner/site
  reviewer_name: Reviewer
  live_hosts: [live.example.com]
  preview_pattern: "https://{alias}-site.sub.workers.dev"
  account_id: "0000"
  database_id: "0000-0000"
  allowed_paths: [src/pages, public]
  shared_paths: [src/site.config.ts]
  sensitive_files: [src/site.config.ts]
"""


def test_review_notes_loads(tmp_path):
    config = load_mercury_config(write(tmp_path, REVIEW_NOTES_YAML))

    assert config.review_notes == ReviewNotesConfig(
        enabled=True,
        repo="owner/site",
        reviewer_name="Reviewer",
        live_hosts=("live.example.com",),
        preview_pattern="https://{alias}-site.sub.workers.dev",
        account_id="0000",
        database_id="0000-0000",
        allowed_paths=("src/pages/", "public/"),
        shared_paths=("src/site.config.ts",),
        sensitive_files=("src/site.config.ts",),
        daily_cap=10,
    )


def test_no_review_notes_section_means_none(tmp_path):
    assert load_mercury_config(write(tmp_path, "portfolio: {}\n")).review_notes is None


def test_review_notes_is_enabled_only_by_a_yaml_true(tmp_path):
    text = REVIEW_NOTES_YAML.replace("enabled: true", 'enabled: "true"')

    assert load_mercury_config(write(tmp_path, text)).review_notes.enabled is False


def test_review_notes_with_an_unknown_repo_is_refused(tmp_path):
    text = REVIEW_NOTES_YAML.replace("repo: owner/site", "repo: owner/other")

    with pytest.raises(ValueError, match="review_notes.repo"):
        load_mercury_config(write(tmp_path, text))


def test_review_notes_on_a_repo_with_no_test_command_is_refused(tmp_path):
    text = REVIEW_NOTES_YAML.replace("      test_command: npm test\n", "")

    with pytest.raises(ValueError, match="test_command"):
        load_mercury_config(write(tmp_path, text))


@pytest.mark.parametrize(
    "old, new, words",
    [
        ('  database_id: "0000-0000"\n', "", "review_notes.database_id"),
        ("  live_hosts: [live.example.com]\n", "  live_hosts: []\n", "review_notes.live_hosts"),
        ("{alias}-site", "site", "{alias}"),
        ("  allowed_paths: [src/pages, public]\n", "", "review_notes.allowed_paths"),
        (
            "  sensitive_files: [src/site.config.ts]\n",
            "  sensitive_files: oops\n",
            "sensitive_files",
        ),
        ("  enabled: true\n", "  enabled: true\n  daily_cap: 0\n", "review_notes.daily_cap"),
        ("  enabled: true\n", "  enabled: true\n  daily_cap: ten\n", "review_notes.daily_cap"),
        ("  enabled: true\n", "  enabled: true\n  daily_cap: true\n", "review_notes.daily_cap"),
    ],
)
def test_a_bad_review_notes_section_stops_startup(tmp_path, old, new, words):
    text = REVIEW_NOTES_YAML.replace(old, new)
    assert text != REVIEW_NOTES_YAML

    with pytest.raises(ValueError, match=re.escape(words)):
        load_mercury_config(write(tmp_path, text))


def test_a_folder_entry_without_a_slash_allows_the_files_under_it(tmp_path):
    from app.repo_chore import _outside_paths

    allowed = load_mercury_config(write(tmp_path, REVIEW_NOTES_YAML)).review_notes.allowed_paths

    assert _outside_paths({"src/pages/about.astro": "", "public/a/b.png": ""}, allowed) == []
    assert _outside_paths({"src/pagesx/a.astro": ""}, allowed) == ["src/pagesx/a.astro"]


def test_path_entries_are_read_as_folders_unless_their_last_part_has_an_extension(tmp_path):
    text = REVIEW_NOTES_YAML.replace(
        "  shared_paths: [src/site.config.ts]\n",
        "  shared_paths: [src/site.config.ts, src/layouts, src/styles/]\n",
    ).replace("allowed_paths: [src/pages, public]", "allowed_paths: [src/pages, LICENSE]")

    notes = load_mercury_config(write(tmp_path, text)).review_notes

    assert notes.shared_paths == ("src/site.config.ts", "src/layouts/", "src/styles/")
    # A file with no extension reads as a folder, so it is refused, never widened.
    assert notes.allowed_paths == ("src/pages/", "LICENSE/")


def test_the_diff_flags_and_the_path_guard_read_an_entry_the_same_way(tmp_path):
    from app.repo_chore import _allowed
    from app.review_notes import _under

    notes = load_mercury_config(write(tmp_path, REVIEW_NOTES_YAML)).review_notes
    for path in ("src/pages", "src/pages/a.astro", "src/pagesx/a", "public", "public/x", "x"):
        for entry in notes.allowed_paths + notes.shared_paths:
            assert _under(path, entry) == _allowed(path, (entry,)), (path, entry)


def _deals_config(tmp_path, deals: dict | None):
    path = tmp_path / "mercury.yaml"
    path.write_text(yaml.dump({} if deals is None else {"deals": deals}))
    return load_mercury_config(path).deals


def test_deals_default_to_off_with_the_starting_values(tmp_path):
    deals = _deals_config(tmp_path, None)

    assert deals.enabled is False
    assert deals.roundup_size == 10
    assert deals.roundup_weekday == 6
    assert deals.roundup_time == time(10, 0)
    assert deals.alerts_after == 30
    assert deals.silence_days == 7
    assert deals.size_step == 3
    assert deals.steps == {"g": 1.0, "o": 0.5, "n": -0.5, "silence": -0.2}


def test_deals_reads_every_value(tmp_path):
    deals = _deals_config(
        tmp_path,
        {
            "enabled": True,
            "roundup_day": "saturday",
            "roundup_time": "09:30",
            "roundup_size": 5,
            "steps": {"great": 2, "good": 1, "not_for_me": -1, "silence": -0.1},
            "community": {"front_page": 2},
        },
    )

    assert deals.enabled is True
    assert deals.roundup_weekday == 5
    assert deals.roundup_time == time(9, 30)
    assert deals.roundup_size == 5
    assert deals.steps == {"g": 2.0, "o": 1.0, "n": -1.0, "silence": -0.1}
    assert deals.community["front_page"] == 2.0
    assert deals.community["votes_per_hour"] == 2.0


def test_deals_reads_a_quoted_true_as_off(tmp_path):
    assert _deals_config(tmp_path, {"enabled": "true"}).enabled is False


@pytest.mark.parametrize(
    ("deals", "key"),
    [
        ({"roundup_day": "someday"}, "deals.roundup_day"),
        ({"roundup_time": "25:00"}, "deals.roundup_time"),
        ({"roundup_size": 0}, "deals.roundup_size"),
        ({"steps": {"great": -1}}, "deals.steps.great"),
        ({"steps": {"silence": 0.5}}, "deals.steps.silence"),
        ({"community": {"likes": 1}}, "deals.community.likes"),
    ],
)
def test_deals_refuses_bad_values(tmp_path, deals, key):
    with pytest.raises(ValueError, match=re.escape(key)):
        _deals_config(tmp_path, deals)
