-- Phase 5 (decision 28 of docs/build-brief-evals.md). Every model call a
-- repo_chore makes, as the model saw it and as it answered, so training
-- examples are built from the prompt the model is served. seq is the step
-- the reply led to; provider is the rung that answered. A bank run's calls
-- outlive the 30 day cleanup (app/cleanup.py); the rest go then.
CREATE TABLE model_calls (
    id         bigserial PRIMARY KEY,
    run_id     uuid NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    seq        integer NOT NULL,
    provider   text,
    system     text NOT NULL,
    prompt     text NOT NULL,
    reply      text NOT NULL,
    tokens     integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX model_calls_run_idx ON model_calls (run_id, seq);
