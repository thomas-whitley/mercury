"""Instant alerts: off until 30 deals are rated with a button, then a deal
seen on this tick clearing the bar goes on its own, once, and notifies."""

from datetime import timedelta

import pytest

from app.deals import alert_bar, send_alerts, send_roundup
from app.mercury_config import DealsConfig
from app.telegram import TelegramClient
from tests.deal_seed import CHAT, SUNDAY, seed_deal, snapshot

CONFIG = DealsConfig(enabled=True)
TICK = SUNDAY - timedelta(hours=1)


@pytest.fixture
def telegram(fake_telegram):
    return TelegramClient("123:abc", fake_telegram.url)


def rate_deals(conn, count: int, *, first: int = 1000) -> None:
    """count distinct deals rated Great with a button, in a category of their
    own and below any bar, so they neither alert nor change the target's taste."""
    for node_id in range(first, first + count):
        seed_deal(
            conn,
            node_id,
            pos=1,
            category="cat:other",
            store=None,
            seen_at=TICK - timedelta(hours=5),
        )
        conn.execute(
            "INSERT INTO deal_ratings VALUES (%s, 'g', false, %s) "
            "ON CONFLICT (node_id) DO UPDATE SET rating = 'o'",
            (node_id, SUNDAY),
        )


def strong_deal(conn, node_id: int = 1, pos: int = 400) -> None:
    seed_deal(conn, node_id, pos=pos, first_seen=TICK - timedelta(hours=1), seen_at=TICK)


def test_alerts_stay_off_before_thirty_ratings_and_log_would_be_alerts(
    migrated_db, telegram, fake_telegram
):
    rate_deals(migrated_db, 29)
    strong_deal(migrated_db)

    assert send_alerts(migrated_db, telegram, CHAT, SUNDAY, CONFIG) == []

    assert fake_telegram.sent() == []
    rows = migrated_db.execute("SELECT node_id, first_at FROM deal_would_alert").fetchall()
    assert rows == [(1, SUNDAY)]


def test_alerts_switch_on_at_thirty_distinct_deals(migrated_db, telegram, fake_telegram):
    rate_deals(migrated_db, 29)
    # The same deal pressed again is still one deal.
    migrated_db.execute("UPDATE deal_ratings SET rating = 'o' WHERE node_id = 1000")
    strong_deal(migrated_db)
    assert send_alerts(migrated_db, telegram, CHAT, SUNDAY, CONFIG) == []

    rate_deals(migrated_db, 1, first=2000)
    later = SUNDAY + timedelta(hours=1)
    seed_deal(migrated_db, 2, pos=400, first_seen=later - timedelta(hours=1), seen_at=later)
    # Deal 1 is still in the feed on the new tick.
    snapshot(migrated_db, 1, later, 450)
    migrated_db.execute("UPDATE deals SET last_seen_at = %s WHERE node_id = 1", (later,))

    # Deal 1 first cleared the bar while alerts were off, so it is not sent now.
    assert send_alerts(migrated_db, telegram, CHAT, later, CONFIG) == [2]
    [alert] = fake_telegram.sent()
    assert "disable_notification" not in alert
    assert alert["text"].endswith("/node/2")
    assert len(alert["reply_markup"]["inline_keyboard"]) == 2
    kind = migrated_db.execute("SELECT kind FROM deal_sends WHERE node_id = 2").fetchone()[0]
    assert kind == "alert"


def test_a_deal_below_the_bar_is_not_alerted(migrated_db, telegram, fake_telegram):
    rate_deals(migrated_db, 30)
    strong_deal(migrated_db, pos=3)

    assert send_alerts(migrated_db, telegram, CHAT, SUNDAY, CONFIG) == []


def test_a_deal_not_seen_on_this_tick_is_not_alerted(migrated_db, telegram):
    rate_deals(migrated_db, 30)
    strong_deal(migrated_db, 1)
    seed_deal(migrated_db, 2, pos=10, seen_at=TICK + timedelta(hours=1))

    assert send_alerts(migrated_db, telegram, CHAT, SUNDAY, CONFIG) == []


def test_an_alerted_deal_is_not_in_the_roundup(migrated_db, telegram):
    rate_deals(migrated_db, 30)
    strong_deal(migrated_db)
    send_alerts(migrated_db, telegram, CHAT, SUNDAY, CONFIG)

    send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG)

    kinds = migrated_db.execute("SELECT kind FROM deal_sends WHERE node_id = 1").fetchall()
    assert kinds == [("alert",)]


def test_an_alert_is_sent_once(migrated_db, telegram, fake_telegram):
    rate_deals(migrated_db, 30)
    strong_deal(migrated_db)

    send_alerts(migrated_db, telegram, CHAT, SUNDAY, CONFIG)
    send_alerts(migrated_db, telegram, CHAT, SUNDAY + timedelta(minutes=1), CONFIG)

    assert len(fake_telegram.sent()) == 1


def test_paused_sends_no_alert(migrated_db, telegram, fake_telegram):
    rate_deals(migrated_db, 30)
    strong_deal(migrated_db)
    migrated_db.execute("UPDATE deal_state SET paused = true")

    assert send_alerts(migrated_db, telegram, CHAT, SUNDAY, CONFIG) == []


def test_the_bar_moves_one_step_per_offset(migrated_db):
    migrated_db.execute("UPDATE deal_state SET bar_offset = 2")

    assert alert_bar(migrated_db, CONFIG) == CONFIG.alert_bar + 2 * CONFIG.bar_step
