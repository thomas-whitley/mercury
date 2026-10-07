-- Phase 2's escalation ladder. A chore that cannot finish on a free model
-- ends escalated with a reason. hint is the advice an advised rerun carries
-- (source_run_id names the run it advises). escalation_message_id is the
-- Telegram message a reply to which becomes a hint. needs_claude marks a
-- chore whose second advised rerun also failed. Eval chores are source eval,
-- so their escalations reach the report and never Telegram.
ALTER TABLE runs ADD COLUMN escalation_reason text;
ALTER TABLE runs ADD COLUMN hint text;
ALTER TABLE runs ADD COLUMN escalation_message_id bigint;
ALTER TABLE runs ADD COLUMN needs_claude boolean NOT NULL DEFAULT false;

ALTER TABLE runs DROP CONSTRAINT runs_source_check;
ALTER TABLE runs ADD CONSTRAINT runs_source_check
    CHECK (source IN ('telegram', 'mcp', 'n8n', 'api', 'scheduler', 'eval'));

CREATE INDEX runs_escalated_idx ON runs (created_at DESC) WHERE status = 'escalated';
