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
-- Uses motion_ai_analysis.priority_area instead of motions.primary_topic
-- =========================================================

CREATE INDEX IF NOT EXISTS idx_motions_meeting_date
ON motions (meeting_date);

CREATE INDEX IF NOT EXISTS idx_motions_vote_result
ON motions (vote_result);

CREATE INDEX IF NOT EXISTS idx_motion_ai_analysis_motion_id
ON motion_ai_analysis (motion_id);

CREATE INDEX IF NOT EXISTS idx_motion_ai_analysis_priority_area
ON motion_ai_analysis (priority_area);


-- Latest AI row per motion, in case a motion was analyzed more than once
CREATE OR REPLACE VIEW v_latest_motion_ai AS
SELECT DISTINCT ON (motion_id)
    *
FROM motion_ai_analysis
ORDER BY motion_id, analyzed_at DESC NULLS LAST, id DESC;


CREATE OR REPLACE VIEW v_topic_analytics AS
SELECT
    COALESCE(NULLIF(TRIM(ai.priority_area), ''), 'Uncategorized') AS topic,

    COUNT(*) AS motion_count,

    COUNT(*) FILTER (
        WHERE LOWER(COALESCE(m.vote_result, '')) IN ('passed', 'pass', 'approved', 'carried')
    ) AS passed_count,

    COUNT(*) FILTER (
        WHERE LOWER(COALESCE(m.vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost')
    ) AS failed_count,

    COUNT(*) FILTER (
        WHERE COALESCE(ai.controversy_score, 0) >= 2
    ) AS controversial_count,

    COUNT(*) FILTER (
        WHERE COALESCE(ai.significance_score, 0) >= 2
    ) AS significant_count,

    ROUND(AVG(COALESCE(ai.significance_score, 0))::numeric, 2) AS avg_significance,

    ROUND(AVG(COALESCE(ai.controversy_score, 0))::numeric, 2) AS avg_controversy,

    ROUND(
        (
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(m.vote_result, '')) IN ('passed', 'pass', 'approved', 'carried')
            )::numeric / NULLIF(COUNT(*), 0)
        ) * 100,
        2
    ) AS pass_rate,

    ROUND(
        (
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(m.vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost')
            )::numeric / NULLIF(COUNT(*), 0)
        ) * 100,
        2
    ) AS failure_rate,

    ROUND(
        (
            AVG(COALESCE(ai.significance_score, 0))
            + AVG(COALESCE(ai.controversy_score, 0))
            + (
                COUNT(*) FILTER (
                    WHERE LOWER(COALESCE(m.vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost')
                )::numeric / NULLIF(COUNT(*), 0)
            ) * 5
        )::numeric,
        2
    ) AS importance_score

FROM motions m
LEFT JOIN v_latest_motion_ai ai
    ON ai.motion_id = m.id
GROUP BY COALESCE(NULLIF(TRIM(ai.priority_area), ''), 'Uncategorized');


CREATE OR REPLACE VIEW v_topic_yearly_trends AS
SELECT
    COALESCE(NULLIF(TRIM(ai.priority_area), ''), 'Uncategorized') AS topic,
    EXTRACT(YEAR FROM m.meeting_date)::int AS year,

    COUNT(*) AS motion_count,

    COUNT(*) FILTER (
        WHERE LOWER(COALESCE(m.vote_result, '')) IN ('passed', 'pass', 'approved', 'carried')
    ) AS passed_count,

    COUNT(*) FILTER (
        WHERE LOWER(COALESCE(m.vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost')
    ) AS failed_count,

    COUNT(*) FILTER (
        WHERE COALESCE(ai.controversy_score, 0) >= 2
    ) AS controversial_count,

    COUNT(*) FILTER (
        WHERE COALESCE(ai.significance_score, 0) >= 2
    ) AS significant_count

FROM motions m
LEFT JOIN v_latest_motion_ai ai
    ON ai.motion_id = m.id
WHERE m.meeting_date IS NOT NULL
GROUP BY
    COALESCE(NULLIF(TRIM(ai.priority_area), ''), 'Uncategorized'),
    EXTRACT(YEAR FROM m.meeting_date)::int;


CREATE OR REPLACE VIEW v_important_motions AS
SELECT
    m.*,
    ai.priority_area,
    ai.significance_score,
    ai.controversy_score,
    ai.governance_flags,
    (
        COALESCE(ai.significance_score, 0)
        + COALESCE(ai.controversy_score, 0)
        + CASE
            WHEN LOWER(COALESCE(m.vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost')
            THEN 5
            ELSE 0
          END
    ) AS importance_score
FROM motions m
LEFT JOIN v_latest_motion_ai ai
    ON ai.motion_id = m.id;


CREATE OR REPLACE VIEW v_failed_motions_by_topic AS
SELECT *
FROM v_important_motions
WHERE LOWER(COALESCE(vote_result, '')) IN ('failed', 'fail', 'not passed', 'not approved', 'lost');


CREATE OR REPLACE VIEW v_controversial_motions_by_topic AS
SELECT *
FROM v_important_motions
WHERE COALESCE(controversy_score, 0) >= 2;


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
    print("Created or updated:")
    print("- v_latest_motion_ai")
    print("- v_topic_analytics")
    print("- v_topic_yearly_trends")
    print("- v_important_motions")
    print("- v_failed_motions_by_topic")
    print("- v_controversial_motions_by_topic")
    print("- v_significant_motions_by_topic")


if __name__ == "__main__":
    run()
