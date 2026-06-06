from html import escape
from urllib.parse import urlencode


def register_sprint2_routes(app, get_cursor, layout):
    def esc(value):
        return escape(str(value or ""))

    def pct(num, den):
        if not den:
            return "0.0%"
        return f"{(num / den) * 100:.1f}%"

    def motion_topic_join_sql():
        return """
            LEFT JOIN motion_topics mt ON mt.motion_id = m.id
        """

    @app.route("/controversial-motions")
    def controversial_motions():
        with get_cursor() as cur:
            cur.execute("""
                WITH vote_counts AS (
                    SELECT
                        motion_id,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('yes','aye','y')) AS yes_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('no','nay','n')) AS no_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'abstain%') AS abstain_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'absent%') AS absent_votes,
                        COUNT(*) AS total_votes
                    FROM trustee_votes
                    GROUP BY motion_id
                ),
                topic_rollup AS (
                    SELECT
                        motion_id,
                        STRING_AGG(DISTINCT topic, ', ' ORDER BY topic) AS topics
                    FROM motion_topics
                    GROUP BY motion_id
                )
                SELECT
                    m.id,
                    m.document_id,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    COALESCE(vc.yes_votes, 0) AS yes_votes,
                    COALESCE(vc.no_votes, 0) AS no_votes,
                    COALESCE(vc.abstain_votes, 0) AS abstain_votes,
                    COALESCE(vc.absent_votes, 0) AS absent_votes,
                    COALESCE(vc.total_votes, 0) AS total_votes,
                    ABS(COALESCE(vc.yes_votes, 0) - COALESCE(vc.no_votes, 0)) AS vote_margin,
                    COALESCE(tr.topics, '') AS topics
                FROM motions m
                LEFT JOIN vote_counts vc ON vc.motion_id = m.id
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                WHERE
                    LOWER(COALESCE(m.vote_result, '')) LIKE '%fail%'
                    OR ABS(COALESCE(vc.yes_votes, 0) - COALESCE(vc.no_votes, 0)) <= 1
                    OR COALESCE(vc.abstain_votes, 0) > 0
                    OR COALESCE(vc.absent_votes, 0) > 0
                ORDER BY
                    CASE WHEN LOWER(COALESCE(m.vote_result, '')) LIKE '%fail%' THEN 0 ELSE 1 END,
                    vote_margin ASC,
                    m.meeting_date DESC NULLS LAST
                LIMIT 250
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            table_rows += f"""
            <tr>
                <td><a href="/motions/{r['id']}">Motion #{r['id']}</a></td>
                <td>{esc(r['meeting_date'])}</td>
                <td>{esc(r['vote_result'])}</td>
                <td>{r['yes_votes']}</td>
                <td>{r['no_votes']}</td>
                <td>{r['abstain_votes']}</td>
                <td>{r['absent_votes']}</td>
                <td>{r['vote_margin']}</td>
                <td>{esc(r['topics'])}</td>
                <td>{esc(r['motion_text'])[:220]}</td>
            </tr>
            """

        body = f"""
        <div class="card">
            <h2>Controversial Motions</h2>
            <p>Failed motions, close votes, abstentions, and absences.</p>
            <table>
                <thead>
                    <tr>
                        <th>Motion</th>
                        <th>Date</th>
                        <th>Result</th>
                        <th>Yes</th>
                        <th>No</th>
                        <th>Abstain</th>
                        <th>Absent</th>
                        <th>Margin</th>
                        <th>Topics</th>
                        <th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows or '<tr><td colspan="10">No controversial motions found.</td></tr>'}
                </tbody>
            </table>
        </div>
        """
        return layout("Controversial Motions", body)

    @app.route("/trustee-scorecards")
    def trustee_scorecards():
        with get_cursor() as cur:
            cur.execute("""
                WITH normalized_votes AS (
                    SELECT
                        tv.motion_id,
                        COALESCE(a.normalized_name, tv.trustee_name) AS trustee_name,
                        LOWER(TRIM(tv.vote)) AS vote
                    FROM trustee_votes tv
                    LEFT JOIN trustee_name_aliases a
                        ON LOWER(TRIM(tv.trustee_name)) = LOWER(TRIM(a.raw_name))
                ),
                motion_flags AS (
                    SELECT
                        m.id AS motion_id,
                        CASE WHEN LOWER(COALESCE(m.vote_result, '')) LIKE '%fail%' THEN 1 ELSE 0 END AS failed_motion
                    FROM motions m
                )
                SELECT
                    nv.trustee_name,
                    COUNT(*) AS total_votes,
                    COUNT(*) FILTER (WHERE nv.vote IN ('yes','aye','y')) AS yes_votes,
                    COUNT(*) FILTER (WHERE nv.vote IN ('no','nay','n')) AS no_votes,
                    COUNT(*) FILTER (WHERE nv.vote LIKE 'abstain%') AS abstain_votes,
                    COUNT(*) FILTER (WHERE nv.vote LIKE 'absent%') AS absent_votes,
                    SUM(mf.failed_motion) AS failed_motion_votes
                FROM normalized_votes nv
                LEFT JOIN motion_flags mf ON mf.motion_id = nv.motion_id
                WHERE COALESCE(nv.trustee_name, '') <> ''
                GROUP BY nv.trustee_name
                ORDER BY nv.trustee_name
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            total = r["total_votes"] or 0
            table_rows += f"""
            <tr>
                <td><a href="/trustee-scorecards/{urlencode({'name': r['trustee_name']})[5:]}">{esc(r['trustee_name'])}</a></td>
                <td>{total}</td>
                <td>{r['yes_votes']} ({pct(r['yes_votes'], total)})</td>
                <td>{r['no_votes']} ({pct(r['no_votes'], total)})</td>
                <td>{r['abstain_votes']}</td>
                <td>{r['absent_votes']}</td>
                <td>{r['failed_motion_votes']}</td>
            </tr>
            """

        body = f"""
        <div class="card">
            <h2>Enhanced Trustee Scorecards</h2>
            <table>
                <thead>
                    <tr>
                        <th>Trustee</th>
                        <th>Total</th>
                        <th>Yes</th>
                        <th>No</th>
                        <th>Abstain</th>
                        <th>Absent</th>
                        <th>Failed Motion Votes</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows or '<tr><td colspan="7">No trustee votes found.</td></tr>'}
                </tbody>
            </table>
        </div>
        """
        return layout("Trustee Scorecards", body)

    @app.route("/trustee-scorecards/<path:trustee_name>")
    def trustee_scorecard_detail(trustee_name):
        with get_cursor() as cur:
            cur.execute("""
                WITH normalized_votes AS (
                    SELECT
                        tv.motion_id,
                        COALESCE(a.normalized_name, tv.trustee_name) AS trustee_name,
                        tv.vote
                    FROM trustee_votes tv
                    LEFT JOIN trustee_name_aliases a
                        ON LOWER(TRIM(tv.trustee_name)) = LOWER(TRIM(a.raw_name))
                ),
                topic_rollup AS (
                    SELECT
                        motion_id,
                        STRING_AGG(DISTINCT topic, ', ' ORDER BY topic) AS topics
                    FROM motion_topics
                    GROUP BY motion_id
                )
                SELECT
                    m.id,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    nv.vote,
                    COALESCE(tr.topics, '') AS topics
                FROM normalized_votes nv
                JOIN motions m ON m.id = nv.motion_id
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                WHERE LOWER(TRIM(nv.trustee_name)) = LOWER(TRIM(%s))
                ORDER BY m.meeting_date DESC NULLS LAST, m.id DESC
                LIMIT 250
            """, [trustee_name])
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            table_rows += f"""
            <tr>
                <td>{esc(r['meeting_date'])}</td>
                <td><a href="/motions/{r['id']}">Motion #{r['id']}</a></td>
                <td>{esc(r['vote'])}</td>
                <td>{esc(r['vote_result'])}</td>
                <td>{esc(r['topics'])}</td>
                <td>{esc(r['motion_text'])[:250]}</td>
            </tr>
            """

        body = f"""
        <div class="card">
            <h2>Trustee Scorecard: {esc(trustee_name)}</h2>
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Motion</th>
                        <th>Vote</th>
                        <th>Result</th>
                        <th>Topics</th>
                        <th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows or '<tr><td colspan="6">No votes found for this trustee.</td></tr>'}
                </tbody>
            </table>
        </div>
        """
        return layout(f"Trustee Scorecard - {trustee_name}", body)

    @app.route("/topic-analytics")
    def topic_analytics():
        with get_cursor() as cur:
            cur.execute("""
                WITH vote_counts AS (
                    SELECT
                        motion_id,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('yes','aye','y')) AS yes_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('no','nay','n')) AS no_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'abstain%') AS abstain_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'absent%') AS absent_votes
                    FROM trustee_votes
                    GROUP BY motion_id
                )
                SELECT
                    mt.topic,
                    COUNT(DISTINCT m.id) AS motion_count,
                    COUNT(DISTINCT m.id) FILTER (WHERE LOWER(COALESCE(m.vote_result, '')) LIKE '%fail%') AS failed_count,
                    COUNT(DISTINCT m.id) FILTER (
                        WHERE ABS(COALESCE(vc.yes_votes, 0) - COALESCE(vc.no_votes, 0)) <= 1
                    ) AS close_vote_count,
                    SUM(COALESCE(vc.abstain_votes, 0)) AS abstentions,
                    SUM(COALESCE(vc.absent_votes, 0)) AS absences,
                    MIN(m.meeting_date) AS first_seen,
                    MAX(m.meeting_date) AS last_seen
                FROM motion_topics mt
                JOIN motions m ON m.id = mt.motion_id
                LEFT JOIN vote_counts vc ON vc.motion_id = m.id
                GROUP BY mt.topic
                ORDER BY motion_count DESC, failed_count DESC
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            table_rows += f"""
            <tr>
                <td><a href="/search?topic={esc(r['topic'])}">{esc(r['topic'])}</a></td>
                <td>{r['motion_count']}</td>
                <td>{r['failed_count']}</td>
                <td>{r['close_vote_count']}</td>
                <td>{r['abstentions']}</td>
                <td>{r['absences']}</td>
                <td>{esc(r['first_seen'])}</td>
                <td>{esc(r['last_seen'])}</td>
            </tr>
            """

        body = f"""
        <div class="card">
            <h2>Topic Analytics Dashboard</h2>
            <table>
                <thead>
                    <tr>
                        <th>Topic</th>
                        <th>Motions</th>
                        <th>Failed</th>
                        <th>Close Votes</th>
                        <th>Abstentions</th>
                        <th>Absences</th>
                        <th>First Seen</th>
                        <th>Last Seen</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows or '<tr><td colspan="8">No topic analytics found.</td></tr>'}
                </tbody>
            </table>
        </div>
        """
        return layout("Topic Analytics", body)

    @app.route("/trustee-influence")
    def trustee_influence():
        with get_cursor() as cur:
            cur.execute("""
                WITH normalized_votes AS (
                    SELECT
                        tv.motion_id,
                        COALESCE(a.normalized_name, tv.trustee_name) AS trustee_name,
                        LOWER(TRIM(tv.vote)) AS vote
                    FROM trustee_votes tv
                    LEFT JOIN trustee_name_aliases a
                        ON LOWER(TRIM(tv.trustee_name)) = LOWER(TRIM(a.raw_name))
                ),
                motion_vote_counts AS (
                    SELECT
                        motion_id,
                        COUNT(*) FILTER (WHERE vote IN ('yes','aye','y')) AS yes_votes,
                        COUNT(*) FILTER (WHERE vote IN ('no','nay','n')) AS no_votes
                    FROM normalized_votes
                    GROUP BY motion_id
                ),
                trustee_base AS (
                    SELECT
                        nv.trustee_name,
                        COUNT(*) AS total_votes,
                        COUNT(*) FILTER (WHERE nv.vote IN ('yes','aye','y','no','nay','n')) AS decisive_votes,
                        COUNT(*) FILTER (
                            WHERE ABS(COALESCE(mvc.yes_votes, 0) - COALESCE(mvc.no_votes, 0)) <= 1
                        ) AS close_vote_participation,
                        COUNT(*) FILTER (
                            WHERE LOWER(COALESCE(m.vote_result, '')) LIKE '%fail%'
                        ) AS failed_motion_participation
                    FROM normalized_votes nv
                    JOIN motions m ON m.id = nv.motion_id
                    LEFT JOIN motion_vote_counts mvc ON mvc.motion_id = nv.motion_id
                    WHERE COALESCE(nv.trustee_name, '') <> ''
                    GROUP BY nv.trustee_name
                ),
                mover_counts AS (
                    SELECT
                        COALESCE(a.normalized_name, m.moved_by) AS trustee_name,
                        COUNT(*) AS motions_moved
                    FROM motions m
                    LEFT JOIN trustee_name_aliases a
                        ON LOWER(TRIM(m.moved_by)) = LOWER(TRIM(a.raw_name))
                    WHERE COALESCE(m.moved_by, '') <> ''
                    GROUP BY COALESCE(a.normalized_name, m.moved_by)
                ),
                seconder_counts AS (
                    SELECT
                        COALESCE(a.normalized_name, m.seconded_by) AS trustee_name,
                        COUNT(*) AS motions_seconded
                    FROM motions m
                    LEFT JOIN trustee_name_aliases a
                        ON LOWER(TRIM(m.seconded_by)) = LOWER(TRIM(a.raw_name))
                    WHERE COALESCE(m.seconded_by, '') <> ''
                    GROUP BY COALESCE(a.normalized_name, m.seconded_by)
                )
                SELECT
                    tb.trustee_name,
                    tb.total_votes,
                    tb.decisive_votes,
                    tb.close_vote_participation,
                    tb.failed_motion_participation,
                    COALESCE(mc.motions_moved, 0) AS motions_moved,
                    COALESCE(sc.motions_seconded, 0) AS motions_seconded,
                    (
                        tb.decisive_votes
                        + tb.close_vote_participation * 3
                        + tb.failed_motion_participation * 2
                        + COALESCE(mc.motions_moved, 0) * 4
                        + COALESCE(sc.motions_seconded, 0) * 2
                    ) AS influence_score
                FROM trustee_base tb
                LEFT JOIN mover_counts mc ON LOWER(TRIM(mc.trustee_name)) = LOWER(TRIM(tb.trustee_name))
                LEFT JOIN seconder_counts sc ON LOWER(TRIM(sc.trustee_name)) = LOWER(TRIM(tb.trustee_name))
                ORDER BY influence_score DESC, tb.total_votes DESC
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            table_rows += f"""
            <tr>
                <td>{esc(r['trustee_name'])}</td>
                <td><strong>{r['influence_score']}</strong></td>
                <td>{r['total_votes']}</td>
                <td>{r['decisive_votes']}</td>
                <td>{r['close_vote_participation']}</td>
                <td>{r['failed_motion_participation']}</td>
                <td>{r['motions_moved']}</td>
                <td>{r['motions_seconded']}</td>
            </tr>
            """

        body = f"""
        <div class="card">
            <h2>Trustee Influence Scores</h2>
            <p>
                Influence score is a weighted indicator using decisive votes, close vote participation,
                failed motion participation, motions moved, and motions seconded.
            </p>
            <table>
                <thead>
                    <tr>
                        <th>Trustee</th>
                        <th>Influence Score</th>
                        <th>Total Votes</th>
                        <th>Decisive Votes</th>
                        <th>Close Votes</th>
                        <th>Failed Motion Votes</th>
                        <th>Moved</th>
                        <th>Seconded</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows or '<tr><td colspan="8">No influence data found.</td></tr>'}
                </tbody>
            </table>
        </div>
        """
        return layout("Trustee Influence Scores", body)
