"""/deals from the allowed chat steers the deal finder: roundup size and
alert bar, blocking a category, store or tag, why a deal arrived, a roundup
now, and pausing everything."""

from datetime import UTC, datetime, timedelta

import httpx2
import pytest
import yaml

from tests.deal_seed import CHAT, record_send, seed_deal

SECRET = "webhook-secret"


def start_bot(start_server, fake_telegram, monkeypatch, tmp_path, *, enabled=True):
    config = tmp_path / "mercury.yaml"
    config.write_text(yaml.dump({"telegram": {"chat_id": CHAT}, "deals": {"enabled": enabled}}))
    monkeypatch.setenv("MERCURY_CONFIG_PATH", str(config))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_API_URL", fake_telegram.url)
    return start_server()


@pytest.fixture
def bot(start_server, fake_telegram, monkeypatch, tmp_path):
    return start_bot(start_server, fake_telegram, monkeypatch, tmp_path)


def say(base_url: str, text: str, chat_id: int = CHAT) -> None:
    body = {
        "update_id": 1,
        "message": {"message_id": 10, "chat": {"id": chat_id, "type": "private"}, "text": text},
    }
    response = httpx2.post(
        f"{base_url}/telegram", json=body, headers={"X-Telegram-Bot-Api-Secret-Token": SECRET}
    )
    assert response.status_code == 200


def last_reply(fake_telegram) -> str:
    return fake_telegram.sent()[-1]["text"]


def fresh_deal(conn, node_id: int, **extra) -> None:
    """A deal seen just now, since /deals reads the real clock."""
    now = datetime.now(UTC)
    seed_deal(
        conn,
        node_id,
        first_seen=now - timedelta(hours=1),
        seen_at=now - timedelta(minutes=5),
        **extra,
    )


def name(conn, key: str, text: str) -> None:
    conn.execute("INSERT INTO deal_feature_names VALUES (%s, %s)", (key, text))


def test_more_and_less_move_size_by_three_and_the_bar_by_one_step(bot, fake_telegram, migrated_db):
    say(bot, "/deals more")
    assert last_reply(fake_telegram) == "Roundup size 13, alert bar 5.0."

    say(bot, "/deals less")
    say(bot, "/deals less")
    assert last_reply(fake_telegram) == "Roundup size 7, alert bar 7.0."


def test_less_never_takes_the_size_below_one(bot, fake_telegram, migrated_db):
    for _ in range(5):
        say(bot, "/deals less")

    assert last_reply(fake_telegram) == "Roundup size 1, alert bar 11.0."
    say(bot, "/deals more")
    assert last_reply(fake_telegram) == "Roundup size 4, alert bar 10.0."


def test_never_blocks_every_kind_that_matches_and_names_them(bot, fake_telegram, migrated_db):
    name(migrated_db, "cat:computing", "Computing")
    name(migrated_db, "tag:computing", "computing")
    name(migrated_db, "store:amazon-au", "Amazon AU")

    say(bot, "/deals never COMPUTING")

    assert last_reply(fake_telegram) == "Blocked: Computing (category), computing (tag)."
    blocked = [row[0] for row in migrated_db.execute("SELECT key FROM deal_blocks ORDER BY key")]
    assert blocked == ["cat:computing", "tag:computing"]


def test_never_matches_a_slug(bot, fake_telegram, migrated_db):
    name(migrated_db, "store:amazon-au", "Amazon AU")

    say(bot, "/deals never amazon-au")

    assert last_reply(fake_telegram) == "Blocked: Amazon AU (store)."


def test_never_with_no_match_lists_the_closest_and_records_nothing(bot, fake_telegram, migrated_db):
    name(migrated_db, "cat:computing", "Computing")
    name(migrated_db, "cat:gaming", "Gaming")

    say(bot, "/deals never computng")

    assert last_reply(fake_telegram) == "Nothing called computng. Closest: Computing."
    assert migrated_db.execute("SELECT count(*) FROM deal_blocks").fetchone()[0] == 0


def test_allow_undoes_never(bot, fake_telegram, migrated_db):
    name(migrated_db, "cat:gaming", "Gaming")
    say(bot, "/deals never gaming")

    say(bot, "/deals allow gaming")

    assert last_reply(fake_telegram) == "Allowed again: Gaming (category)."
    assert migrated_db.execute("SELECT count(*) FROM deal_blocks").fetchone()[0] == 0


def test_why_shows_the_numbers_for_the_last_deal_sent(bot, fake_telegram, migrated_db):
    fresh_deal(migrated_db, 1, title="Invented SSD $99")
    say(bot, "/deals now")

    say(bot, "/deals why")

    reply = last_reply(fake_telegram)
    assert reply.startswith("Invented SSD $99\n")
    assert "OzBargain score" in reply
    assert "Total" in reply


def test_why_with_nothing_sent(bot, fake_telegram, migrated_db):
    say(bot, "/deals why")

    assert last_reply(fake_telegram) == "No deal sent yet."


def test_why_reads_an_old_send_without_a_score(bot, fake_telegram, migrated_db):
    fresh_deal(migrated_db, 1)
    record_send(migrated_db, 1, datetime.now(UTC))

    say(bot, "/deals why")

    assert "No score was kept" in last_reply(fake_telegram)


def test_now_sends_the_roundup_and_leaves_sunday_due(bot, fake_telegram, migrated_db):
    fresh_deal(migrated_db, 1)

    say(bot, "/deals now")

    texts = [m["text"] for m in fake_telegram.sent()]
    assert texts[0] == "Deals so far this week: 1"
    assert texts[1].endswith("/node/1")
    kinds = migrated_db.execute("SELECT kind FROM deal_roundups").fetchall()
    assert kinds == [("now",)]


def test_off_and_on(bot, fake_telegram, migrated_db):
    say(bot, "/deals off")
    assert last_reply(fake_telegram) == "Deals paused."
    assert migrated_db.execute("SELECT paused FROM deal_state").fetchone()[0] is True

    say(bot, "/deals on")
    assert last_reply(fake_telegram) == "Deals on."
    assert migrated_db.execute("SELECT paused FROM deal_state").fetchone()[0] is False


@pytest.mark.parametrize("text", ["/deals", "/deals sideways"])
def test_usage(bot, fake_telegram, migrated_db, text):
    say(bot, text)

    assert last_reply(fake_telegram) == (
        "Usage: /deals more | less | never <name> | allow <name> | why | now | off | on"
    )


def test_deals_from_another_chat_gets_no_reply(bot, fake_telegram, migrated_db):
    say(bot, "/deals more", chat_id=99)

    assert fake_telegram.calls == []
    assert migrated_db.execute("SELECT size_offset FROM deal_state").fetchone()[0] == 0


def test_deals_off_in_config_says_so(
    start_server, fake_telegram, monkeypatch, tmp_path, migrated_db
):
    base_url = start_bot(start_server, fake_telegram, monkeypatch, tmp_path, enabled=False)

    say(base_url, "/deals more")

    assert last_reply(fake_telegram) == "The deal finder is off in mercury.yaml."
