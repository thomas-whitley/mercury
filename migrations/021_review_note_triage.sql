-- Review note triage (docs/superpowers/specs/2026-11-13-review-note-triage-design.md).
-- A new note is sorted first ('sorting'); one that is not a website change goes to
-- Thomas as a card ('asked'). Dismiss sets 'dismiss' and the scheduler marks the note
-- done in D1, then 'dismissed'. card_message_id is the Telegram message carrying the
-- note's buttons, and card_updated_at the note's updated_at when it was sent, so a
-- press on a card for words since edited changes nothing. held_by_page is set when a
-- note queued for a chore waited for another note on its page.
ALTER TABLE review_notes DROP CONSTRAINT review_notes_state_check;
ALTER TABLE review_notes ADD CONSTRAINT review_notes_state_check CHECK (state IN
    ('chore', 'question', 'waiting', 'reported', 'merged', 'closed', 'gone', 'preview', 'capped',
     'sorting', 'asked', 'dismiss', 'dismissed'));

ALTER TABLE review_notes ADD COLUMN card_message_id bigint;
ALTER TABLE review_notes ADD COLUMN card_updated_at text;
ALTER TABLE review_notes ADD COLUMN suggestion text;
ALTER TABLE review_notes ADD COLUMN held_by_page boolean NOT NULL DEFAULT false;
-- Thomas's hint from a reply to a card, kept until the chore it shapes starts.
ALTER TABLE review_notes ADD COLUMN hint text;
-- The note's updated_at when note_body was read. A card records this, not
-- note_updated_at, which an edit moves on while the stored words stay old.
ALTER TABLE review_notes ADD COLUMN words_at text;
