"""The deal finder's step in the scheduler tick: off unless deals.enabled,
then fetch, silence, a due roundup and alerts, with nothing able to stop
the rest of the tick and no deal reaching the run list."""

from datetime import timedelta

import httpx2
import pytest

from app import deals
from app.config import load_settings
from app.mercury_config import DealsConfig, MercuryConfig
from app.telegram import TelegramClient
from tests.deal_seed import CHAT, SUNDAY
from tests.ozbargain_fake import item_xml

TITLE = "Invented Tick Deal $42"
POSTED = (SUNDAY - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S %z")


def mercury(enabled: bool = True) -> MercuryConfig:
    return MercuryConfig(sites=(), telegram_chat_id=CHAT, deals=DealsConfig(enabled=enabled))


@pytest.fixture
def settings(fake_ozbargain, monkeypatch, clean_db):
    monkeypatch.setenv("DATABASE_URL", clean_db)
    monkeypatch.setenv("OZBARGAIN_URL", fake_ozbargain.url)
    return load_settings()


@pytest.fixture
def telegram(fake_telegram):
    return TelegramClient("123:abc", fake_telegram.url)


def test_tick_does_nothing_when_disabled(migrated_db, settings, telegram, fake_ozbargain):
    deals.tick(migrated_db, settings, mercury(enabled=False), telegram, SUNDAY)

    assert fake_ozbargain.requests == []


def test_tick_does_nothing_without_a_chat(migrated_db, settings, telegram, fake_ozbargain):
    config = MercuryConfig(sites=(), deals=DealsConfig(enabled=True))

    deals.tick(migrated_db, settings, config, telegram, SUNDAY)

    assert fake_ozbargain.requests == []


def test_tick_fetches_and_sends_a_due_roundup(
    migrated_db, settings, telegram, fake_ozbargain, fake_telegram
):
    fake_ozbargain.new_items = [item_xml(1, TITLE, posted=POSTED, pos=30)]
    fake_ozbargain.front_items = [item_xml(2, "Invented Front Deal", posted=POSTED, pos=90)]

    deals.tick(migrated_db, settings, mercury(), telegram, SUNDAY)

    texts = [m["text"] for m in fake_telegram.sent()]
    assert texts[0] == "Deals this week: 2"
    assert texts[1].endswith("/node/2")
    assert texts[2].startswith(TITLE)


def test_tick_records_silence(migrated_db, settings, telegram, fake_ozbargain, fake_telegram):
    fake_ozbargain.new_items = [item_xml(1, TITLE, posted=POSTED)]
    deals.tick(migrated_db, settings, mercury(), telegram, SUNDAY)

    deals.tick(migrated_db, settings, mercury(), telegram, SUNDAY + timedelta(days=7, hours=1))

    rows = migrated_db.execute("SELECT rating, silent FROM deal_ratings").fetchall()
    assert rows == [("n", True)]


def test_a_failing_deal_step_does_not_stop_the_tick(
    migrated_db, settings, telegram, fake_ozbargain, fake_telegram, monkeypatch
):
    fake_ozbargain.new_items = [item_xml(1, TITLE, posted=POSTED)]

    def broken(*args, **kwargs):
        raise RuntimeError(TITLE)

    monkeypatch.setattr(deals, "send_alerts", broken)

    deals.tick(migrated_db, settings, mercury(), telegram, SUNDAY)

    assert fake_telegram.sent()[0]["text"] == "Deals this week: 1"


def test_the_run_list_shows_no_deal(
    start_server, migrated_db, settings, telegram, fake_ozbargain, fake_telegram
):
    fake_ozbargain.new_items = [item_xml(1, TITLE, posted=POSTED)]
    deals.tick(migrated_db, settings, mercury(), telegram, SUNDAY)
    migrated_db.execute("INSERT INTO deal_ratings VALUES (1, 'g', false, now())")
    base_url = start_server()

    response = httpx2.get(f"{base_url}/runs")

    assert response.status_code == 200
    assert TITLE not in response.text
    assert migrated_db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
