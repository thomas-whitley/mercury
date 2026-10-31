# Deal Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mercury reads OzBargain's two RSS feeds every scheduler tick, sends Thomas a weekly roundup of live deals ranked by community signal times learned taste, learns from four rating buttons and from silence, sends rare instant alerts once it has 30 ratings, and takes `/deals` commands.

**Architecture:** The scheduler tick fetches both feeds (`app/ozbargain.py`), stores deals and vote snapshots, records silence, sends a due roundup and any alerts (`app/deals.py`). Scoring is pure functions over rows (`app/deal_score.py`): weights are recomputed from the ratings table on every use, so step sizes and decay in config apply without a migration and `/deals why` can show the sum. The api's webhook handles button presses and `/deals` commands (`app/deal_commands.py`), calling the same `app/deals.py` functions in a threadpool with a sync connection, as `_advise_newest` does. Nothing touches `runs`.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, plain SQL migrations, `xml.etree.ElementTree` from the standard library (no new dependency), pytest against Postgres and the fake Telegram.

**Spec:** `docs/superpowers/specs/2026-10-23-deal-finder-design.md`

## Global Constraints

- No new dependency. Feeds are read with `urllib.request` and parsed with `xml.etree.ElementTree`.
- No model calls. $0 added running cost.
- Fetch only `https://www.ozbargain.com.au/deals/feed` and `https://www.ozbargain.com.au/feed`, once per tick each, with a 10 second timeout and the user agent `Mercury deal finder (personal, hourly)`. Never fetch `/api/`, `/comment/` or `/goto/`. Messages link to `https://www.ozbargain.com.au/node/<id>`.
- No deal title, rating, weight or store in the public repo, the run list at `/`, `/runs`, the event stream, the MCP tools, or any log line. Logs may carry node ids and numbers only. Tests use invented titles.
- Starting values (all in `deals:` in `mercury.yaml`, all tunable): Sunday 10:00 in `telegram.timezone`, roundup size 10, `/deals more|less` change size by 3 and the alert bar by one step, alerts after 30 ratings, silence after 7 days.
- Only the allowed chat's presses and commands count. Callback data is `deal:<node id>:<letter>`, letters `g` 🔥 Great, `o` 👍 Good, `n` 👎 Not for me, `p` 💸 Overpriced, under Telegram's 64 byte limit.
- State lives in the database. Each scheduler tick is a fresh process.
- Repo rules from `CLAUDE.md`: failing test first; README claims row only once green; commit after each green task with a plain message (no `feat:`, no emoji, no dashes); no em or en dashes and none of the banned words in README, docs or commits.
- Run tests in WSL against `mercury-test-db` (start it with `docker start mercury-test-db`, stop it after the last task):
  `wsl -e bash -lc "cd /mnt/c/Projects/agent-runs && TEST_DATABASE_URL=postgresql://agent:agent@localhost:55432/agent_runs_test UV_PROJECT_ENVIRONMENT=/tmp/mercury-venv uv run --frozen pytest <args>"`. Below, `PYTEST <args>` means this command.

## Review Focus

1. **One feed down, or malformed XML.** The other feed's deals are still stored and the tick goes on. Test in Task 3.
2. **A deal with no category, no store or no tags.** It scores on community alone, with empty tags averaging to 0, not a ZeroDivisionError. Test in Task 4.
3. **Telegram fails part way through a roundup.** If the heading fails, nothing is recorded and the next tick retries. If one deal's message fails, that deal is not marked sent, the rest still go, and the roundup is not resent every hour. Test in Task 6.
4. **The PC is off on Sunday morning.** The first tick after start sends the roundup once, with the window from the last scheduled roundup, and a `/deals now` earlier in the week does not stop it. Test in Task 6.
5. **Titles with entities, odd characters or great length.** `&amp;` arrives as `&`, messages are plain text (no `parse_mode`), and a deal message stays under 4,000 characters. Test in Tasks 2 and 6.

---

### Task 1: The `deals:` config section

**Files:**
- Modify: `app/mercury_config.py`
- Modify: `config/mercury.sample.yaml`
- Test: `tests/test_mercury_config.py`

**Interfaces:**
- Produces: `DealsConfig` frozen dataclass and `MercuryConfig.deals: DealsConfig` (default `DealsConfig()`, so a config with no `deals:` section has the feature off).

```python
@dataclass(frozen=True)
class DealsConfig:
    enabled: bool = False                 # only a YAML true
    roundup_weekday: int = 6              # Monday 0, Sunday 6
    roundup_time: time = time(10, 0)
    roundup_size: int = 10
    size_step: int = 3
    alerts_after: int = 30
    alert_bar: float = 6.0                # total score an alert must reach
    bar_step: float = 1.0                 # one /deals more or less
    silence_days: int = 7
    half_life_days: float = 90.0          # a rating's weight halves this often
    steps: dict[str, float]               # g 1.0, o 0.5, n -0.5, silence -0.2
    overpriced_step: float = 0.5          # community bar raise per 💸 in a category
    community: dict[str, float]           # votes_per_hour 2.0, net 1.0, comments 0.3, front_page 1.0
```

- [ ] **Step 1: Write the failing tests**

`test_deals_default_to_off_with_the_starting_values`: a config with no `deals:` gives `config.deals.enabled is False`, `roundup_size == 10`, `roundup_weekday == 6`, `roundup_time == time(10, 0)`, `alerts_after == 30`, `silence_days == 7`, `steps == {"g": 1.0, "o": 0.5, "n": -0.5, "silence": -0.2}`.

`test_deals_reads_every_value`: a `deals:` section with `enabled: true`, `roundup_day: saturday`, `roundup_time: "09:30"`, `roundup_size: 5`, `steps: {great: 2, good: 1, not_for_me: -1, silence: -0.1}` reads back as `enabled is True`, `roundup_weekday == 5`, `roundup_time == time(9, 30)`, `roundup_size == 5`, `steps == {"g": 2.0, "o": 1.0, "n": -1.0, "silence": -0.1}`.

`test_deals_refuses_bad_values` (parametrized): `roundup_day: someday`, `roundup_time: "25:00"`, `roundup_size: 0`, `enabled: "true"` read as off (assert `enabled is False`, not a raise), `steps: {great: -1}` raises `ValueError` with `deals.steps.great` in the message (great and good must be positive, not_for_me and silence negative).

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_mercury_config.py -k deals -v`
Expected: FAIL, `MercuryConfig` has no attribute `deals`.

- [ ] **Step 3: Implement `DealsConfig` and `_deals(section) -> DealsConfig` in `app/mercury_config.py`**

YAML keys use words (`great`, `good`, `not_for_me`, `silence`, `roundup_day`); the dataclass keys `steps` by rating letter so the scorer indexes it directly. `community:` keys are `votes_per_hour`, `net`, `comments`, `front_page`. Errors follow the `review_notes` style: `ValueError("mercury.yaml: deals.<key> ...")`.

- [ ] **Step 4: Add a commented `deals:` section to `config/mercury.sample.yaml`** with every key at its starting value and one comment line per key. Update the schedule comment there to say the deal feeds are read on every tick.

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_mercury_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit** `Read the deal finder's settings from mercury.yaml`

---

### Task 2: Reading the OzBargain feeds

**Files:**
- Create: `app/ozbargain.py`
- Create: `tests/ozbargain_fake.py`
- Modify: `app/config.py` (add `ozbargain_url: str = "https://www.ozbargain.com.au"`, from `OZBARGAIN_URL`)
- Test: `tests/test_ozbargain.py`

**Interfaces:**
- Produces:

```python
NEW_FEED = "/deals/feed"
FRONT_FEED = "/feed"
USER_AGENT = "Mercury deal finder (personal, hourly)"
TIMEOUT_SECONDS = 10.0
DROPPED_FLAGS = frozenset({"expired", "targeted", "upcoming"})

@dataclass(frozen=True)
class Feature:
    key: str      # "cat:computing", "store:amazon-au", "tag:ssd"
    name: str     # the display name from the <category> text

@dataclass(frozen=True)
class FeedItem:
    node_id: int
    title: str
    posted_at: datetime
    votes_pos: int
    votes_neg: int
    comments: int
    expires_at: datetime | None
    flag: str | None          # ozb:title-msg type, or None
    category: Feature | None
    store: Feature | None
    tags: tuple[Feature, ...]

class FeedError(Exception): ...

def parse_feed(xml: bytes) -> list[FeedItem]
def fetch_feed(base_url: str, path: str) -> list[FeedItem]   # raises FeedError
```

- [ ] **Step 1: Write `tests/ozbargain_fake.py`**

`item_xml(node_id, title, *, pos=10, neg=0, comments=2, posted="Fri, 23 Oct 2026 03:00:00 +0000", expiry=None, flag=None, category=("computing", "Computing"), store=("amazon-au", "Amazon AU"), tags=(("ssd", "SSD"),)) -> str` builds one `<item>` in OzBargain's shape (`<link>https://www.ozbargain.com.au/node/<id></link>`, `<ozb:meta votes-pos=... votes-neg=... comment-count=... expiry=.../>`, `<ozb:title-msg type=.../>`, `<category domain="https://www.ozbargain.com.au/cat/computing">Computing</category>` and the `/brand/` and `/tag/` ones). `feed_xml(*items) -> bytes` wraps them in an RSS 2.0 channel declaring `xmlns:ozb="https://www.ozbargain.com.au"`. `FakeOzBargain` serves `/deals/feed` and `/feed` from settable `new_items` and `front_items`, records each request's path and `User-Agent`, and has `status_override: int | None`. Copy the server shape from `tests/osv_fake.py`.

- [ ] **Step 2: Write the failing tests**

- `test_parse_reads_votes_features_and_expiry`: one item with `expiry="2026-10-30T13:00:00+11:00"` parses to `node_id`, `votes_pos`, `votes_neg`, `comments`, `posted_at` (aware UTC), `expires_at` (aware), `category == Feature("cat:computing", "Computing")`, `store == Feature("store:amazon-au", "Amazon AU")`, `tags == (Feature("tag:ssd", "SSD"),)`.
- `test_parse_reads_the_flag`: `flag="targeted"` gives `item.flag == "targeted"`.
- `test_parse_decodes_entities`: title `"Crucial T500 2TB &amp; Heatsink $199"` gives `"Crucial T500 2TB & Heatsink $199"`.
- `test_parse_survives_an_item_with_no_features_or_meta`: no categories and no `ozb:meta` gives `category is None`, `store is None`, `tags == ()`, votes 0.
- `test_parse_skips_an_item_with_no_node_id` and `test_parse_raises_feed_error_on_malformed_xml`.
- `test_fetch_sends_the_user_agent_and_reads_only_the_named_path`: against `FakeOzBargain`, `fetch_feed(fake.url, NEW_FEED)` returns the items and the fake recorded exactly `["/deals/feed"]` with `User-Agent == USER_AGENT`.
- `test_fetch_raises_feed_error_on_http_500`.

- [ ] **Step 3: Run them to see them fail**

Run: `PYTEST tests/test_ozbargain.py -v`
Expected: FAIL, `No module named 'app.ozbargain'`.

- [ ] **Step 4: Implement `app/ozbargain.py`**

The node id comes from the `link`, falling back to `guid`, with `r"/node/(\d+)"`. A `<category>` domain path decides the kind: `/cat/<slug>`, `/brand/<slug>` (store), `/tag/<slug>`. Missing numbers read as 0. `FeedError` messages name the path and the error class only.

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_ozbargain.py -v`
Expected: PASS.

- [ ] **Step 6: Commit** `Read OzBargain's new deals and front page feeds`

---

### Task 3: Storing deals each tick, and feed health

**Files:**
- Create: `migrations/020_deals.sql`
- Create: `app/deals.py`
- Test: `tests/test_deals_ingest.py`

**Interfaces:**
- Consumes: `FeedItem`, `fetch_feed`, `NEW_FEED`, `FRONT_FEED`, `DROPPED_FLAGS` (Task 2); `DealsConfig` (Task 1).
- Produces: the schema below, and

```python
FEED_DOWN_AFTER = timedelta(hours=24)

def ingest(conn, new: list[FeedItem], front: list[FeedItem], now: datetime) -> int   # deals stored
def fetch_and_ingest(conn, base_url: str, now: datetime,
                     telegram: TelegramClient | None, chat_id: int | None) -> int
def is_live(conn, node_id: int, now: datetime) -> bool
```

Schema (`020_deals.sql`), with a header comment saying these tables hold Thomas's ratings and must never be read by the run list, `/runs`, the stream or MCP:

```sql
deals (node_id bigint PK, title text NOT NULL, posted_at timestamptz NOT NULL,
       expires_at timestamptz, flag text, category text, store text, tags text[] NOT NULL DEFAULT '{}',
       first_seen_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL)
deal_feature_names (key text PK, name text NOT NULL)
deal_snapshots (node_id bigint REFERENCES deals ON DELETE CASCADE, seen_at timestamptz,
                votes_pos int, votes_neg int, comments int, front_page boolean, PRIMARY KEY (node_id, seen_at))
deal_roundups (id bigint identity PK, kind text CHECK (kind IN ('scheduled','now')),
               sent_at timestamptz NOT NULL, heading_message_id bigint)
deal_sends (id bigint identity PK, node_id bigint REFERENCES deals, kind text CHECK (kind IN ('roundup','alert')),
            roundup_id bigint REFERENCES deal_roundups, chat_id bigint, message_id bigint,
            text text NOT NULL, score jsonb NOT NULL, sent_at timestamptz NOT NULL)
deal_ratings (node_id bigint PK REFERENCES deals, rating text CHECK (rating IN ('g','o','n','p')),
              silent boolean NOT NULL DEFAULT false, rated_at timestamptz NOT NULL)
deal_blocks (key text PK, created_at timestamptz NOT NULL DEFAULT now())
deal_would_alert (node_id bigint PK REFERENCES deals ON DELETE CASCADE, first_at timestamptz, total real)
deal_state (id int PK CHECK (id = 1), paused boolean DEFAULT false, size_offset int DEFAULT 0,
            bar_offset int DEFAULT 0, last_fetch_ok_at timestamptz, feed_down_notified boolean DEFAULT false,
            created_at timestamptz DEFAULT now())   -- one row, inserted by the migration
```

- [ ] **Step 1: Write the failing tests** (use `migrated_db`; `NOW = datetime(2026, 11, 1, 1, 0, tzinfo=UTC)`)

- `test_ingest_stores_a_deal_and_one_snapshot`: one item in `new` gives one `deals` row with `category = 'cat:computing'`, `tags = ['tag:ssd']`, a `deal_feature_names` row `('store:amazon-au', 'Amazon AU')`, and one snapshot with `front_page = false`.
- `test_a_deal_in_both_feeds_is_one_snapshot_on_the_front_page`.
- `test_a_second_tick_adds_a_snapshot_and_keeps_first_seen`: ingest at `NOW` then `NOW + 1h` with more votes gives 2 snapshots, `first_seen_at == NOW`, `last_seen_at == NOW + 1h`.
- `test_expired_targeted_and_upcoming_and_past_expiry_are_not_stored` (parametrized over the three flags and `expires_at < NOW`). A deal already stored that turns up flagged `expired` gets `flag = 'expired'` updated (so it is no longer live) but no new snapshot.
- `test_is_live`: false for flag `expired` or `expires_at < now`, true otherwise, including a deal not seen for 8 days.
- `test_one_feed_failing_still_stores_the_other`: `FakeOzBargain` with the front feed returning 500 (give the fake a per-path override) still stores the new feed's items and sets `last_fetch_ok_at`.
- `test_24_hours_without_a_fetch_sends_one_message_then_one_when_it_works`: both feeds 500 at `created_at + 25h` sends one message containing `"OzBargain feeds have not loaded for 24 hours"`; a second failing tick sends nothing more; a working tick sends one containing `"loading again"` and clears `feed_down_notified`.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_deals_ingest.py -v`
Expected: FAIL, `No module named 'app.deals'`.

- [ ] **Step 3: Write `migrations/020_deals.sql` and implement `ingest`, `fetch_and_ingest`, `is_live` in `app/deals.py`**

`ingest` merges `new` and `front` by node id (front wins `front_page = true`), upserts `deals`, `deal_feature_names` and one snapshot at `now`. `fetch_and_ingest` catches `FeedError` per feed and logs the path and error only; a tick counts as fetched when at least one feed parsed. The 24 hour clock starts from `coalesce(last_fetch_ok_at, created_at)`. Telegram errors are logged and swallowed.

- [ ] **Step 4: Run the tests, and `PYTEST tests/test_migrations.py`**

Expected: PASS.

- [ ] **Step 5: Commit** `Store OzBargain deals and vote snapshots each scheduler tick`

---

### Task 4: Scoring

**Files:**
- Create: `app/deal_score.py`
- Test: `tests/test_deal_score.py`

**Interfaces:**
- Consumes: `DealsConfig` (Task 1).
- Produces (pure, no database):

```python
@dataclass(frozen=True)
class Snapshot:
    seen_at: datetime; votes_pos: int; votes_neg: int; comments: int; front_page: bool

@dataclass(frozen=True)
class Rated:            # one row of deal_ratings joined to its deal's features
    rating: str         # 'g' 'o' 'n' 'p', or 'n' with silent=True
    silent: bool
    rated_at: datetime
    category: str | None; store: str | None; tags: tuple[str, ...]

@dataclass(frozen=True)
class Learned:
    weights: dict[str, float]          # feature key -> weight
    price_bars: dict[str, float]       # category key -> community bar

@dataclass(frozen=True)
class Score:
    community: float
    community_parts: dict[str, float]  # votes_per_hour, net, comments, front_page
    taste: float
    taste_parts: dict[str, float]      # feature key -> weight that applied
    price_bar: float
    total: float

def community_score(posted_at: datetime, snapshots: list[Snapshot], now: datetime, config: DealsConfig) -> tuple[float, dict[str, float]]
def learn(ratings: list[Rated], now: datetime, config: DealsConfig) -> Learned
def score(posted_at, snapshots, category, store, tags, learned: Learned, now, config) -> Score
def explain(score: Score, names: dict[str, str]) -> str      # the /deals why text
```

The formula, stated once in this module's docstring and nowhere else:

```
latest      = the newest snapshot; age_hours = max(1, hours from posted_at to latest.seen_at)
share       = pos / (pos + neg), 0 when both are 0
community   = c.votes_per_hour * ln(1 + pos / age_hours)
            + c.net * ln(1 + max(0, pos - neg)) * share
            + c.comments * ln(1 + comments)
            + c.front_page * (1 if any snapshot was on the front page else 0)
decay(r)    = 0.5 ** (days since r.rated_at / half_life_days)
weight[f]   = sum over ratings r touching f of steps[r] * decay(r)   (silent ones use steps["silence"]; 'p' adds nothing)
price_bar[c]= sum over 'p' ratings in category c of overpriced_step * decay(r)
taste       = weight[category] + weight[store] + mean(weight[t] for t in tags), each missing term 0, empty tags 0
total       = community * 2 ** taste, or 0 when community < price_bar[category]
```

- [ ] **Step 1: Write the failing tests**

- `test_an_untrained_score_is_community_alone`: no ratings gives `taste == 0` and `total == community`.
- `test_community_rises_with_votes_per_hour_and_front_page`: the same votes at 2 hours old beat 20 hours old; adding `front_page=True` adds exactly `config.community["front_page"]`.
- `test_great_counts_more_than_good_and_not_for_me_lowers`: weights after one `g`, one `o`, one `n` on the same category, each alone, are `1.0`, `0.5`, `-0.5`.
- `test_three_not_for_me_push_a_category_down_the_ranking`: deal A (category X) with 3 `n` ratings on X ranks below deal B (category Y) with community 30% lower.
- `test_overpriced_raises_the_category_bar_and_leaves_weights_alone`: two `p` on category X gives `weights == {}` and `price_bars == {"cat:x": 1.0}`; a deal in X with community 0.8 has `total == 0`.
- `test_silence_is_a_weak_not_for_me`: one silent rating gives category weight `-0.2`.
- `test_ratings_decay_by_half_life`: a `g` rated 90 days before `now` gives weight `0.5`.
- `test_twelve_tags_weigh_as_one_term`: twelve tags each weighted 1.0 give a tag term of 1.0, the same as two tags each 1.0.
- `test_a_deal_with_no_features_scores_on_community` (Review Focus 2).
- `test_explain_names_every_part`: the text contains the community total and each part, each feature's display name with its weight to 2 decimals, the price bar, and `Total`.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_deal_score.py -v`
Expected: FAIL, `No module named 'app.deal_score'`.

- [ ] **Step 3: Implement `app/deal_score.py`** to the formula above.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_deal_score.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** `Score deals by community signal times learned taste`

---

### Task 5: Telegram buttons in rows, and an edit that keeps them

**Files:**
- Modify: `app/telegram.py`
- Test: `tests/test_telegram.py`

**Interfaces:**
- Produces: `send_message(..., per_row: int | None = None)` and `edit_message_text(chat_id, message_id, text, buttons: list[tuple[str, str]] | None = None, *, per_row: int | None = None)`. With `per_row=None` the keyboard is one row, as today. `edit_message_text` without `buttons` sends exactly what it sends today, so the four existing callers (`approvals.py:102`, `chat.py:247`, `progress.py:114,132`, `telegram_webhook.py:375`) are unchanged. One private `_keyboard(buttons, per_row) -> dict` builds `reply_markup` for both.

- [ ] **Step 1: Write the failing tests** against `fake_telegram`

- `test_send_message_puts_buttons_two_per_row`: four buttons with `per_row=2` give `reply_markup.inline_keyboard` of two rows of two.
- `test_edit_with_buttons_keeps_the_keyboard`: the `editMessageText` payload carries `reply_markup` with the same rows.
- `test_edit_without_buttons_sends_no_reply_markup`: unchanged behaviour.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_telegram.py -v`
Expected: FAIL on the new tests with an unexpected keyword argument.

- [ ] **Step 3: Implement** in `app/telegram.py`.

- [ ] **Step 4: Run the tests, and the callers' tests**

Run: `PYTEST tests/test_telegram.py tests/test_approvals.py tests/test_chat.py tests/test_progress.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** `Let Telegram messages carry buttons in rows and keep them on edit`

---

### Task 6: The roundup

**Files:**
- Modify: `app/deals.py`
- Test: `tests/test_deal_roundup.py`

**Interfaces:**
- Consumes: `is_live` (Task 3); `learn`, `score`, `Snapshot`, `Rated`, `Score` (Task 4); `send_message(..., per_row=2)` (Task 5).
- Produces:

```python
RATING_BUTTONS = (("🔥 Great", "g"), ("👍 Good", "o"), ("👎 Not for me", "n"), ("💸 Overpriced", "p"))
RATING_NAMES = {"g": "🔥 Great", "o": "👍 Good", "n": "👎 Not for me", "p": "💸 Overpriced"}
FIRST_WINDOW = timedelta(days=7)
MAX_DEAL_CHARS = 4000

def buttons(node_id: int) -> list[tuple[str, str]]          # callback data deal:<id>:<letter>
def learned(conn, now, config) -> Learned                     # reads deal_ratings joined to deals
def ranked(conn, since: datetime, now, config) -> list[tuple[int, Score]]   # best first, total > 0
def deal_text(conn, node_id: int) -> str
def send_roundup(conn, telegram, chat_id, kind: str, now, config) -> int | None   # roundup id, None if heading failed
def roundup_due(conn, now, timezone: str, config) -> bool
def window_start(conn, now) -> datetime
```

Rules from the spec, decided here:
- `window_start` is the last `kind = 'scheduled'` roundup's `sent_at`, or `now - FIRST_WINDOW`.
- `ranked` takes deals with `first_seen_at >= since`, live by `is_live`, never in `deal_sends`, none of whose features is in `deal_blocks`, and not dropped by the send time check: a deal absent from the newest tick's snapshots whose last positive share is more than 0.15 below its best share is left out. Size is `config.roundup_size + 3 * size_offset` (the `size_step`), floored at 1.
- `roundup_due`: the due moment is the most recent `roundup_weekday` at `roundup_time` in `timezone` at or before `now`; due when no scheduled roundup has `sent_at >= due`, and `deal_state.paused` is false.
- `send_roundup` sends the heading first, the only message that notifies: `Deals this week: N` (scheduled) or `Deals so far this week: N` (now), or `No new deals cleared the bar this week.` when N is 0, and with N 0 nothing else is sent. If the heading's `TelegramError` occurs, it returns None and records nothing. Then each deal goes as its own message with `disable_notification=True`, `disable_link_preview=True`, no `parse_mode`, `buttons(node_id)`, `per_row=2`; a deal whose send fails is skipped and not recorded. Each sent deal is one `deal_sends` row with `kind='roundup'`, its text, and `score` as the `Score` fields in JSON.
- `deal_text`: title, then `<store name> · +<pos> −<neg>` (store omitted when None), then `https://www.ozbargain.com.au/node/<id>`, with the title cut to fit `MAX_DEAL_CHARS`.

- [ ] **Step 1: Write the failing tests** (seed rows with a helper `seed_deal(conn, node_id, title, first_seen, pos, neg, category=..., front=False)`)

- `test_roundup_sends_a_quiet_message_per_deal_after_one_heading`: 3 seeded deals give 4 `sendMessage` calls; only the first lacks `disable_notification`; each deal message has 4 buttons in 2 rows with data `deal:<id>:g` and so on, no `parse_mode`, and a `/node/<id>` link; 3 `deal_sends` rows, 1 `deal_roundups` row.
- `test_roundup_takes_at_most_the_size_best_first`: 12 deals with `roundup_size` 10 send the 10 highest totals in order.
- `test_roundup_skips_expired_blocked_and_already_sent_deals`.
- `test_a_deal_that_dropped_off_with_worse_votes_is_left_out`.
- `test_due_on_sunday_at_ten_melbourne_and_only_once`: `roundup_due` false at Sunday 09:59 Melbourne, true at 10:00, false after a scheduled roundup at 10:05.
- `test_a_pc_off_on_sunday_sends_on_the_first_tick_after` (Review Focus 4): last scheduled roundup a week before, `/deals now` sent Wednesday, `now` Monday 08:00; `roundup_due` is true, `window_start` is last week's scheduled `sent_at`, and deals the Wednesday `now` roundup sent are excluded.
- `test_a_failed_heading_records_nothing` and `test_a_failed_deal_message_skips_only_that_deal` (Review Focus 3, use `fake_telegram.fail_next`; for the second, fail the third call and assert 2 `deal_sends` rows and `roundup_due` now false).
- `test_an_empty_week_sends_one_line`.
- `test_a_long_title_stays_under_the_limit` (Review Focus 5): a 5,000 character title gives `len(text) <= 4000` with the link intact.
- `test_a_roundup_creates_no_run`: `SELECT count(*) FROM runs` is 0 after a roundup.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_deal_roundup.py -v`
Expected: FAIL, `cannot import name 'send_roundup'`.

- [ ] **Step 3: Implement** the functions above in `app/deals.py`.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_deal_roundup.py tests/test_deals_ingest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** `Send a weekly roundup of the best live deals, one message each`

---

### Task 7: Ratings from the buttons, and silence

**Files:**
- Create: `app/deal_commands.py`
- Modify: `app/deals.py`
- Modify: `app/telegram_webhook.py` (`_on_button` dispatches `deal:` data before the approval regex)
- Test: `tests/test_deal_ratings.py`

**Interfaces:**
- Consumes: `RATING_NAMES`, `buttons` (Task 6); `edit_message_text(..., buttons, per_row=2)` (Task 5).
- Produces:

```python
# app/deals.py
def record_rating(conn, node_id: int, chat_id: int, rating: str, now) -> tuple[int, str] | None
    # the (message_id, text) of the newest send of that deal to that chat, None when it was never sent there
def record_silence(conn, now, config) -> int   # silent ratings added
def button_ratings(conn) -> int                 # distinct deals rated with a button (silent = false)

# app/deal_commands.py
DEAL_BUTTON = re.compile(r"^deal:(\d+):([gonp])$")
def on_deal_button(database_url: str, telegram: TelegramClient | None, chat_id: int,
                   callback_id: str, data: str, now: datetime) -> None   # sync, run in a threadpool
```

`record_rating` upserts `deal_ratings` with `silent = false`, so a later press replaces the earlier rating and a press replaces a silent one. `record_silence` inserts `('n', silent = true)` for each deal sent at least `silence_days` before `now`, with no rating, and `is_live` at `now`. An expired one gets nothing. The webhook's chat check stays in `_on_button`; `on_deal_button` edits the deal's message to its text plus `\n\nRated: <name>` with the four buttons kept, and answers the callback `Saved: <name>`. A Telegram error is logged and swallowed, and the rating stands.

- [ ] **Step 1: Write the failing tests** (webhook tests use the `bot` fixture shape from `tests/test_telegram_webhook.py`, posting a `callback_query` update)

- `test_a_press_records_the_rating_and_edits_in_place_keeping_buttons`: after a roundup, a press `deal:<id>:g` from the allowed chat gives one `deal_ratings` row `g`, one `editMessageText` whose text ends `Rated: 🔥 Great` and whose `reply_markup` has the four buttons, and one `answerCallbackQuery` with `Saved: 🔥 Great`.
- `test_a_later_press_replaces_the_rating`: `g` then `p` leaves one row, `p`.
- `test_a_press_from_another_chat_changes_nothing`.
- `test_a_press_on_a_deal_never_sent_changes_nothing`.
- `test_approval_buttons_still_work`: run `PYTEST tests/test_telegram_webhook.py tests/test_approvals.py` unchanged.
- `test_silence_counts_after_seven_days_for_a_live_deal_only`: sent 6 days ago gives nothing; 7 days and live gives one silent `n`; 7 days and expired gives nothing; rated with a button gives nothing.
- `test_silence_never_counts_toward_alerts`: 31 silent ratings give `button_ratings == 0`.
- `test_a_press_after_silence_replaces_it`: silent then a `g` press gives `silent = false`, `g`, and `button_ratings == 1`.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_deal_ratings.py -v`
Expected: FAIL, `No module named 'app.deal_commands'`.

- [ ] **Step 3: Implement** the functions above, and in `_on_button` call `run_in_threadpool(on_deal_button, ...)` when `DEAL_BUTTON` matches, after the allowed chat check.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_deal_ratings.py tests/test_telegram_webhook.py tests/test_approvals.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** `Learn from the rating buttons and from a week of silence`

---

### Task 8: Instant alerts

**Files:**
- Modify: `app/deals.py`
- Test: `tests/test_deal_alerts.py`

**Interfaces:**
- Consumes: `ranked`-style candidate filtering, `learned`, `deal_text`, `buttons` (Task 6); `button_ratings` (Task 7).
- Produces: `send_alerts(conn, telegram, chat_id, now, config) -> list[int]` (node ids sent) and `alert_bar(conn, config) -> float` (`config.alert_bar + bar_offset * config.bar_step`; `/deals less` raises `bar_offset`, so fewer alerts).

Candidates are deals seen on the newest tick, live, unsent, unblocked, with `total >= alert_bar`. While `button_ratings < config.alerts_after` or paused, nothing is sent and each candidate is upserted into `deal_would_alert` (keeping `first_at`). Once on, each candidate goes as one message that notifies normally, with the four buttons, and is recorded in `deal_sends` with `kind='alert'`, so `ranked` already leaves it out of the roundup.

- [ ] **Step 1: Write the failing tests**

- `test_alerts_stay_off_before_thirty_ratings_and_log_would_be_alerts`: 29 button ratings and a deal above the bar send nothing and add one `deal_would_alert` row.
- `test_alerts_switch_on_at_thirty_distinct_deals`: 29 deals rated with a button, one of them pressed twice, still leaves alerts off; a 30th distinct deal rated turns them on, and a deal above the bar then goes as one message without `disable_notification`, with the four buttons.
- `test_a_deal_below_the_bar_is_not_alerted`.
- `test_an_alerted_deal_is_not_in_the_roundup`.
- `test_an_alert_is_sent_once`: two ticks send one message.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_deal_alerts.py -v`
Expected: FAIL, `cannot import name 'send_alerts'`.

- [ ] **Step 3: Implement** in `app/deals.py`.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_deal_alerts.py tests/test_deal_roundup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** `Send an instant alert for a strong match once thirty deals are rated`

---

### Task 9: The `/deals` commands

**Files:**
- Modify: `app/deal_commands.py`
- Modify: `app/telegram_webhook.py` (`_answer` routes `/deals`)
- Test: `tests/test_deal_commands.py`

**Interfaces:**
- Consumes: `send_roundup` (Task 6), `explain`, `learned` (Tasks 4 and 6), `alert_bar` (Task 8).
- Produces: `answer_deals(database_url: str, telegram: TelegramClient | None, chat_id: int, argument: str, config: DealsConfig, now: datetime) -> str | None` (the reply text; None when the command already sent its own messages, as `now` does). `_answer` calls it with `run_in_threadpool` and `request.app.state.mercury.deals`.

Replies (exact copy):
- no argument or unknown: `Usage: /deals more | less | never <name> | allow <name> | why | now | off | on`
- `more`: `Roundup size <n>, alert bar <x>.` after `size_offset += 1`, `bar_offset -= 1`. `less` the reverse, size floored at 1.
- `never <text>` and `allow <text>`: case-insensitive match of `<text>` against `deal_feature_names.name` or the key's slug (after `cat:`, `store:`, `tag:`). Each match is blocked (or unblocked). Reply `Blocked: <name> (category), <name> (store).` or `Allowed again: ...`. No match: `Nothing called <text>. Closest: <up to 5 names>.` using `difflib.get_close_matches`, and nothing is recorded.
- `why`: `explain` of the newest `deal_sends` row's stored score, headed by its title. With none: `No deal sent yet.`
- `now`: `send_roundup(kind='now')`; returns None, or `Could not send the roundup.` when it returns None.
- `off` / `on`: `Deals paused.` / `Deals on.`
- When `config.enabled` is false: `The deal finder is off in mercury.yaml.` for every subcommand.

- [ ] **Step 1: Write the failing tests** (through the webhook `bot` fixture, so the allowlist and routing are covered)

- `test_more_and_less_move_size_by_three_and_the_bar_by_one_step`.
- `test_less_never_takes_the_size_below_one`.
- `test_never_blocks_every_kind_that_matches_and_names_them`: `/deals never computing` with a category `Computing` and a tag `computing` blocks both and names both.
- `test_never_with_no_match_lists_the_closest_and_records_nothing`.
- `test_allow_undoes_never`.
- `test_why_shows_the_numbers_for_the_last_deal_sent`.
- `test_now_sends_the_roundup_and_leaves_sunday_due`.
- `test_off_stops_roundups_and_alerts_and_on_resumes`.
- `test_deals_from_another_chat_gets_no_reply`.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_deal_commands.py -v`
Expected: FAIL, `cannot import name 'answer_deals'`.

- [ ] **Step 3: Implement** `answer_deals` and the `_answer` route.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_deal_commands.py tests/test_telegram_webhook.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** `Steer the deal finder from Telegram with /deals`

---

### Task 10: Wire it into the tick, retention, privacy and the README

**Files:**
- Modify: `app/deals.py` (add `tick`)
- Modify: `app/scheduler.py` (`main` calls `tick`; module docstring gains one paragraph)
- Modify: `app/cleanup.py`
- Modify: `README.md`, `docs/` only where a section lists what the scheduler does
- Test: `tests/test_deals_tick.py`, `tests/test_cleanup.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `tick(conn, settings: Settings, config: MercuryConfig, telegram: TelegramClient | None, now: datetime | None = None) -> None`. It does nothing when `config.deals.enabled` is false or `config.telegram_chat_id` is None. Otherwise, in order: `fetch_and_ingest`, `record_silence`, `send_roundup(kind='scheduled')` when `roundup_due`, `send_alerts`. Any exception is logged by class name only and the tick goes on, as `advance_review_notes` does. In `scheduler.main` it runs after `schedule_flight_watch` and before `run_cleanup`.

Retention added to `run_cleanup`: snapshots older than `event_bodies_days` go; deals never sent with `last_seen_at` older than `event_bodies_days` go (snapshots and `deal_would_alert` by cascade); sent deals, their sends and ratings go after `runs_days`, sends and ratings first. Add a sentence to the module docstring.

- [ ] **Step 1: Write the failing tests**

- `test_tick_does_nothing_when_disabled`: no request reaches `FakeOzBargain`.
- `test_tick_fetches_records_silence_and_sends_a_due_roundup`: one tick at Sunday 10:00 Melbourne against both fakes stores the feed's deals and sends the heading plus each deal.
- `test_a_failing_deal_step_does_not_stop_the_tick`: monkeypatch `app.deals.send_alerts` to raise; `tick` returns and the roundup was still sent.
- `test_the_run_list_and_runs_command_show_no_deal`: after a tick and a rating, `GET /` (the run list API it reads) and `/runs` contain no deal title, and `runs` has no rows.
- `test_cleanup_drops_old_snapshots_and_unsent_deals_and_keeps_rated_ones` in `tests/test_cleanup.py`.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_deals_tick.py tests/test_cleanup.py -v`
Expected: FAIL, `cannot import name 'tick'`.

- [ ] **Step 3: Implement `tick`, the `scheduler.main` call and the cleanup statements.**

- [ ] **Step 4: Run the whole suite and ruff**

Run: `PYTEST` then `wsl -e bash -lc "cd /mnt/c/Projects/agent-runs && UV_PROJECT_ENVIRONMENT=/tmp/mercury-venv uv run --frozen ruff check && uv run --frozen ruff format --check"`
Expected: all pass, ruff clean.

- [ ] **Step 5: Write the README section** `## Deals from OzBargain`, placed after the flight watch section. It covers what is fetched and how often, the formula's location (`app/deal_score.py`), the four buttons, silence, alerts after 30, the `/deals` commands, and the privacy rule, in the repo's writing rules (numbers, no dashes, no banned words). It names no real deal. Add one claims row: `A weekly OzBargain roundup is ranked by votes and learned ratings, and a rating changes the next ranking | tests/test_deal_score.py, tests/test_deal_roundup.py and tests/test_deal_ratings.py, against the fake Telegram and a fake OzBargain | green`, only after Step 4 is green.

- [ ] **Step 6: Commit** `Read OzBargain on every scheduler tick, with retention and a README section`

- [ ] **Step 7: Stop the test database** with `wsl -e docker stop mercury-test-db`.
