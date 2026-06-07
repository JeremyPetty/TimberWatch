# sprint3.py
import os
import psycopg2
from psycopg2.extras import RealDictCursor


DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


SQL = """

-- =========================================================
-- Sprint 3: Topic Analytics Layer
-- =========================================================

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_motions_primary_topic
ON motions (primary_topic);

CREATE INDEX IF NOT EXISTS idx_motions_meeting_date
ON motions (meeting_date);

CREATE INDEX IF NOT EXISTS idx_motions_vote_result
ON motions (vote_result);

CREATE INDEX IF NOT EXISTS idx_motions_significance
ON motions (significance_score);

CREATE INDEX IF NOT EXISTS idx_motions_controversy
ON motions (controversy_score);


-- =========================================================
-- View: topic analytics summary
-- Used by /topics upgraded dashboard
-- =========================================================

CREATE OR REPLACE VIEW v_topic_analytics AS
SELECT
    COALESCE(NULLIF(TRIM(primary_topic), ''), 'Uncategorized') AS topic,

    COUNT(*) AS motion_count,

    COUNT(*) FILTER (
        WHERE LOWER(COALESCE(vote_result, '')) IN ('passed', 'pass', 'approved', 'carried')
    ) AS passed_count,

    COUNT(*) FILTER (
        WHERE LOWER(COALESCE(vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost')
    ) AS failed_count,

    COUNT(*) FILTER (
        WHERE COALESCE(controversy_score, 0) >= 2
    ) AS controversial_count,

    COUNT(*) FILTER (
        WHERE COALESCE(significance_score, 0) >= 2
    ) AS significant_count,

    ROUND(AVG(COALESCE(significance_score, 0))::numeric, 2) AS avg_significance,

    ROUND(AVG(COALESCE(controversy_score, 0))::numeric, 2) AS avg_controversy,

    ROUND(AVG(COALESCE(classification_confidence, 0))::numeric, 4) AS avg_confidence,

    ROUND(
        (
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(vote_result, '')) IN ('passed', 'pass', 'approved', 'carried')
            )::numeric
            / NULLIF(COUNT(*), 0)
        ) * 100,
        2
    ) AS pass_rate,

    ROUND(
        (
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost')
            )::numeric
            / NULLIF(COUNT(*), 0)
        ) * 100,
        2
    ) AS failure_rate,

    ROUND(
        (
            AVG(COALESCE(significance_score, 0))
            + AVG(COALESCE(controversy_score, 0))
            + (
                COUNT(*) FILTER (
                    WHERE LOWER(COALESCE(vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost')
                )::numeric
                / NULLIF(COUNT(*), 0)
            ) * 5
        )::numeric,
        2
    ) AS importance_score

FROM motions
GROUP BY COALESCE(NULLIF(TRIM(primary_topic), ''), 'Uncategorized');


-- =========================================================
-- View: topic trends by year
-- Used by topic detail pages
-- =========================================================

CREATE OR REPLACE VIEW v_topic_yearly_trends AS
SELECT
    COALESCE(NULLIF(TRIM(primary_topic), ''), 'Uncategorized') AS topic,
    EXTRACT(YEAR FROM meeting_date)::int AS year,
    COUNT(*) AS motion_count,

    COUNT(*) FILTER (
        WHERE LOWER(COALESCE(vote_result, '')) IN ('passed', 'pass', 'approved', 'carried')
    ) AS passed_count,

    COUNT(*) FILTER (
        WHERE LOWER(COALESCE(vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost')
    ) AS failed_count,

    COUNT(*) FILTER (
        WHERE COALESCE(controversy_score, 0) >= 2
    ) AS controversial_count,

    COUNT(*) FILTER (
        WHERE COALESCE(significance_score, 0) >= 2
    ) AS significant_count

FROM motions
WHERE meeting_date IS NOT NULL
GROUP BY
    COALESCE(NULLIF(TRIM(primary_topic), ''), 'Uncategorized'),
    EXTRACT(YEAR FROM meeting_date)::int;


-- =========================================================
-- View: most important motions
-- Used by topic detail pages
-- =========================================================

CREATE OR REPLACE VIEW v_important_motions AS
SELECT
    m.*,
    (
        COALESCE(m.significance_score, 0)
        + COALESCE(m.controversy_score, 0)
        + CASE
            WHEN LOWER(COALESCE(m.vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost')
            THEN 5
            ELSE 0
          END
    ) AS importance_score
FROM motions m;


-- =========================================================
-- View: failed motions by topic
-- =========================================================

CREATE OR REPLACE VIEW v_failed_motions_by_topic AS
SELECT *
FROM v_important_motions
WHERE LOWER(COALESCE(vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost');


-- =========================================================
-- View: controversial motions by topic
-- =========================================================

CREATE OR REPLACE VIEW v_controversial_motions_by_topic AS
SELECT *
FROM v_important_motions
WHERE COALESCE(controversy_score, 0) >= 2;


-- =========================================================
-- View: significant motions by topic
-- =========================================================

CREATE OR REPLACE VIEW v_significant_motions_by_topic AS
SELECT *
FROM v_important_motions
WHERE COALESCE(significance_score, 0) >= 2;

"""


def run():
    print("Starting Sprint 3 database upgrade...")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SQL)
        conn.commit()

    print("Sprint 3 database upgrade complete.")
    print("")
    print("Created or updated:")
    print("- v_topic_analytics")
    print("- v_topic_yearly_trends")
    print("- v_important_motions")
    print("- v_failed_motions_by_topic")
    print("- v_controversial_motions_by_topic")
    print("- v_significant_motions_by_topic")


if __name__ == "__main__":
    run()
