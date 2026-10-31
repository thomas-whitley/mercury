"""How the deal finder scores a deal. Plain counting, no model call, every
number from config (DealsConfig in app/mercury_config.py), so /deals why can
show each part. This docstring is the one place the formula is stated.

Community signal, from the newest snapshot (c is deals.community):

    age_hours = max(1, hours from posting to the newest snapshot)
    share     = pos / (pos + neg), 0 when both are 0
    community = c.votes_per_hour * ln(1 + pos / age_hours)
              + c.net * ln(1 + max(0, pos - neg)) * share
              + c.comments * ln(1 + comments)
              + c.front_page * (1 if any snapshot was on the front page, else 0)

Learning, recomputed from every rating on each use, so a change of step or
half life applies to old ratings too:

    decay(r)     = 0.5 ** (days since r was rated / half_life_days)
    weight[f]    = sum of steps[r] * decay(r) over ratings whose deal has feature f
                   (a silent rating uses steps.silence; Overpriced adds nothing)
    price_bar[c] = sum of overpriced_step * decay(r) over Overpriced ratings in category c

Ranking:

    taste = weight[category] + weight[store] + mean(weight[t] for each tag)
            (a missing feature or an empty tag list is 0)
    total = community * 2 ** taste, or 0 when community < price_bar[category]
"""

import math
from dataclasses import asdict, dataclass
from datetime import datetime

from app.mercury_config import DealsConfig

PART_NAMES = {
    "votes_per_hour": "votes per hour",
    "net": "net votes",
    "comments": "comments",
    "front_page": "front page",
}


@dataclass(frozen=True)
class Snapshot:
    seen_at: datetime
    votes_pos: int
    votes_neg: int
    comments: int
    front_page: bool


@dataclass(frozen=True)
class Rated:
    """One rating, with the features of the deal it was given to."""

    rating: str
    silent: bool
    rated_at: datetime
    category: str | None
    store: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Learned:
    weights: dict[str, float]
    price_bars: dict[str, float]


@dataclass(frozen=True)
class Score:
    community: float
    community_parts: dict[str, float]
    taste: float
    taste_parts: dict[str, float]
    price_bar: float
    total: float

    def as_json(self) -> dict:
        return asdict(self)


def community_score(
    posted_at: datetime, snapshots: list[Snapshot], now: datetime, config: DealsConfig
) -> tuple[float, dict[str, float]]:
    c = config.community
    parts = dict.fromkeys(PART_NAMES, 0.0)
    if snapshots:
        latest = max(snapshots, key=lambda s: s.seen_at)
        pos, neg = latest.votes_pos, latest.votes_neg
        age_hours = max(1.0, (latest.seen_at - posted_at).total_seconds() / 3600)
        share = pos / (pos + neg) if pos + neg else 0.0
        parts["votes_per_hour"] = c["votes_per_hour"] * math.log(1 + pos / age_hours)
        parts["net"] = c["net"] * math.log(1 + max(0, pos - neg)) * share
        parts["comments"] = c["comments"] * math.log(1 + latest.comments)
        parts["front_page"] = c["front_page"] * (1.0 if any(s.front_page for s in snapshots) else 0)
    return sum(parts.values()), parts


def learn(ratings: list[Rated], now: datetime, config: DealsConfig) -> Learned:
    weights: dict[str, float] = {}
    price_bars: dict[str, float] = {}
    for r in ratings:
        days = (now - r.rated_at).total_seconds() / 86400
        decay = 0.5 ** (max(0.0, days) / config.half_life_days)
        if r.rating == "p":
            if r.category is not None:
                price_bars[r.category] = (
                    price_bars.get(r.category, 0.0) + config.overpriced_step * decay
                )
            continue
        step = config.steps["silence"] if r.silent else config.steps[r.rating]
        for feature in (r.category, r.store, *r.tags):
            if feature is not None:
                weights[feature] = weights.get(feature, 0.0) + step * decay
    return Learned(weights=weights, price_bars=price_bars)


def score(
    posted_at: datetime,
    snapshots: list[Snapshot],
    category: str | None,
    store: str | None,
    tags: tuple[str, ...],
    learned: Learned,
    now: datetime,
    config: DealsConfig,
) -> Score:
    community, community_parts = community_score(posted_at, snapshots, now, config)
    taste_parts = {
        f: learned.weights.get(f, 0.0) for f in (category, store, *tags) if f is not None
    }
    tag_term = sum(taste_parts[t] for t in tags) / len(tags) if tags else 0.0
    taste = (
        (taste_parts[category] if category else 0.0)
        + (taste_parts[store] if store else 0.0)
        + tag_term
    )
    price_bar = learned.price_bars.get(category, 0.0) if category else 0.0
    total = 0.0 if community < price_bar else community * 2**taste
    return Score(community, community_parts, taste, taste_parts, price_bar, total)


def explain(result: Score, names: dict[str, str]) -> str:
    """The numbers /deals why shows."""
    parts = ", ".join(
        f"{PART_NAMES[key]} {value:.2f}" for key, value in result.community_parts.items()
    )
    lines = [f"OzBargain score {result.community:.2f}: {parts}."]
    if result.taste_parts:
        weights = ", ".join(
            f"{names.get(key, key)} {value:+.2f}" for key, value in result.taste_parts.items()
        )
        lines.append(f"Your weights: {weights}. Tags are averaged into one term.")
    else:
        lines.append("No weights applied yet.")
    if result.price_bar:
        lines.append(f"Category bar from Overpriced: {result.price_bar:.2f}.")
    lines.append(
        f"Total {result.total:.2f} = {result.community:.2f} x 2^{result.taste:+.2f}"
        + (" (under the category bar, so 0)" if result.community < result.price_bar else "")
        + "."
    )
    return "\n".join(lines)
