from html import escape
from urllib.parse import quote


def register_sprint2_routes(app, get_cursor, layout):
    def esc(value):
        return escape(str(value or ""))

    def pct(num, den):
        if not den:
            return "0.0%"
        return f"{(float(num or 0) / float(den)) * 100:.1f}%"

    CLOSED_SESSION_SQL = """
        (
            COALESCE(m.motion_text, '') ILIKE '%%closed session%%'
            OR COALESCE(m.motion_text, '') ILIKE '%%reportable action%%'
            OR COALESCE(m.motion_text, '') ILIKE '%%reported out%%'
            OR COALESCE(m.motion_text, '') ILIKE '%%conference with legal counsel%%'
            OR COALESCE(m.motion_text, '') ILIKE '%%litigation%%'
            OR COALESCE(m.motion_text, '') ILIKE '%%labor negotiator%%'
            OR COALESCE(m.motion_text, '') ILIKE '%%collective bargaining%%'
            OR COALESCE(m.motion_text, '') ILIKE '%%public employee%%'
            OR COALESCE(m.motion_text, '') ILIKE '%%discipline/dismissal/release%%'
            OR COALESCE(m.motion_text, '') ILIKE '%%settlement agreement%%'
            OR COALESCE(d.text_content, '') ILIKE '%%closed session%%'
            OR COALESCE(d.text_content, '') ILIKE '%%reportable action%%'
            OR COALESCE(d.text_content, '') ILIKE '%%reported out%%'
            OR COALESCE(d.text_content, '') ILIKE '%%conference with legal counsel%%'
            OR COALESCE(d.text_content, '') ILIKE '%%litigation%%'
            OR COALESCE(d.text_content, '') ILIKE '%%labor negotiator%%'
            OR COALESCE(d.text_content, '') ILIKE '%%collective bargaining%%'
            OR COALESCE(d.text_content, '') ILIKE '%%public employee%%'
            OR COALESCE(d.text_content, '') ILIKE '%%discipline/dismissal/release%%'
            OR COALESCE(d.text_content, '') ILIKE '%%settlement agreement%%'
        )
    """

    def sprint2_nav():
        return """
        <div class="card">
            <h2>Sprint 2 Governance Analytics</h2>
            <p>Consensus, disagreement, closed-session-related actions, trustee alignment, and long-term governance trends.</p>
            <p>
                <a href="/rare-failed-motions">Rare Failed Motions</a> |
                <a href="/non-unanimous-motions">Non-Unanimous Motions</a> |
                <a href="/abstentions">Abstentions</a> |
                <a href="/closed-session-motions">Closed Session Related</a> |
                <a href="/trustee-alignment">Trustee Alignment Scores</a> |
                <a href="/topic-consensus">Topic Consensus Scores</a> |
                <a href="/topic-heatmap">Topic Heatmap Over Time</a> |
                <a href="/election-cycle-shifts">Election-Cycle Governance Shifts</a>
            </p>
        </div>
        """

    @app.route("/sprint2")
    def sprint2_dashboard():
        return layout("Sprint 2", sprint2_nav())

    @app.route("/rare-failed-motions")
    def rare_failed_motions():
        with get_cursor() as cur:
            cur.execute("""
                WITH topic_rollup AS (
                    SELECT motion_id, STRING_AGG(DISTINCT topic, ', ' ORDER BY topic) AS topics
                    FROM motion_topics
                    GROUP BY motion_id
                ),
                vote_counts AS (
                    SELECT
                        motion_id,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('yes','aye','y')) AS yes_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('no','nay','n')) AS no_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'abstain%%') AS abstain_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'absent%%') AS absent_votes
                    FROM trustee_votes
                    GROUP BY motion_id
                )
                SELECT
                    m.id,
                    m.document_id,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    COALESCE(tr.topics, '') AS topics,
                    COALESCE(vc.yes_votes, 0) AS yes_votes,
                    COALESCE(vc.no_votes, 0) AS no_votes,
                    COALESCE(vc.abstain_votes, 0) AS abstain_votes,
                    COALESCE(vc.absent_votes, 0) AS absent_votes
                FROM motions m
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                LEFT JOIN vote_counts vc ON vc.motion_id = m.id
                WHERE LOWER(COALESCE(m.vote_result, '')) LIKE '%%fail%%'
                ORDER BY m.meeting_date DESC NULLS LAST, m.id DESC
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            table_rows += f"""
            <tr>
                <td>{esc(r['meeting_date'])}</td>
                <td><a href="/motions/{r['id']}">Motion #{r['id']}</a></td>
                <td>{esc(r['vote_result'])}</td>
                <td>{r['yes_votes']}</td>
                <td>{r['no_votes']}</td>
                <td>{r['abstain_votes']}</td>
                <td>{r['absent_votes']}</td>
                <td>{esc(r['topics'])}</td>
                <td>{esc(r['motion_text'])[:300]}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Rare Failed Motions</h2>
            <p>Motions where the recorded result appears to be failed.</p>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Motion</th><th>Result</th><th>Yes</th><th>No</th>
                        <th>Abstain</th><th>Absent</th><th>Topics</th><th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="9">No failed motions found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Rare Failed Motions", body)

    @app.route("/non-unanimous-motions")
    def non_unanimous_motions():
        with get_cursor() as cur:
            cur.execute("""
                WITH topic_rollup AS (
                    SELECT motion_id, STRING_AGG(DISTINCT topic, ', ' ORDER BY topic) AS topics
                    FROM motion_topics
                    GROUP BY motion_id
                ),
                vote_counts AS (
                    SELECT
                        motion_id,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('yes','aye','y')) AS yes_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('no','nay','n')) AS no_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'abstain%%') AS abstain_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'absent%%') AS absent_votes
                    FROM trustee_votes
                    GROUP BY motion_id
                )
                SELECT
                    m.id,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    COALESCE(tr.topics, '') AS topics,
                    COALESCE(vc.yes_votes, 0) AS yes_votes,
                    COALESCE(vc.no_votes, 0) AS no_votes,
                    COALESCE(vc.abstain_votes, 0) AS abstain_votes,
                    COALESCE(vc.absent_votes, 0) AS absent_votes
                FROM motions m
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                LEFT JOIN vote_counts vc ON vc.motion_id = m.id
                WHERE COALESCE(vc.no_votes, 0) > 0
                   OR COALESCE(vc.abstain_votes, 0) > 0
                ORDER BY m.meeting_date DESC NULLS LAST, m.id DESC
                LIMIT 500
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            table_rows += f"""
            <tr>
                <td>{esc(r['meeting_date'])}</td>
                <td><a href="/motions/{r['id']}">Motion #{r['id']}</a></td>
                <td>{esc(r['vote_result'])}</td>
                <td>{r['yes_votes']}</td>
                <td>{r['no_votes']}</td>
                <td>{r['abstain_votes']}</td>
                <td>{r['absent_votes']}</td>
                <td>{esc(r['topics'])}</td>
                <td>{esc(r['motion_text'])[:300]}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Non-Unanimous Motions</h2>
            <p>Includes motions with at least one No vote or abstention.</p>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Motion</th><th>Result</th><th>Yes</th><th>No</th>
                        <th>Abstain</th><th>Absent</th><th>Topics</th><th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="9">No non-unanimous motions found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Non-Unanimous Motions", body)

    @app.route("/abstentions")
    def abstentions():
        with get_cursor() as cur:
            cur.execute("""
                WITH topic_rollup AS (
                    SELECT motion_id, STRING_AGG(DISTINCT topic, ', ' ORDER BY topic) AS topics
                    FROM motion_topics
                    GROUP BY motion_id
                ),
                abstention_votes AS (
                    SELECT
                        tv.motion_id,
                        STRING_AGG(DISTINCT COALESCE(a.normalized_name, tv.trustee_name), ', ' ORDER BY COALESCE(a.normalized_name, tv.trustee_name)) AS trustees
                    FROM trustee_votes tv
                    LEFT JOIN trustee_name_aliases a
                        ON LOWER(TRIM(tv.trustee_name)) = LOWER(TRIM(a.raw_name))
                    WHERE LOWER(tv.vote) LIKE 'abstain%%'
                    GROUP BY tv.motion_id
                )
                SELECT
                    m.id,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    COALESCE(av.trustees, '') AS trustees,
                    COALESCE(tr.topics, '') AS topics
                FROM motions m
                JOIN abstention_votes av ON av.motion_id = m.id
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                ORDER BY m.meeting_date DESC NULLS LAST, m.id DESC
                LIMIT 500
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            table_rows += f"""
            <tr>
                <td>{esc(r['meeting_date'])}</td>
                <td><a href="/motions/{r['id']}">Motion #{r['id']}</a></td>
                <td>{esc(r['trustees'])}</td>
                <td>{esc(r['vote_result'])}</td>
                <td>{esc(r['topics'])}</td>
                <td>{esc(r['motion_text'])[:300]}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Abstentions</h2>
            <p>Motions where at least one trustee abstained.</p>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Motion</th><th>Trustee(s)</th><th>Result</th><th>Topics</th><th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="6">No abstentions found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Abstentions", body)

    @app.route("/closed-session-motions")
    def closed_session_motions():
        with get_cursor() as cur:
            cur.execute(f"""
                WITH topic_rollup AS (
                    SELECT motion_id, STRING_AGG(DISTINCT topic, ', ' ORDER BY topic) AS topics
                    FROM motion_topics
                    GROUP BY motion_id
                ),
                vote_counts AS (
                    SELECT
                        motion_id,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('yes','aye','y')) AS yes_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('no','nay','n')) AS no_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'abstain%%') AS abstain_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'absent%%') AS absent_votes
                    FROM trustee_votes
                    GROUP BY motion_id
                )
                SELECT
                    m.id,
                    m.document_id,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    d.name AS document_name,
                    COALESCE(tr.topics, '') AS topics,
                    COALESCE(vc.yes_votes, 0) AS yes_votes,
                    COALESCE(vc.no_votes, 0) AS no_votes,
                    COALESCE(vc.abstain_votes, 0) AS abstain_votes,
                    COALESCE(vc.absent_votes, 0) AS absent_votes
                FROM motions m
                LEFT JOIN documents d ON d.id = m.document_id
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                LEFT JOIN vote_counts vc ON vc.motion_id = m.id
                WHERE {CLOSED_SESSION_SQL}
                ORDER BY m.meeting_date DESC NULLS LAST, m.id DESC
                LIMIT 500
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            document_link = f'<a href="/documents/{r["document_id"]}">{esc(r["document_name"])}</a>' if r["document_id"] else ""
            table_rows += f"""
            <tr>
                <td>{esc(r['meeting_date'])}</td>
                <td><a href="/motions/{r['id']}">Motion #{r['id']}</a></td>
                <td>{document_link}</td>
                <td>{esc(r['vote_result'])}</td>
                <td>{r['yes_votes']}</td>
                <td>{r['no_votes']}</td>
                <td>{r['abstain_votes']}</td>
                <td>{r['absent_votes']}</td>
                <td>{esc(r['topics'])}</td>
                <td>{esc(r['motion_text'])[:300]}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Closed Session Related Motions</h2>
            <p>This is an evidence flag based on closed-session-related language in the motion or source document. It is not a legal conclusion.</p>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Motion</th><th>Document</th><th>Result</th>
                        <th>Yes</th><th>No</th><th>Abstain</th><th>Absent</th><th>Topics</th><th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="10">No closed-session-related motions found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Closed Session Related Motions", body)

    @app.route("/trustee-alignment")
    def trustee_alignment():
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
                majority AS (
                    SELECT
                        motion_id,
                        COUNT(*) FILTER (WHERE vote IN ('yes','aye','y')) AS yes_votes,
                        COUNT(*) FILTER (WHERE vote IN ('no','nay','n')) AS no_votes,
                        CASE
                            WHEN COUNT(*) FILTER (WHERE vote IN ('yes','aye','y')) > COUNT(*) FILTER (WHERE vote IN ('no','nay','n')) THEN 'yes'
                            WHEN COUNT(*) FILTER (WHERE vote IN ('no','nay','n')) > COUNT(*) FILTER (WHERE vote IN ('yes','aye','y')) THEN 'no'
                            ELSE 'tie'
                        END AS majority_vote
                    FROM normalized_votes
                    GROUP BY motion_id
                )
                SELECT
                    nv.trustee_name,
                    COUNT(*) FILTER (WHERE nv.vote IN ('yes','aye','y','no','nay','n')) AS decisive_votes,
                    COUNT(*) FILTER (
                        WHERE majority.majority_vote = 'yes' AND nv.vote IN ('yes','aye','y')
                           OR majority.majority_vote = 'no' AND nv.vote IN ('no','nay','n')
                    ) AS aligned_votes,
                    COUNT(*) FILTER (
                        WHERE majority.majority_vote = 'yes' AND nv.vote IN ('no','nay','n')
                           OR majority.majority_vote = 'no' AND nv.vote IN ('yes','aye','y')
                    ) AS divergent_votes,
                    COUNT(*) FILTER (WHERE nv.vote LIKE 'abstain%%') AS abstentions,
                    COUNT(*) FILTER (WHERE nv.vote LIKE 'absent%%') AS absences
                FROM normalized_votes nv
                JOIN majority ON majority.motion_id = nv.motion_id
                WHERE COALESCE(nv.trustee_name, '') <> ''
                GROUP BY nv.trustee_name
                ORDER BY divergent_votes DESC, aligned_votes DESC
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            decisive = r["decisive_votes"] or 0
            table_rows += f"""
            <tr>
                <td>{esc(r['trustee_name'])}</td>
                <td>{decisive}</td>
                <td>{r['aligned_votes']}</td>
                <td>{r['divergent_votes']}</td>
                <td>{pct(r['aligned_votes'], decisive)}</td>
                <td>{r['abstentions']}</td>
                <td>{r['absences']}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Trustee Alignment Scores</h2>
            <p>Measures how often each trustee voted with or against the board majority on Yes/No votes.</p>
            <table>
                <thead>
                    <tr>
                        <th>Trustee</th><th>Decisive Votes</th><th>Aligned</th><th>Divergent</th>
                        <th>Alignment %</th><th>Abstentions</th><th>Absences</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="7">No trustee alignment data found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Trustee Alignment Scores", body)

    @app.route("/topic-consensus")
    def topic_consensus():
        with get_cursor() as cur:
            cur.execute(f"""
                WITH vote_counts AS (
                    SELECT
                        motion_id,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('yes','aye','y')) AS yes_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('no','nay','n')) AS no_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'abstain%%') AS abstain_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'absent%%') AS absent_votes
                    FROM trustee_votes
                    GROUP BY motion_id
                )
                SELECT
                    mt.topic,
                    COUNT(DISTINCT m.id) AS motion_count,
                    COUNT(DISTINCT m.id) FILTER (WHERE LOWER(COALESCE(m.vote_result, '')) LIKE '%%fail%%') AS failed_count,
                    COUNT(DISTINCT m.id) FILTER (
                        WHERE COALESCE(vc.no_votes, 0) > 0 OR COALESCE(vc.abstain_votes, 0) > 0
                    ) AS non_unanimous_count,
                    COUNT(DISTINCT m.id) FILTER (WHERE {CLOSED_SESSION_SQL}) AS closed_session_count,
                    SUM(COALESCE(vc.abstain_votes, 0)) AS abstentions,
                    SUM(COALESCE(vc.absent_votes, 0)) AS absences,
                    MIN(m.meeting_date) AS first_seen,
                    MAX(m.meeting_date) AS last_seen
                FROM motion_topics mt
                JOIN motions m ON m.id = mt.motion_id
                LEFT JOIN documents d ON d.id = m.document_id
                LEFT JOIN vote_counts vc ON vc.motion_id = m.id
                GROUP BY mt.topic
                ORDER BY non_unanimous_count DESC, motion_count DESC
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            motions = r["motion_count"] or 0
            consensus_count = motions - (r["non_unanimous_count"] or 0)
            table_rows += f"""
            <tr>
                <td><a href="/search?topic={quote(str(r['topic']))}">{esc(r['topic'])}</a></td>
                <td>{motions}</td>
                <td>{r['failed_count']}</td>
                <td>{r['non_unanimous_count']}</td>
                <td>{consensus_count}</td>
                <td>{pct(consensus_count, motions)}</td>
                <td>{r['closed_session_count']}</td>
                <td>{r['abstentions']}</td>
                <td>{r['absences']}</td>
                <td>{esc(r['first_seen'])}</td>
                <td>{esc(r['last_seen'])}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Topic Consensus Scores</h2>
            <p>Consensus means the topic had no No votes and no abstentions for that motion.</p>
            <table>
                <thead>
                    <tr>
                        <th>Topic</th><th>Motions</th><th>Failed</th><th>Non-Unanimous</th>
                        <th>Consensus Motions</th><th>Consensus %</th><th>Closed Session Related</th>
                        <th>Abstentions</th><th>Absences</th><th>First Seen</th><th>Last Seen</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="11">No topic consensus data found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Topic Consensus Scores", body)

    @app.route("/topic-analytics")
    def topic_analytics():
        return topic_consensus()

    @app.route("/topic-heatmap")
    def topic_heatmap():
        with get_cursor() as cur:
            cur.execute("""
                WITH yearly AS (
                    SELECT
                        mt.topic,
                        EXTRACT(YEAR FROM m.meeting_date)::int AS meeting_year,
                        COUNT(DISTINCT m.id) AS motion_count
                    FROM motion_topics mt
                    JOIN motions m ON m.id = mt.motion_id
                    WHERE m.meeting_date IS NOT NULL
                    GROUP BY mt.topic, EXTRACT(YEAR FROM m.meeting_date)::int
                ),
                top_topics AS (
                    SELECT topic
                    FROM yearly
                    GROUP BY topic
                    ORDER BY SUM(motion_count) DESC
                    LIMIT 20
                )
                SELECT y.topic, y.meeting_year, y.motion_count
                FROM yearly y
                JOIN top_topics tt ON tt.topic = y.topic
                ORDER BY y.topic, y.meeting_year
            """)
            rows = cur.fetchall()

        years = sorted({r["meeting_year"] for r in rows})
        topics = sorted({r["topic"] for r in rows})
        lookup = {(r["topic"], r["meeting_year"]): r["motion_count"] for r in rows}

        header = "".join(f"<th>{year}</th>" for year in years)
        table_rows = ""
        for topic in topics:
            cells = "".join(f"<td>{lookup.get((topic, year), 0)}</td>" for year in years)
            table_rows += f"<tr><td>{esc(topic)}</td>{cells}</tr>"

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Topic Heatmap Over Time</h2>
            <p>Motion volume by topic and year. This helps show when certain governance topics became more active.</p>
            <table>
                <thead>
                    <tr><th>Topic</th>{header}</tr>
                </thead>
                <tbody>{table_rows or '<tr><td>No topic heatmap data found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Topic Heatmap Over Time", body)

    @app.route("/election-cycle-shifts")
    def election_cycle_shifts():
        with get_cursor() as cur:
            cur.execute(f"""
                WITH vote_counts AS (
                    SELECT
                        motion_id,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('yes','aye','y')) AS yes_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) IN ('no','nay','n')) AS no_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'abstain%%') AS abstain_votes,
                        COUNT(*) FILTER (WHERE LOWER(vote) LIKE 'absent%%') AS absent_votes
                    FROM trustee_votes
                    GROUP BY motion_id
                ),
                base AS (
                    SELECT
                        (
                            FLOOR((EXTRACT(YEAR FROM m.meeting_date)::int - 1976) / 4.0)::int * 4 + 1976
                        ) AS cycle_start,
                        m.id,
                        m.vote_result,
                        COALESCE(vc.no_votes, 0) AS no_votes,
                        COALESCE(vc.abstain_votes, 0) AS abstain_votes,
                        COALESCE(vc.absent_votes, 0) AS absent_votes,
                        CASE WHEN {CLOSED_SESSION_SQL} THEN 1 ELSE 0 END AS closed_session_related
                    FROM motions m
                    LEFT JOIN documents d ON d.id = m.document_id
                    LEFT JOIN vote_counts vc ON vc.motion_id = m.id
                    WHERE m.meeting_date IS NOT NULL
                )
                SELECT
                    cycle_start,
                    cycle_start + 3 AS cycle_end,
                    COUNT(DISTINCT id) AS motion_count,
                    COUNT(DISTINCT id) FILTER (WHERE LOWER(COALESCE(vote_result, '')) LIKE '%%fail%%') AS failed_count,
                    COUNT(DISTINCT id) FILTER (WHERE no_votes > 0 OR abstain_votes > 0) AS non_unanimous_count,
                    SUM(abstain_votes) AS abstentions,
                    SUM(absent_votes) AS absences,
                    SUM(closed_session_related) AS closed_session_count
                FROM base
                GROUP BY cycle_start
                ORDER BY cycle_start DESC
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            motions = r["motion_count"] or 0
            consensus = motions - (r["non_unanimous_count"] or 0)
            table_rows += f"""
            <tr>
                <td>{r['cycle_start']}–{r['cycle_end']}</td>
                <td>{motions}</td>
                <td>{r['failed_count']}</td>
                <td>{r['non_unanimous_count']}</td>
                <td>{pct(consensus, motions)}</td>
                <td>{r['closed_session_count']}</td>
                <td>{r['abstentions']}</td>
                <td>{r['absences']}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Election-Cycle Governance Shifts</h2>
            <p>Grouped into four-year cycles starting with 1976. This is a rough proxy for trustee election-cycle changes.</p>
            <table>
                <thead>
                    <tr>
                        <th>Cycle</th><th>Motions</th><th>Failed</th><th>Non-Unanimous</th>
                        <th>Consensus %</th><th>Closed Session Related</th><th>Abstentions</th><th>Absences</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="8">No election-cycle data found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Election-Cycle Governance Shifts", body)
