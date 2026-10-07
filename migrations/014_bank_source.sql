-- Phase 5 (decision 27 of docs/build-brief-evals.md). Bank chores are quiet
-- in every way eval chores are: no Telegram, no outage retry, no place in the
-- report's escalations. The rescue script in part 5b reads them itself.
ALTER TABLE runs DROP CONSTRAINT runs_source_check;
ALTER TABLE runs ADD CONSTRAINT runs_source_check
    CHECK (source IN ('telegram', 'mcp', 'n8n', 'api', 'scheduler', 'eval', 'bank'));
