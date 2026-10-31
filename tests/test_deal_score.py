"""A deal's score: OzBargain's community signal times what the ratings
taught, with Overpriced raising a category's bar instead of lowering taste."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.deal_score import Learned, Rated, Snapshot, community_score, explain, learn, score
from app.mercury_config import DealsConfig

NOW = datetime(2026, 11, 1, 1, 0, tzinfo=UTC)
POSTED = NOW - timedelta(hours=2)
CONFIG = DealsConfig()
UNTRAINED = Learned(weights={}, price_bars={})


def snap(pos: int, neg: int = 0, comments: int = 0, front: bool = False, at: datetime = NOW):
    return Snapshot(seen_at=at, votes_pos=pos, votes_neg=neg, comments=comments, front_page=front)


def rated(
    rating: str, category: str | None = "cat:x", *, silent=False, days_ago=0.0, store=None, tags=()
):
    return Rated(
        rating=rating,
        silent=silent,
        rated_at=NOW - timedelta(days=days_ago),
        category=category,
        store=store,
        tags=tuple(tags),
    )


def test_an_untrained_score_is_community_alone():
    result = score(POSTED, [snap(30, 2, 5)], "cat:x", "store:s", ("tag:t",), UNTRAINED, NOW, CONFIG)

    assert result.taste == 0
    assert result.total == pytest.approx(result.community)
    assert result.community > 0


def test_community_rises_with_votes_per_hour_and_front_page():
    young, _ = community_score(NOW - timedelta(hours=2), [snap(30)], NOW, CONFIG)
    old, _ = community_score(NOW - timedelta(hours=20), [snap(30)], NOW, CONFIG)
    front, _ = community_score(NOW - timedelta(hours=2), [snap(30, front=True)], NOW, CONFIG)

    assert young > old
    assert front - young == pytest.approx(CONFIG.community["front_page"])


def test_front_page_counts_when_any_snapshot_was_on_it():
    earlier = snap(10, front=True, at=NOW - timedelta(hours=1))
    _, parts = community_score(POSTED, [earlier, snap(30)], NOW, CONFIG)

    assert parts["front_page"] == CONFIG.community["front_page"]


def test_the_formula_parts_add_up():
    value, parts = community_score(POSTED, [snap(30, 10, 5)], NOW, CONFIG)

    assert parts["votes_per_hour"] == pytest.approx(2.0 * math.log(1 + 30 / 2))
    assert parts["net"] == pytest.approx(1.0 * math.log(1 + 20) * 0.75)
    assert parts["comments"] == pytest.approx(0.3 * math.log(6))
    assert value == pytest.approx(sum(parts.values()))


@pytest.mark.parametrize(("rating", "weight"), [("g", 1.0), ("o", 0.5), ("n", -0.5)])
def test_great_counts_more_than_good_and_not_for_me_lowers(rating, weight):
    assert learn([rated(rating)], NOW, CONFIG).weights == {"cat:x": pytest.approx(weight)}


def test_three_not_for_me_push_a_category_down_the_ranking():
    learned = learn([rated("n"), rated("n"), rated("n")], NOW, CONFIG)
    disliked = score(POSTED, [snap(40, 1, 5)], "cat:x", None, (), learned, NOW, CONFIG)
    other = score(POSTED, [snap(15, 1, 1)], "cat:y", None, (), learned, NOW, CONFIG)

    assert other.community < 0.75 * disliked.community
    assert other.total > disliked.total


def test_overpriced_raises_the_category_bar_and_leaves_weights_alone():
    learned = learn([rated("p"), rated("p")], NOW, CONFIG)
    # Community from 13 comments alone is 0.3 * ln(14), about 0.79.
    cheap = score(POSTED, [snap(0, comments=13)], "cat:x", None, (), learned, NOW, CONFIG)

    assert learned.weights == {}
    assert learned.price_bars == {"cat:x": pytest.approx(1.0)}
    assert cheap.price_bar == pytest.approx(1.0)
    assert cheap.total == 0


def test_silence_is_a_weak_not_for_me():
    assert learn([rated("n", silent=True)], NOW, CONFIG).weights == {"cat:x": pytest.approx(-0.2)}


def test_ratings_decay_by_half_life():
    assert learn([rated("g", days_ago=90)], NOW, CONFIG).weights == {"cat:x": pytest.approx(0.5)}


def test_a_rating_touches_category_store_and_every_tag():
    learned = learn([rated("g", store="store:s", tags=["tag:a", "tag:b"])], NOW, CONFIG)

    assert learned.weights == {
        "cat:x": pytest.approx(1.0),
        "store:s": pytest.approx(1.0),
        "tag:a": pytest.approx(1.0),
        "tag:b": pytest.approx(1.0),
    }


def test_twelve_tags_weigh_as_one_term():
    tags = [f"tag:{n}" for n in range(12)]
    learned = Learned(weights={tag: 1.0 for tag in tags}, price_bars={})

    many = score(POSTED, [snap(30)], None, None, tuple(tags), learned, NOW, CONFIG)
    two = score(POSTED, [snap(30)], None, None, tuple(tags[:2]), learned, NOW, CONFIG)

    assert many.taste == pytest.approx(1.0)
    assert two.taste == pytest.approx(1.0)


def test_a_deal_with_no_features_scores_on_community():
    learned = Learned(weights={"cat:x": -2.0}, price_bars={"cat:x": 5.0})

    result = score(POSTED, [snap(30)], None, None, (), learned, NOW, CONFIG)

    assert result.taste == 0
    assert result.price_bar == 0
    assert result.total == pytest.approx(result.community)


def test_explain_names_every_part():
    learned = Learned(weights={"cat:x": -0.5, "tag:t": 1.25}, price_bars={"cat:x": 0.5})
    result = score(POSTED, [snap(30, 2, 5)], "cat:x", None, ("tag:t",), learned, NOW, CONFIG)

    text = explain(result, {"cat:x": "Computing", "tag:t": "SSD"})

    assert f"{result.community:.2f}" in text
    for part in ("votes per hour", "net votes", "comments", "front page"):
        assert part in text
    assert "Computing -0.50" in text
    assert "SSD +1.25" in text
    assert "0.50" in text
    assert f"Total {result.total:.2f}" in text
