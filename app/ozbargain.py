"""Reads OzBargain's two public RSS feeds for the deal finder (app/deals.py).

Only the two feed paths below are fetched, once per scheduler tick each,
with a user agent that names Mercury. robots.txt disallows /api/, /comment/
and /goto/, and nothing here goes near them. Each item's votes and comment
count come from its ozb:meta element, and its category, store and tags from
<category> elements whose domain path starts /cat/, /brand/ or /tag/. The
ozb namespace is matched by local name, so a change of its URL does not
silently drop every vote.

Nothing here logs a title. FeedError carries the path and the error class.
"""

import http.client
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

NEW_FEED = "/deals/feed"
FRONT_FEED = "/feed"
USER_AGENT = "Mercury deal finder (personal, hourly)"
TIMEOUT_SECONDS = 10.0
# ozb:title-msg types that drop a deal before scoring. longrunning stays.
DROPPED_FLAGS = frozenset({"expired", "targeted", "upcoming"})

_NODE = re.compile(r"/node/(\d+)")
_KINDS = {"cat": "cat", "brand": "store", "tag": "tag"}


@dataclass(frozen=True)
class Feature:
    """key is the kind and OzBargain's slug, "cat:computing"; name is how
    the feed displays it."""

    key: str
    name: str


@dataclass(frozen=True)
class FeedItem:
    node_id: int
    title: str
    posted_at: datetime
    votes_pos: int
    votes_neg: int
    comments: int
    expires_at: datetime | None
    flag: str | None
    category: Feature | None
    store: Feature | None
    tags: tuple[Feature, ...]


class FeedError(Exception):
    pass


def fetch_feed(base_url: str, path: str) -> list[FeedItem]:
    """The items of one feed. Any failure to fetch or parse is a FeedError."""
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        raise FeedError(f"{path} answered HTTP {error.code}") from None
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise FeedError(f"{path} failed: {type(error).__name__}") from None
    try:
        return parse_feed(body)
    except FeedError as error:
        raise FeedError(f"{path}: {error}") from None


def parse_feed(xml: bytes) -> list[FeedItem]:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        raise FeedError("the feed is not well formed XML") from None
    items = []
    for element in root.iter("item"):
        item = _item(element)
        if item is not None:
            items.append(item)
    return items


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((child for child in element if _local(child.tag) == name), None)


def _item(element: ElementTree.Element) -> FeedItem | None:
    node_id = None
    for name in ("link", "guid"):
        found = _NODE.search(element.findtext(name) or "")
        if found:
            node_id = int(found[1])
            break
    if node_id is None:
        return None

    meta = _child(element, "meta")
    attrs = meta.attrib if meta is not None else {}
    flag_element = _child(element, "title-msg")

    category = store = None
    tags = []
    for entry in element.findall("category"):
        parts = urlsplit(entry.get("domain") or "").path.strip("/").split("/")
        if len(parts) != 2 or parts[0] not in _KINDS:
            continue
        kind = _KINDS[parts[0]]
        feature = Feature(f"{kind}:{parts[1]}", (entry.text or parts[1]).strip())
        if kind == "cat" and category is None:
            category = feature
        elif kind == "store" and store is None:
            store = feature
        elif kind == "tag":
            tags.append(feature)

    return FeedItem(
        node_id=node_id,
        title=(element.findtext("title") or "").strip(),
        posted_at=_posted(element.findtext("pubDate")),
        votes_pos=_count(attrs.get("votes-pos")),
        votes_neg=_count(attrs.get("votes-neg")),
        comments=_count(attrs.get("comment-count")),
        expires_at=_moment(attrs.get("expiry")),
        flag=flag_element.get("type") if flag_element is not None else None,
        category=category,
        store=store,
        tags=tuple(tags),
    )


def _count(value: str | None) -> int:
    try:
        return max(0, int(value or 0))
    except ValueError:
        return 0


def _moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _posted(value: str | None) -> datetime:
    """The pubDate, or now when it is missing or unreadable, so an item is
    never dropped for its date alone."""
    try:
        moment = parsedate_to_datetime(value or "")
    except (TypeError, ValueError):
        return datetime.now(UTC)
    return moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
