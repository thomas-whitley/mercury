"""Reading OzBargain's two RSS feeds: the votes, the category, store and
tags, the expiry and the flags, and nothing fetched but the named feed."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.ozbargain import (
    NEW_FEED,
    USER_AGENT,
    Feature,
    FeedError,
    fetch_feed,
    parse_feed,
)
from tests.ozbargain_fake import feed_xml, item_xml


def test_parse_reads_votes_features_and_expiry():
    [item] = parse_feed(
        feed_xml(
            item_xml(
                901,
                "Invented SSD 2TB $99",
                pos=40,
                neg=3,
                comments=12,
                expiry="2026-10-30T13:00:00+11:00",
            )
        )
    )

    assert item.node_id == 901
    assert item.title == "Invented SSD 2TB $99"
    assert (item.votes_pos, item.votes_neg, item.comments) == (40, 3, 12)
    assert item.posted_at == datetime(2026, 10, 23, 3, 0, tzinfo=UTC)
    assert item.expires_at == datetime(2026, 10, 30, 13, 0, tzinfo=timezone(timedelta(hours=11)))
    assert item.category == Feature("cat:computing", "Computing")
    assert item.store == Feature("store:amazon-au", "Amazon AU")
    assert item.tags == (Feature("tag:ssd", "SSD"),)
    assert item.flag is None


def test_parse_reads_the_flag():
    [item] = parse_feed(feed_xml(item_xml(902, "Invented deal", flag="targeted")))

    assert item.flag == "targeted"


def test_parse_decodes_entities():
    [item] = parse_feed(feed_xml(item_xml(903, "Invented 2TB & Heatsink $199")))

    assert item.title == "Invented 2TB & Heatsink $199"


def test_parse_survives_an_item_with_no_features_or_meta():
    [item] = parse_feed(
        feed_xml(item_xml(904, "Bare deal", category=None, store=None, tags=(), meta=False))
    )

    assert item.category is None
    assert item.store is None
    assert item.tags == ()
    assert (item.votes_pos, item.votes_neg, item.comments) == (0, 0, 0)
    assert item.expires_at is None


def test_parse_skips_an_item_with_no_node_id():
    items = parse_feed(feed_xml(item_xml(None, "No link"), item_xml(905, "Has link")))

    assert [item.node_id for item in items] == [905]


def test_parse_raises_feed_error_on_malformed_xml():
    with pytest.raises(FeedError):
        parse_feed(b"<rss><channel><item>")


def test_fetch_sends_the_user_agent_and_reads_only_the_named_path(fake_ozbargain):
    fake_ozbargain.new_items = [item_xml(906, "Invented deal")]

    items = fetch_feed(fake_ozbargain.url, NEW_FEED)

    assert [item.node_id for item in items] == [906]
    assert fake_ozbargain.requests == [("/deals/feed", USER_AGENT)]


def test_fetch_raises_feed_error_on_http_500(fake_ozbargain):
    fake_ozbargain.status_override = 500

    with pytest.raises(FeedError, match="/deals/feed"):
        fetch_feed(fake_ozbargain.url, NEW_FEED)
