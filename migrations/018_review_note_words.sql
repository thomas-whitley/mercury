-- The pull request for a note chore leads with the reviewer's words
-- (docs/superpowers/specs/2026-10-19-review-notes-chores-design.md). The worker
-- has no Cloudflare token, so the scheduler copies the words here when it
-- starts the chore, capped as the instruction caps them, and the worker reads
-- them by run id. They go into the pull request on the site's repo and nowhere
-- else: not a log line, not an error and not GET /runs.
ALTER TABLE review_notes
    ADD COLUMN note_body   text,
    ADD COLUMN note_anchor text,
    ADD COLUMN note_quote  text;
