CREATE SCHEMA IF NOT EXISTS research;

CREATE TABLE IF NOT EXISTS research.expert_annotations (
    annotation_id text PRIMARY KEY,
    symbol text NOT NULL,
    timeframe text NOT NULL,
    start_time timestamptz NOT NULL,
    end_time timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    expert_source text NOT NULL CHECK (expert_source = 'MANUAL'),
    point_count integer NOT NULL CHECK (point_count >= 0),
    notes text
);

CREATE TABLE IF NOT EXISTS research.expert_annotation_points (
    annotation_id text NOT NULL REFERENCES research.expert_annotations(annotation_id) ON DELETE CASCADE,
    point_index integer NOT NULL CHECK (point_index >= 0),
    timestamp timestamptz NOT NULL,
    price numeric NOT NULL,
    snap_source text NOT NULL CHECK (snap_source IN ('NONE','HIGH','LOW')),
    PRIMARY KEY (annotation_id, point_index)
);

CREATE INDEX IF NOT EXISTS expert_annotation_points_timestamp_idx
ON research.expert_annotation_points(timestamp);
