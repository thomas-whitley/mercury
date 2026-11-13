# Review note triage: design

Date: 2026-11-13. Status: agreed with Thomas in chat, not yet planned.
Builds on `docs/superpowers/specs/2026-10-19-review-notes-chores-design.md` (how notes become chores today).

## Why

On 2026-11-13 Luke's note "Should we get a beer this weekend" (left 2026-10-28 on ludoelectrical.com `/`) became a repo chore. The agent couldn't make a site change from it and escalated. The Telegram escalation showed the raw chore prompt, didn't say how old the note was, and offered no way to drop it. Thomas then typed into the chat, which can't see escalations, and went round in circles. The note now sits in `question`, holding the homepage, and no Telegram action can clear it.

When a note needs Thomas, he wants to know at a glance **what it is, how old it is, and what he can do**, and to act with one tap.

## Goals

1. **A sorting step before the agent.** One model call per new note: is it a website change?
   - A clear change goes to the agent, as now. Thomas still hears only through the PR.
   - Anything else (not a change, or unsure) skips the agent and goes to Thomas.
2. **One message format** for every note that needs Thomas. It's used both for notes the sorting step sends him and for chores the agent escalates. It has:
   - **What it is:** the reviewer's name (`review_notes.reviewer_name`), the page, and the note's words. The tapped element or highlighted text goes in only when present and short.
   - **How old:** "written 28 Oct, 16 days ago", from the note's `updated_at`. If Mercury picked the note up more than a day after it was written, add why, e.g. "held up behind Luke's 'easy jobs' note on the same page" or "the daily limit was reached". If the reason isn't known, say "picked up late".
   - **Suggestion:** one line written by the sorting step's model. Plain text, about 150 characters at most, advice only.
3. **Buttons** on that message:
   - **Dismiss** closes the note: it's no longer tracked in Mercury, the page is free for the next note, and the note is marked done in D1 so it leaves the reviewer's page. This is the same D1 "done" a merged PR sets today.
   - **Treat as a change** starts the agent on the note straight away. It's shown on sorted notes only; an escalated chore already ran.
   - **Reply-to-hint** keeps working on escalations, as today (`app/advice.py`). On a sorted note, a reply with text works like Treat as a change with that hint.
4. **Digest:** the existing "Review notes: N waiting on you" line names each waiting note and how long it has waited, e.g. "Luke's beer note, waiting 2 days". There are no other reminders.

## Non-goals

- Any change to the reviewer's side of the site, or how notes are left.
- A smarter general chat (`app/chat.py`), or a `/dismiss` command for other run types.
- Undo for Dismiss. If it's tapped by mistake, the reviewer can leave the note again.
- Anything Ludo-specific. Build it on the shared `review_notes` setup, so any site with review notes gets it.

## Anti-goals (failures even if it works)

- Mercury dismisses, closes or edits a note on its own judgement. Only Thomas's tap does that.
- Thomas dismisses words he hasn't seen. If the note's `updated_at` changed after the message was sent, Dismiss doesn't act. Mercury replies "Luke changed this note since", then shows the new text with fresh buttons.
- A note's words become an action. The note reaches the model as data (same rule as the chore prompt), and the model's output is a label plus the capped suggestion line. Buttons are fixed. The suggestion can't add a button or a link.
- A model outage messages Thomas. If the sorting call fails, the note stays untouched and the next scheduler tick tries again.

## Constraints

- The sorting step uses the chat model ladder (currently `[gemini]`). Local's JSON mode only fits chore replies.
- Sorting doesn't count toward `review_notes.daily_cap`. Only agent runs do.
- **Sorting runs as soon as a note arrives**, even if its page is busy or the daily cap is full (Thomas, after the builder check). A note sorted as "not a change" goes to Thomas at once and **doesn't hold the page**, because it will never touch the site. Only notes heading to the agent queue for their page, as today. An escalated chore still holds its page until Thomas acts, because its run already touched the page's branch.
- The existing settle rules still apply: a note that leaves D1 becomes `gone`, and an edited note is flagged, not rerun.
- Telegram's message limit: reuse `app/escalation.py`'s fitting (`MESSAGE_LIMIT`, `_fit`).

## Decided by Thomas

The sorting step comes before the agent. On a model outage, the note waits an hour. Age is shown as written above. The suggestion line comes from the model. Treat as a change starts immediately, and hints come by reply. Dismiss has no undo. Escalations use the same format. It works across all review-note sites. Sorting is outside the daily cap. Dismiss on a stale message shows the new text instead. "Written" means the last edit. Clear changes get no extra message. The suggestion is capped and plain. Waiting notes are listed in the digest only. The live note 5 (the beer note, now in `question`) is left as the first real test of Dismiss.

## Claude's calls (from the builder check; Thomas to confirm on reading)

- **Escalation content:**
  - An escalated chore's message keeps today's content: the agent's question, the end of the test output, the run link and the hint instructions.
  - The new "what / how old" header and the Dismiss button are added to it.
  - Its suggestion line is the agent's own question. There's no second model call, so `announce_escalation` stays model-free and an outage can't block or trigger an escalation.
- **Treat as a change** goes through the normal start path and respects `daily_cap`, the day's run limit and the token cap. If the day is full, the note becomes `capped` and starts when there's room, as today. Its run counts toward the cap like any note chore.
- **Dismiss while work is moving:**
  - Dismiss acts only when no run is in progress for the note and no PR is open from it.
  - Otherwise it changes nothing and replies with what's in progress, e.g. "A rerun is going; close its PR to drop the note".
  - It never cancels runs or closes PRs.
  - A button on an old message acts on the note's current state, with the same check.
- **Digest line:**
  - Built in code, not by the digest model, so the note's words never enter a model prompt there.
  - Form: `Luke's note on / ("Should we get a beer this w…"), waiting 2 days`, with the note's first ~30 characters quoted.

## Left to the builder

- The state names and the migration (e.g. a new state for "sorted, waiting on Thomas" vs reusing `question`).
- The prompt and JSON shape for the sorting call.
- How the "why late" reason is worked out from existing rows.
- The callback data format for the buttons (follow `app/approvals.py` and `app/deal_commands.py`).
- **Note 5:** it's an escalated chore in `question`. Its escalation message predates the new format, so the builder decides how it gets a Dismiss button, e.g. a one-off resend in the new format when this ships.
