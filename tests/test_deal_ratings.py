"""Ratings from the four buttons, edited into the deal's own message, and a
week of silence counted as a weak Not for me."""

from datetime import timedelta

import httpx2
import pytest
import yaml

from app.deals import button_ratings, record_silence
from app.mercury_config import DealsConfig
from tests.deal_seed import CHAT, SUNDAY, record_send, seed_deal

SECRET = "webhook-secret"
CONFIG = DealsConfig(enabled=True)


@pytest.fixture
def bot(start_server, fake_telegram, monkeypatch, tmp_path):
    config = tmp_path / "mercury.yaml"
    config.write_text(yaml.dump({"telegram": {"chat_id": CHAT}}))
    monkeypatch.setenv("MERCURY_CONFIG_PATH", str(config))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_API_URL", fake_telegram.url)
    return start_server()


def press(base_url: str, data: str, chat_id: int = CHAT) -> None:
    body = {
        "update_id": 1,
        "callback_query": {
            "id": "cb1",
            "data": data,
            "message": {"message_id": 5, "chat": {"id": chat_id}},
        },
    }
    response = httpx2.post(
        f"{base_url}/telegram", json=body, headers={"X-Telegram-Bot-Api-Secret-Token": SECRET}
    )
    assert response.status_code == 200


def ratings(conn) -> list[tuple]:
    query = "SELECT node_id, rating, silent FROM deal_ratings ORDER BY node_id"
    return conn.execute(query).fetchall()


def sent_deal(conn, node_id=1, sent_at=SUNDAY):
    seed_deal(conn, node_id)
    record_send(conn, node_id, sent_at, text=f"Invented deal {node_id}\nhttps://x/node/{node_id}")


def test_a_press_records_the_rating_and_edits_in_place_keeping_buttons(
    bot, fake_telegram, migrated_db
):
    sent_deal(migrated_db)

    press(bot, "deal:1:g")

    assert ratings(migrated_db) == [(1, "g", False)]
    [edit] = fake_telegram.sent("editMessageText")
    assert edit["message_id"] == 5
    assert edit["text"] == "Invented deal 1\nhttps://x/node/1\n\nRated: 🔥 Great"
    keys = [key["callback_data"] for row in edit["reply_markup"]["inline_keyboard"] for key in row]
    assert keys == ["deal:1:g", "deal:1:o", "deal:1:n", "deal:1:p"]
    [answer] = fake_telegram.sent("answerCallbackQuery")
    assert answer["text"] == "Saved: 🔥 Great"


def test_a_later_press_replaces_the_rating(bot, fake_telegram, migrated_db):
    sent_deal(migrated_db)

    press(bot, "deal:1:g")
    press(bot, "deal:1:p")

    assert ratings(migrated_db) == [(1, "p", False)]
    assert fake_telegram.sent("editMessageText")[-1]["text"].endswith("Rated: 💸 Overpriced")


def test_a_press_from_another_chat_changes_nothing(bot, fake_telegram, migrated_db):
    sent_deal(migrated_db)

    press(bot, "deal:1:g", chat_id=99)

    assert ratings(migrated_db) == []
    assert fake_telegram.calls == []


def test_a_press_on_a_deal_never_sent_changes_nothing(bot, fake_telegram, migrated_db):
    seed_deal(migrated_db, 2)

    press(bot, "deal:2:g")

    assert ratings(migrated_db) == []
    assert fake_telegram.sent("editMessageText") == []


def test_a_malformed_press_changes_nothing(bot, fake_telegram, migrated_db):
    sent_deal(migrated_db)

    press(bot, "deal:1:x")

    assert ratings(migrated_db) == []


def test_silence_counts_after_seven_days_for_a_live_deal_only(migrated_db):
    now = SUNDAY + timedelta(days=7)
    sent_deal(migrated_db, 1, sent_at=SUNDAY + timedelta(days=1))  # six days ago
    sent_deal(migrated_db, 2, sent_at=SUNDAY)  # seven days ago, live
    seed_deal(migrated_db, 3, flag="expired")
    record_send(migrated_db, 3, SUNDAY)
    sent_deal(migrated_db, 4, sent_at=SUNDAY)
    migrated_db.execute("INSERT INTO deal_ratings VALUES (4, 'g', false, %s)", (SUNDAY,))

    assert record_silence(migrated_db, now, CONFIG) == 1

    assert ratings(migrated_db) == [(2, "n", True), (4, "g", False)]
    assert record_silence(migrated_db, now, CONFIG) == 0


def test_an_unrated_alert_counts_as_silence_too(migrated_db):
    seed_deal(migrated_db, 1)
    record_send(migrated_db, 1, SUNDAY, kind="alert")

    assert record_silence(migrated_db, SUNDAY + timedelta(days=7), CONFIG) == 1


def test_silence_never_counts_toward_alerts(migrated_db):
    for node_id in range(1, 32):
        sent_deal(migrated_db, node_id)

    record_silence(migrated_db, SUNDAY + timedelta(days=8), CONFIG)

    assert button_ratings(migrated_db) == 0


def test_a_press_after_silence_replaces_it(bot, fake_telegram, migrated_db):
    sent_deal(migrated_db)
    record_silence(migrated_db, SUNDAY + timedelta(days=8), CONFIG)

    press(bot, "deal:1:g")

    assert ratings(migrated_db) == [(1, "g", False)]
    assert button_ratings(migrated_db) == 1


def test_the_rating_stays_out_of_the_log(migrated_db, clean_db, caplog):
    from datetime import UTC, datetime

    from app.deal_commands import on_deal_button

    sent_deal(migrated_db)
    caplog.set_level("INFO", logger="agent_runs.deals")

    on_deal_button(clean_db, None, CHAT, "cb1", "deal:1:p", datetime.now(UTC))

    assert ratings(migrated_db) == [(1, "p", False)]
    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["deal 1 rated"]
