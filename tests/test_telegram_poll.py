"""The inbound half on the home PC. Nothing on the internet reaches it, so
the poller asks Telegram for updates and posts each one to the api's own
/telegram with the webhook's secret, and the webhook handles it as before.
"""

import pytest
import yaml

from app.schedule_state import is_suspended, record_failure
from app.telegram import TelegramClient
from app.telegram_poll import poll_once
from tests.test_telegram_webhook import CHAT, SECRET, SITE, replies, update

SCHEDULE = f"site_uptime:{SITE}"


@pytest.fixture
def bot(start_server, fake_telegram, monkeypatch, tmp_path):
    config = tmp_path / "mercury.yaml"
    config.write_text(yaml.dump({"telegram": {"chat_id": CHAT}, "portfolio": {"sites": [SITE]}}))
    monkeypatch.setenv("MERCURY_CONFIG_PATH", str(config))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_API_URL", fake_telegram.url)
    return start_server()


def client(fake_telegram) -> TelegramClient:
    return TelegramClient("123:abc", fake_telegram.url)


def numbered(update_id: int, text: str) -> dict:
    return {**update(text), "update_id": update_id}


def test_a_polled_command_reaches_the_bot(bot, fake_telegram, migrated_db):
    for _ in range(3):
        record_failure(migrated_db, SCHEDULE)
    fake_telegram.updates.append(numbered(7, f"/resume {SITE}"))

    offset = poll_once(client(fake_telegram), None, bot, SECRET, timeout=0)

    assert offset == 8
    assert is_suspended(migrated_db, SCHEDULE) is False
    assert replies(fake_telegram) == [f"Resumed {SITE}."]


def test_the_next_poll_asks_only_for_newer_updates(bot, fake_telegram, migrated_db):
    fake_telegram.updates.append(numbered(7, "/status"))

    offset = poll_once(client(fake_telegram), None, bot, SECRET, timeout=0)
    poll_once(client(fake_telegram), offset, bot, SECRET, timeout=0)

    [first, second] = fake_telegram.sent("getUpdates")
    assert "offset" not in first
    assert second["offset"] == 8
    assert len(replies(fake_telegram)) == 1


def test_an_update_the_api_did_not_take_is_fetched_again(fake_telegram):
    fake_telegram.updates.append(numbered(7, "/status"))
    unreachable = "http://127.0.0.1:1"

    offset = poll_once(client(fake_telegram), None, unreachable, SECRET, timeout=0, retry_seconds=0)

    assert offset is None
