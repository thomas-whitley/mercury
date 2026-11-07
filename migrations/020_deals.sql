-- The deal finder (docs/superpowers/specs/2026-10-23-deal-finder-design.md).
-- These tables hold the owner's ratings and the deals sent. Nothing that
-- serves the run list at /, /runs, the event stream or the MCP tools may read
-- them, and no deal is ever a run.

-- One row per OzBargain node seen in either feed. category and store are
-- feature keys ("cat:computing", "store:amazon-au"), tags a list of them.
CREATE TABLE deals (
    node_id       bigint PRIMARY KEY,
    title         text NOT NULL,
    posted_at     timestamptz NOT NULL,
    expires_at    timestamptz,
    flag          text,
    category      text,
    store         text,
    tags          text[] NOT NULL DEFAULT '{}',
    first_seen_at timestamptz NOT NULL,
    last_seen_at  timestamptz NOT NULL
);

-- How the feed displays each feature key, for messages and /deals never.
CREATE TABLE deal_feature_names (
    key  text PRIMARY KEY,
    name text NOT NULL
);

-- The votes as each tick saw them, the deal's community signal over time.
CREATE TABLE deal_snapshots (
    node_id    bigint NOT NULL REFERENCES deals ON DELETE CASCADE,
    seen_at    timestamptz NOT NULL,
    votes_pos  integer NOT NULL,
    votes_neg  integer NOT NULL,
    comments   integer NOT NULL,
    front_page boolean NOT NULL,
    PRIMARY KEY (node_id, seen_at)
);

CREATE TABLE deal_roundups (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind               text NOT NULL CHECK (kind IN ('scheduled', 'now')),
    sent_at            timestamptz NOT NULL,
    heading_message_id bigint
);

-- Every deal message sent, with its text (a rating edits it in place) and
-- the score that picked it (/deals why).
CREATE TABLE deal_sends (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    node_id    bigint NOT NULL REFERENCES deals,
    kind       text NOT NULL CHECK (kind IN ('roundup', 'alert')),
    roundup_id bigint REFERENCES deal_roundups,
    chat_id    bigint NOT NULL,
    message_id bigint NOT NULL,
    text       text NOT NULL,
    score      jsonb NOT NULL,
    sent_at    timestamptz NOT NULL
);
CREATE INDEX deal_sends_node ON deal_sends (node_id, sent_at DESC);

-- One rating per deal, the latest press. silent marks a week of silence,
-- which a press replaces.
CREATE TABLE deal_ratings (
    node_id  bigint PRIMARY KEY REFERENCES deals,
    rating   text NOT NULL CHECK (rating IN ('g', 'o', 'n', 'p')),
    silent   boolean NOT NULL DEFAULT false,
    rated_at timestamptz NOT NULL
);

-- Feature keys /deals never stopped.
CREATE TABLE deal_blocks (
    key        text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Deals that would have been alerts while alerts are off, to set the bar.
CREATE TABLE deal_would_alert (
    node_id  bigint PRIMARY KEY REFERENCES deals ON DELETE CASCADE,
    first_at timestamptz NOT NULL,
    total    real NOT NULL
);

-- One row: what /deals changed, and the feeds' health.
CREATE TABLE deal_state (
    id                 integer PRIMARY KEY CHECK (id = 1),
    paused             boolean NOT NULL DEFAULT false,
    size_offset        integer NOT NULL DEFAULT 0,
    bar_offset         integer NOT NULL DEFAULT 0,
    last_fetch_ok_at   timestamptz,
    feed_down_notified boolean NOT NULL DEFAULT false,
    created_at         timestamptz NOT NULL DEFAULT now()
);
INSERT INTO deal_state (id) VALUES (1);
