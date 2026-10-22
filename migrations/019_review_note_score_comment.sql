-- The preview score warning goes on the note's pull request as one comment
-- (docs/superpowers/specs/2026-10-19-review-notes-chores-design.md, "The
-- Lighthouse comparison"). score_comment is the comment's text, set when the
-- note's message is sent and cleared once the comment is posted. It holds the
-- warning and both scores and never the note's words. score_comment_tries
-- bounds the retries after a failed post.
ALTER TABLE review_notes
    ADD COLUMN score_comment       text,
    ADD COLUMN score_comment_tries integer NOT NULL DEFAULT 0;
