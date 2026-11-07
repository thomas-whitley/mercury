# Deal finder

Date: 2026-10-23. Status: draft, not yet approved by Thomas.

## Why

Thomas wants to find good deals on OzBargain (ozbargain.com.au) without reading the site. He has no fixed shopping
list and does not want to describe his taste up front. He wants Mercury to send him deals, learn from how he reacts,
and get more accurate as he uses it. He will judge volume and timing once he sees real messages and adjust from
Telegram, so every number in this document is a starting value, not a decision.

This is phase 2 (shopping deals) of the `mercury-money` repo's plan, reached through Mercury's scheduler and Telegram
bot as in its phase 4. It replaces that plan's "Claude looks for current deals when asked" with a learned weekly feed.

## What Thomas sees

1. **A weekly roundup.** One Telegram message a week with the best deals posted since the last roundup that are
   still live. Each deal shows its title, price as OzBargain titles it, store, positive and negative votes, and a link
   to the OzBargain deal page. Starting values (Claude's call): Sunday at 10:00 Melbourne time, at most 10 deals.
2. **Rating buttons on every deal** (decided with Thomas, option C). Four buttons: 🔥 Great, 👍 Good, 👎 Not for me,
   💸 Overpriced. A press records the rating and the message shows which one was chosen. A later press on the same deal
   replaces the earlier rating.
3. **Instant alerts, only once it knows him** (decided with Thomas). Off at the start, because Mercury cannot know what
   is good for Thomas until he has rated enough deals. They switch on after 30 ratings (Claude's call). From then on, a
   deal that is both strong on OzBargain and a strong match for Thomas's ratings is sent on its own, on the hourly tick
   that first sees it clear the bar, with the same four buttons. A deal sent as an alert is not repeated in the
   roundup.
4. **Commands to steer it** (Claude's call, Thomas did not ask for specific ones):
   - `/deals more` and `/deals less` change the roundup size by 3 and the alert bar by one step.
   - `/deals never <category, store or tag>` stops that kind of deal completely. `/deals allow <same>` undoes it.
   - `/deals why` answers for the last deal sent: its OzBargain score, Thomas's learned weights that applied, and the
     total.
   - `/deals now` sends the roundup immediately, so Thomas can try it without waiting for Sunday.
   - `/deals off` and `/deals on` pause and resume everything.

## How it learns

The two kinds of 👎 Thomas asked for are kept separate (decided with Thomas: "both").

- **Taste.** 🔥, 👍 and 👎 Not for me adjust a weight for each feature of the deal: its OzBargain category, its store
  (the `brand` or store named in the feed), and each of its tags. 🔥 counts more than 👍. 👎 Not for me lowers the
  weights. A deal's taste score is the sum of its features' weights. A feature never rated has weight zero, so an
  untrained Mercury ranks purely on OzBargain's community signal.
- **Price.** 💸 Overpriced does not lower taste weights. It raises the bar that deals in that category must clear on
  community signal, on the reasoning that Thomas likes the kind of thing but wants a sharper price before he hears
  about it.
- **Silence.** A deal shown in a roundup and not rated within 7 days counts as a weak 👎 Not for me (Claude's call,
  confirmed by Thomas on 2026-10-31). Alerts left unrated count the same way.
- **Explainable.** Learning is plain counting with fixed step sizes, no model call, so it costs nothing and `/deals
  why` can show exactly why a deal was picked. The step sizes and the decay of old ratings are the builder's call,
  stated in config so they can be tuned without a deploy.

## Where the deals come from

OzBargain's public RSS feeds, checked on 2026-10-23:

- `https://www.ozbargain.com.au/deals/feed` lists the newest 30 deals, about 5 hours of posts on a Friday afternoon.
- `https://www.ozbargain.com.au/feed` lists the 20 deals on the front page, which OzBargain promotes on votes.

Each item carries an `ozb:meta` element with `votes-pos`, `votes-neg`, `comment-count`, `click-count`, and on about
half of items `expiry` and `starting`. Categories, tags and the brand come as `<category>` elements whose `domain`
starts `/cat/`, `/tag/` or `/brand/`. Some items carry `ozb:title-msg` with a type of `expired`, `targeted`,
`upcoming` or `longrunning`. The node id is in the `link` and the `guid`.

The scheduler Job, which already wakes every hour, fetches both feeds once per tick. Each fetch stores a snapshot of
every item's votes, so a deal seen on several ticks gets a vote history. That history, plus front page placement, is
the community signal. The exact formula (votes per hour of age, positive share, comment count, front page as a bonus)
is the builder's call, but it must be stated in one place and shown by `/deals why`.

The feeds are read once an hour, with a plain user agent that names Mercury. `robots.txt` disallows `/api/`,
`/comment/` and `/goto/`, so messages link to `/node/<id>`, never to the `/goto/` redirect, and nothing else on the
site is fetched.

Deals are dropped before scoring when they are marked `expired`, `targeted` (only for some accounts) or `upcoming`,
or when their `expiry` has passed. A deal is checked again at send time, because a roundup can pick a deal seen days
earlier. One that has since expired or dropped off both feeds with a sharply worse vote balance is left out.

## Goals

- A roundup every week with up to the configured number of live deals, ranked by community signal times learned
  taste.
- Ratings that visibly change what arrives: after Thomas marks a category 👎 a few times, it stops appearing near the
  top.
- Instant alerts that are rare and good. Once on, they should average no more than about 2 a week at the starting
  bar (Claude's call). `/deals less` lowers that.
- Zero added running cost. No model calls, no new paid resource, inside the existing hourly Job and Postgres.

## Anti-goals

- **Spam.** A Mercury that sends deals Thomas ignores week after week has failed, even if every deal is genuinely
  popular. The weekly cap, the silence-as-👎 rule and `/deals less` all exist for this.
- **A black box.** Thomas must be able to ask why any deal arrived and get an answer in numbers.
- **Stale deals.** A roundup that links to deals already expired or sold out.

## Non-goals

- Buying anything, or opening store pages on Thomas's behalf.
- Price history or price comparison against other stores (StaticICE and the like). Possible later.
- Reading OzBargain comments or deal pages beyond the two feeds.
- Using a language model to judge deals. Possible later if counting stops improving.
- Any user other than Thomas, or any chat other than the one allowed chat.

## Constraints

- Mercury's hard rules apply: $0 idle cost, free providers only, secrets never in the repo. This feature calls no
  model at all.
- Nothing personal goes in the public Mercury repo, its page or its API (a `mercury-money` rule). Thomas's ratings,
  weights and settings live only in Mercury's Postgres. Starting values that reveal nothing personal can go in
  `mercury.sample.yaml`; anything Thomas sets lives in the private config or the database. The public run list at `/`
  must not show deal titles or ratings.
- Only the allowed chat's button presses and commands count, as for approvals today. Button callback data must fit
  Telegram's 64 byte limit.
- On the home PC the scheduler is a long-running compose service (`local/compose.home.yml`), but each tick is a fresh
  process: it runs one pass, sleeps an hour and repeats. Anything an alert or roundup needs must be in the database,
  not in memory.
- Ticks are about an hour apart and drift from minute 0, and a PC that was off catches up on its first tick after
  start. The roundup is due at a local time, as the digest already is (`schedule_digest` in `app/scheduler.py`), so it
  goes out on the first tick after its due time.
- Mercury's writing rules for README and docs apply to anything this adds there.

## Settled after the builder check (Claude's calls)

- **A roundup is one message per deal** (Claude's call, after Thomas asked which was better). A short heading message comes
  first and is the only one that notifies. Each deal follows as its own message, sent with `disable_notification`,
  carrying its own four buttons. Alerts notify normally.
- **Ratings change in place.** A press edits that deal's message to show the chosen rating and keeps all four
  buttons, so Thomas can change his mind. `TelegramClient` needs an edit that re-sends the keyboard, since today's
  `edit_message_text` drops it. Callback data is `deal:<node id>:<rating letter>`, well under 64 bytes.
- **Feeds are read by the scheduler; ratings and commands are handled by the webhook.** Ranking and sending live in a
  shared module so the API can answer `/deals now` straight away. Roundups and alerts are not runs. They use their own
  tables, so no deal title or rating reaches the run list at `/`, the `/runs` command, the event stream or the MCP
  tools.
- **Roundup windows.** A sent roundup is recorded with its time. The scheduled roundup covers deals first seen since
  the last scheduled roundup (the last 7 days for the first one) and skips any deal already sent by `/deals now` or as
  an alert. `/deals now` does not move the Sunday schedule.
- **What counts.** Only deals that were sent count for learning. Deals never sent stay neutral. Silence counts as a
  weak 👎 only for a sent deal still live 7 days after it was sent. One that expired unrated counts for nothing.
  Alerts switch on after 30 distinct deals rated with a button, counting each deal once however often it was
  re-rated, and silence never counts toward the 30.
- **Taste score scale.** Category and store are one term each. Tags are averaged into one term, so a deal with 12
  tags does not outweigh one with 2.
- **`/deals never` and `/deals allow`** match case-insensitively against the display name or slug of categories,
  stores and tags seen in the feeds, and apply to every kind that matches. The reply names what matched. With no
  match the reply says so and lists the closest names. Nothing is recorded in that case.
- **Alert calibration.** While alerts are still off, every tick logs the deals that would have been alerts. By the
  time 30 ratings are in, that log shows whether the starting bar gives about 2 a week, and the bar is set from it.
- **Feed failures** do not suspend anything or send a Resume button. A failed fetch is logged and retried on the next
  tick. After 24 hours with no successful fetch, one Telegram message says so, and another says when fetching works
  again. The fetch has a 10 second timeout so it cannot hold up the rest of the tick.

## Prerequisite

None outstanding. The Azure deploy stopped on 2026-10-26, and since 2026-10-28 Mercury runs on the home PC from
`main` (`docker compose -f docker-compose.yml -f local/compose.home.yml up -d --build`). Telegram updates reach the
api through the `telegram` poller, which posts each one to `/telegram` as the webhook would, so button presses and
`/deals` commands arrive the same way. The live stack is only up while the PC is on.

## Left to the builder

- Table design, migration numbering, and whether roundups and alerts are runs with a type of their own (as `digest`
  is) or are sent by the scheduler directly.
- The community score formula, the learning step sizes, decay, and the alert bar, stated in config.
- Message layout within the content listed above.
- How long snapshots and unrated deals are kept, in line with the existing retention cleanup.
- Tests, following the repo's rule of a failing test first and the claims table filled only when green.
