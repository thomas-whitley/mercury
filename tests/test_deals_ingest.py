"""Each scheduler tick stores OzBargain's deals and one vote snapshot per
deal, drops the ones that cannot be bought, and says once in Telegram when
the feeds have not loaded for a day."""

from datetime import UTC, datetime, timedelta

import pytest

from app.deals import fetch_and_ingest, ingest, is_live
from app.ozbargain import parse_feed
from app.telegram import TelegramClient
from tests.ozbargain_fake import feed_xml, item_xml

NOW = datetime(2026, 11, 1, 1, 0, tzinfo=UTC)
CHAT = 42


def items(*xml: str):
    return parse_feed(feed_xml(*xml))


def snapshots(conn, node_id: int) -> list[tuple]:
    return conn.execute(
        "SELECT seen_at, votes_pos, front_page FROM deal_snapshots WHERE node_id = %s "
        "ORDER BY seen_at",
        (node_id,),
    ).fetchall()


def test_ingest_stores_a_deal_and_one_snapshot(migrated_db):
    stored = ingest(migrated_db, items(item_xml(1, "Invented deal")), [], NOW)

    assert stored == 1
    row = migrated_db.execute(
        "SELECT title, category, store, tags, first_seen_at FROM deals WHERE node_id = 1"
    ).fetchone()
    assert row == ("Invented deal", "cat:computing", "store:amazon-au", ["tag:ssd"], NOW)
    names = dict(migrated_db.execute("SELECT key, name FROM deal_feature_names").fetchall())
    assert names["store:amazon-au"] == "Amazon AU"
    assert snapshots(migrated_db, 1) == [(NOW, 10, False)]


def test_a_deal_in_both_feeds_is_one_snapshot_on_the_front_page(migrated_db):
    deal = item_xml(2, "Invented deal")

    ingest(migrated_db, items(deal), items(deal), NOW)

    assert snapshots(migrated_db, 2) == [(NOW, 10, True)]


def test_a_second_tick_adds_a_snapshot_and_keeps_first_seen(migrated_db):
    ingest(migrated_db, items(item_xml(3, "Invented deal", pos=10)), [], NOW)
    later = NOW + timedelta(hours=1)
    ingest(migrated_db, items(item_xml(3, "Invented deal", pos=25)), [], later)

    assert [row[1] for row in snapshots(migrated_db, 3)] == [10, 25]
    first, last = migrated_db.execute(
        "SELECT first_seen_at, last_seen_at FROM deals WHERE node_id = 3"
    ).fetchone()
    assert (first, last) == (NOW, later)


@pytest.mark.parametrize(
    "extra",
    [
        {"flag": "expired"},
        {"flag": "targeted"},
        {"flag": "upcoming"},
        {"expiry": "2026-10-31T10:00:00+11:00"},
    ],
)
def test_deals_that_cannot_be_bought_are_not_stored(migrated_db, extra):
    stored = ingest(migrated_db, items(item_xml(4, "Invented deal", **extra)), [], NOW)

    assert stored == 0
    assert migrated_db.execute("SELECT count(*) FROM deals").fetchone()[0] == 0


def test_a_stored_deal_that_turns_expired_is_marked_and_not_snapshotted(migrated_db):
    ingest(migrated_db, items(item_xml(5, "Invented deal")), [], NOW)
    later = NOW + timedelta(hours=1)
    ingest(migrated_db, items(item_xml(5, "Invented deal", flag="expired")), [], later)

    assert migrated_db.execute("SELECT flag FROM deals WHERE node_id = 5").fetchone()[0] == (
        "expired"
    )
    assert len(snapshots(migrated_db, 5)) == 1
    assert not is_live(migrated_db, 5, later)


def test_is_live(migrated_db):
    ingest(
        migrated_db,
        items(
            item_xml(6, "Long lived"),
            item_xml(7, "Ends soon", expiry="2026-11-02T12:00:00+11:00"),
        ),
        [],
        NOW,
    )

    assert is_live(migrated_db, 6, NOW + timedelta(days=8))
    assert is_live(migrated_db, 7, NOW)
    assert not is_live(migrated_db, 7, NOW + timedelta(days=2))
    assert not is_live(migrated_db, 999, NOW)


def test_one_feed_failing_still_stores_the_other(migrated_db, fake_ozbargain):
    fake_ozbargain.new_items = [item_xml(8, "Invented deal")]
    fake_ozbargain.path_status["/feed"] = 500

    stored = fetch_and_ingest(migrated_db, fake_ozbargain.url, NOW, None, None)

    assert stored == 1
    assert sorted(fake_ozbargain.paths()) == ["/deals/feed", "/feed"]
    ok_at = migrated_db.execute("SELECT last_fetch_ok_at FROM deal_state").fetchone()[0]
    assert ok_at == NOW


def test_malformed_xml_on_one_feed_still_stores_the_other(migrated_db, fake_ozbargain):
    fake_ozbargain.front_items = [item_xml(9, "Invented deal")]
    fake_ozbargain.raw["/deals/feed"] = b"<rss><channel><item>"

    assert fetch_and_ingest(migrated_db, fake_ozbargain.url, NOW, None, None) == 1


def test_a_day_without_a_fetch_sends_one_message_then_one_when_it_works(
    migrated_db, fake_ozbargain, fake_telegram
):
    telegram = TelegramClient("123:abc", fake_telegram.url)
    created = migrated_db.execute("SELECT created_at FROM deal_state").fetchone()[0]
    fake_ozbargain.status_override = 500

    fetch_and_ingest(migrated_db, fake_ozbargain.url, created + timedelta(hours=23), telegram, CHAT)
    assert fake_telegram.sent() == []

    fetch_and_ingest(migrated_db, fake_ozbargain.url, created + timedelta(hours=25), telegram, CHAT)
    fetch_and_ingest(migrated_db, fake_ozbargain.url, created + timedelta(hours=26), telegram, CHAT)
    [down] = fake_telegram.sent()
    assert "OzBargain feeds have not loaded for 24 hours" in down["text"]

    fake_ozbargain.status_override = None
    fetch_and_ingest(migrated_db, fake_ozbargain.url, created + timedelta(hours=27), telegram, CHAT)
    assert "loading again" in fake_telegram.sent()[-1]["text"]
    assert len(fake_telegram.sent()) == 2
    notified = migrated_db.execute("SELECT feed_down_notified FROM deal_state").fetchone()[0]
    assert notified is False


@pytest.mark.parametrize("flag", ["targeted", "upcoming"])
def test_a_stored_deal_that_turns_targeted_or_upcoming_stops_being_live(migrated_db, flag):
    ingest(migrated_db, items(item_xml(10, "Invented deal")), [], NOW)

    ingest(
        migrated_db, items(item_xml(10, "Invented deal", flag=flag)), [], NOW + timedelta(hours=1)
    )

    assert not is_live(migrated_db, 10, NOW + timedelta(hours=1))


def test_a_truncated_response_on_one_feed_still_reads_the_other(
    migrated_db, fake_ozbargain, monkeypatch
):
    import http.client
    import urllib.request

    fake_ozbargain.front_items = [item_xml(11, "Invented deal")]
    real = urllib.request.urlopen

    def flaky(request, *args, **kwargs):
        if request.full_url.endswith("/deals/feed"):
            raise http.client.IncompleteRead(b"")
        return real(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", flaky)

    assert fetch_and_ingest(migrated_db, fake_ozbargain.url, NOW, None, None) == 1
