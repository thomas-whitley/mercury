-- Phase 5 (decision 29 of docs/build-brief-evals.md). The commit a repo
-- chore starts from, when it is not the tip of the default branch. NULL is
-- the tip, as every chore before this migration started.
ALTER TABLE runs ADD COLUMN base_sha text;
