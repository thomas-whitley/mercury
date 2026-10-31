"""The weekly roundup: one quiet message per deal after one heading that
notifies, the best live deals since the last scheduled roundup, sent once
on the first tick after Sunday 10:00 Melbourne time."""

from datetime import UTC, timedelta

import pytest

from app.deals import MAX_DEAL_CHARS, deal_text, roundup_due, send_roundup, window_start
from app.mercury_config import DealsConfig
from app.telegram import TelegramClient
from tests.deal_seed import CHAT, SUNDAY, seed_deal, snapshot

CONFIG = DealsConfig(enabled=True)
TZ = "Australia/Melbourne"


@pytest.fixture
def telegram(fake_telegram):
    return TelegramClient("123:abc", fake_telegram.url)


def sent_nodes(conn) -> list[int]:
    return [row[0] for row in conn.execute("SELECT node_id FROM deal_sends ORDER BY id")]


def test_roundup_sends_a_quiet_message_per_deal_after_one_heading(
    migrated_db, telegram, fake_telegram
):
    for node_id in (1, 2, 3):
        seed_deal(migrated_db, node_id)

    roundup_id = send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG)

    heading, *deals = fake_telegram.sent()
    assert heading["text"] == "Deals this week: 3"
    assert "disable_notification" not in heading
    assert len(deals) == 3
    for message in deals:
        node_id = int(message["text"].rsplit("/node/", 1)[1])
        assert message["disable_notification"] is True
        assert "parse_mode" not in message
        assert message["reply_markup"]["inline_keyboard"] == [
            [
                {"text": "🔥 Great", "callback_data": f"deal:{node_id}:g"},
                {"text": "👍 Good", "callback_data": f"deal:{node_id}:o"},
            ],
            [
                {"text": "👎 Not for me", "callback_data": f"deal:{node_id}:n"},
                {"text": "💸 Overpriced", "callback_data": f"deal:{node_id}:p"},
            ],
        ]
    assert sorted(sent_nodes(migrated_db)) == [1, 2, 3]
    kind = migrated_db.execute("SELECT kind FROM deal_roundups WHERE id = %s", (roundup_id,))
    assert kind.fetchone()[0] == "scheduled"


def test_a_deal_message_shows_title_store_votes_and_link(migrated_db):
    seed_deal(migrated_db, 7, title="Invented SSD $99", pos=40, neg=3)

    assert deal_text(migrated_db, 7) == (
        "Invented SSD $99\nInvented Store · +40 −3\nhttps://www.ozbargain.com.au/node/7"
    )


def test_roundup_takes_at_most_the_size_best_first(migrated_db, telegram, fake_telegram):
    for node_id in range(1, 13):
        seed_deal(migrated_db, node_id, pos=node_id * 5)

    send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG)

    assert sent_nodes(migrated_db) == list(range(12, 2, -1))


def test_roundup_skips_expired_blocked_and_already_sent_deals(migrated_db, telegram, fake_telegram):
    seed_deal(migrated_db, 1)
    seed_deal(migrated_db, 2, flag="expired")
    seed_deal(migrated_db, 3, expires_at=SUNDAY - timedelta(hours=2))
    seed_deal(migrated_db, 4, tags=("tag:blocked",))
    seed_deal(migrated_db, 5)
    migrated_db.execute("INSERT INTO deal_blocks (key) VALUES ('tag:blocked')")
    migrated_db.execute(
        "INSERT INTO deal_sends (node_id, kind, chat_id, message_id, text, score, sent_at) "
        "VALUES (5, 'alert', %s, 1, 'x', '{}', %s)",
        (CHAT, SUNDAY - timedelta(days=1)),
    )

    send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG)

    assert sent_nodes(migrated_db) == [5, 1]


def test_a_deal_that_dropped_off_with_worse_votes_is_left_out(migrated_db, telegram):
    newest = SUNDAY - timedelta(hours=1)
    earlier = SUNDAY - timedelta(hours=3)
    seed_deal(migrated_db, 1, seen_at=newest)
    # Off both feeds since, and its positive share fell from 0.96 to 0.63.
    seed_deal(migrated_db, 2, pos=50, neg=2, seen_at=earlier)
    snapshot(migrated_db, 2, SUNDAY - timedelta(hours=2), 50, 30)
    # Off both feeds too, with its share unchanged.
    seed_deal(migrated_db, 3, pos=50, neg=2, seen_at=earlier)

    send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG)

    assert sorted(sent_nodes(migrated_db)) == [1, 3]


def test_due_on_sunday_at_ten_melbourne_and_only_once(migrated_db, telegram):
    seed_deal(migrated_db, 1)
    assert not roundup_due(migrated_db, SUNDAY - timedelta(minutes=1), TZ, CONFIG)
    assert roundup_due(migrated_db, SUNDAY, TZ, CONFIG)

    send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY + timedelta(minutes=5), CONFIG)

    assert not roundup_due(migrated_db, SUNDAY + timedelta(hours=1), TZ, CONFIG)
    assert roundup_due(migrated_db, SUNDAY + timedelta(days=7), TZ, CONFIG)


def test_paused_is_never_due(migrated_db):
    seed_deal(migrated_db, 1)
    migrated_db.execute("UPDATE deal_state SET paused = true")

    assert not roundup_due(migrated_db, SUNDAY, TZ, CONFIG)


def test_a_pc_off_on_sunday_sends_on_the_first_tick_after(migrated_db, telegram):
    last_week = SUNDAY - timedelta(days=7) + timedelta(minutes=5)
    migrated_db.execute(
        "INSERT INTO deal_roundups (kind, sent_at) VALUES ('scheduled', %s)", (last_week,)
    )
    wednesday = SUNDAY - timedelta(days=4)
    seed_deal(migrated_db, 1, first_seen=wednesday - timedelta(hours=3), seen_at=wednesday)
    send_roundup(migrated_db, telegram, CHAT, "now", wednesday, CONFIG)
    monday = SUNDAY + timedelta(hours=22)
    seed_deal(migrated_db, 2, first_seen=SUNDAY, seen_at=monday - timedelta(hours=1))

    assert roundup_due(migrated_db, monday, TZ, CONFIG)
    assert window_start(migrated_db, monday) == last_week
    send_roundup(migrated_db, telegram, CHAT, "scheduled", monday, CONFIG)
    assert sent_nodes(migrated_db) == [1, 2]
    assert not roundup_due(migrated_db, monday + timedelta(hours=1), TZ, CONFIG)


def test_a_now_roundup_does_not_move_sunday(migrated_db, telegram):
    seed_deal(migrated_db, 1)
    send_roundup(migrated_db, telegram, CHAT, "now", SUNDAY - timedelta(days=1), CONFIG)

    assert roundup_due(migrated_db, SUNDAY, TZ, CONFIG)


def test_the_first_window_is_seven_days(migrated_db):
    assert window_start(migrated_db, SUNDAY) == SUNDAY - timedelta(days=7)


def test_a_failed_heading_records_nothing(migrated_db, telegram, fake_telegram):
    seed_deal(migrated_db, 1)
    fake_telegram.fail_next = {"error_code": 500, "description": "down"}

    assert send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG) is None

    assert migrated_db.execute("SELECT count(*) FROM deal_roundups").fetchone()[0] == 0
    assert sent_nodes(migrated_db) == []
    assert roundup_due(migrated_db, SUNDAY + timedelta(hours=1), TZ, CONFIG)


def test_a_failed_deal_message_skips_only_that_deal(migrated_db, telegram, fake_telegram):
    for node_id in (1, 2, 3):
        seed_deal(migrated_db, node_id, pos=node_id * 10)
    fake_telegram.fail_sends = {3}

    send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG)

    assert sent_nodes(migrated_db) == [3, 1]
    assert not roundup_due(migrated_db, SUNDAY + timedelta(hours=1), TZ, CONFIG)


def test_an_empty_week_sends_one_line(migrated_db, telegram, fake_telegram):
    send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG)

    assert [m["text"] for m in fake_telegram.sent()] == ["No new deals cleared the bar this week."]


def test_a_long_title_stays_under_the_limit(migrated_db):
    seed_deal(migrated_db, 8, title="x" * 5000)

    text = deal_text(migrated_db, 8)

    assert len(text) <= MAX_DEAL_CHARS
    assert text.endswith("https://www.ozbargain.com.au/node/8")


def test_a_roundup_creates_no_run(migrated_db, telegram):
    seed_deal(migrated_db, 1)

    send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG)

    assert migrated_db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_size_follows_the_offset_and_never_drops_below_one(migrated_db, telegram):
    for node_id in range(1, 6):
        seed_deal(migrated_db, node_id, pos=node_id * 5)
    migrated_db.execute("UPDATE deal_state SET size_offset = -9")

    send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG)

    assert sent_nodes(migrated_db) == [5]


def test_not_due_for_a_sunday_before_the_first_deal_was_seen(migrated_db):
    assert not roundup_due(migrated_db, SUNDAY, TZ, CONFIG)
    seed_deal(migrated_db, 1, first_seen=SUNDAY + timedelta(hours=1))

    assert not roundup_due(migrated_db, SUNDAY + timedelta(hours=2), TZ, CONFIG)
    assert roundup_due(migrated_db, SUNDAY + timedelta(days=7), TZ, CONFIG)


def test_times_are_compared_in_utc(migrated_db):
    seed_deal(migrated_db, 1)
    # The due time is a Melbourne wall clock time; now may arrive in UTC.
    assert roundup_due(migrated_db, SUNDAY.astimezone(UTC), TZ, CONFIG)


def test_a_deal_that_turned_targeted_is_left_out(migrated_db, telegram):
    seed_deal(migrated_db, 1)
    seed_deal(migrated_db, 2, flag="targeted")

    send_roundup(migrated_db, telegram, CHAT, "scheduled", SUNDAY, CONFIG)

    assert sent_nodes(migrated_db) == [1]
