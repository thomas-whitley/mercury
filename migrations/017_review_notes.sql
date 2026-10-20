-- Review notes left on a website become repo chores (docs/superpowers/specs/
-- 2026-10-19-review-notes-chores-design.md). review_notes is what Mercury has
-- seen of each note, keyed by the note's id in the site's D1 database. The
-- note's own text is not copied here; migration 018 adds the columns that
-- hold it for the pull request, and app/cleanup.py clears them.
ALTER TABLE runs DROP CONSTRAINT runs_source_check;
ALTER TABLE runs ADD CONSTRAINT runs_source_check
    CHECK (source IN ('telegram', 'mcp', 'n8n', 'api', 'scheduler', 'eval', 'bank', 'review_note'));

-- run_id is set null, rather than blocking, when the retention cleanup deletes
-- an old run.
CREATE TABLE review_notes (
    note_id            integer PRIMARY KEY,
    host               text NOT NULL,
    page               text NOT NULL,
    note_updated_at    text NOT NULL,
    state              text NOT NULL CHECK (state IN
        ('chore', 'question', 'waiting', 'reported', 'merged', 'closed', 'gone', 'preview', 'capped')),
    run_id             uuid REFERENCES runs (id) ON DELETE SET NULL,
    pr_url             text,
    pr_opened_ticks    integer NOT NULL DEFAULT 0,
    preview_url        text,
    live_check_id      uuid,
    preview_check_id   uuid,
    message_id         bigint,
    edited             boolean NOT NULL DEFAULT false,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX review_notes_page_state ON review_notes (page, state);
CREATE INDEX review_notes_run ON review_notes (run_id);
