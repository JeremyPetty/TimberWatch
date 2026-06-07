from html import escape
from urllib.parse import quote


def register_sprint2_routes(app, get_cursor, layout):
    def esc(value):
        return escape(str(value or ""))

    def pct(num, den):
        if not den:
            return "0.0%"
        return f"{(float(num or 0) / float(den)) * 100:.1f}%"

    def money(value):
        if value is None:
            return ""
        try:
            return "${:,.0f}".format(float(value))
        except Exception:
            return esc(value)

    CLOSED_SESSION_SQL = """
        COALESCE(m.closed_session_related, FALSE) = TRUE
    """

    def sprint2_nav():
        return """
        <div class="card">
            <h2>Sprint 2 Governance Analytics</h2>
            <p>Consensus, disagreement, closed-session-related actions, trustee alignment, AI governance signals, and long-term governance trends.</p>
            <p>
                <a href="/high-significance-motions">High Significance Motions</a> |
                <a href="/controversial-motions">Most Controversial Motions</a> |
                <a href="/strategic-priorities">Strategic Priorities</a> |
                <a href="/election-cycles">Election Cycle History</a>
            </p>
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
            <p>
                <a href="/financial-impact-motions">Financial Impact</a> |
                <a href="/legal-risk-motions">Legal Risk</a> |
                <a href="/personnel-impact-motions">Personnel Impact</a> |
                <a href="/policy-change-motions">Policy Changes</a> |
                <a href="/public-comment-motions">Public Comment Signals</a>
            </p>
        </div>
        """

    def motion_table(rows, include_ai=True):
        table_rows = ""
        for r in rows:
            document_link = ""
            if "document_id" in r and r.get("document_id"):
                document_name = r.get("document_name") or f"Document #{r['document_id']}"
                document_link = f'<a href="/documents/{r["document_id"]}">{esc(document_name)}</a>'

            ai_cols = ""
            if include_ai:
                ai_cols = f"""
                <td>{esc(r.get('strategic_priority'))}</td>
                <td>{esc(r.get('board_action_type'))}</td>
                <td>{r.get('governance_significance_score') or ''}</td>
                <td>{r.get('controversy_score') or 0}</td>
                """

            table_rows += f"""
            <tr>
                <td>{esc(r.get('meeting_date'))}</td>
                <td><a href="/motions/{r['id']}">Motion #{r['id']}</a></td>
                <td>{document_link}</td>
                <td>{esc(r.get('vote_result'))}</td>
                {ai_cols}
                <td>{esc(r.get('topics'))}</td>
                <td>{esc(r.get('motion_text'))[:320]}</td>
            </tr>
            """
        return table_rows

    @app.route("/sprint2")
    def sprint2_dashboard():
        with get_cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) AS total_motions,
                    COUNT(*) FILTER (WHERE ai_governance_signals IS NOT NULL) AS ai_scanned,
                    COUNT(*) FILTER (WHERE governance_significance_score >= 4) AS high_significance,
                    COUNT(*) FILTER (WHERE controversy_score >= 4) AS controversial,
                    COUNT(*) FILTER (WHERE closed_session_related = TRUE) AS closed_session_actions,
                    COUNT(*) FILTER (WHERE financial_impact_flag = TRUE) AS financial_impact,
                    COUNT(*) FILTER (WHERE legal_risk_flag = TRUE) AS legal_risk,
                    COUNT(*) FILTER (WHERE personnel_impact_flag = TRUE) AS personnel_impact,
                    COUNT(*) FILTER (WHERE policy_change_flag = TRUE) AS policy_changes
                FROM motions
            """)
            stats = cur.fetchone()

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Sprint 2.5 AI Governance Summary</h2>
            <table>
                <thead>
                    <tr>
                        <th>Total Motions</th>
                        <th>AI Scanned</th>
                        <th>High Significance</th>
                        <th>Controversial</th>
                        <th>Closed Session Actions</th>
                        <th>Financial</th>
                        <th>Legal</th>
                        <th>Personnel</th>
                        <th>Policy</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>{stats['total_motions']}</td>
                        <td>{stats['ai_scanned']} ({pct(stats['ai_scanned'], stats['total_motions'])})</td>
                        <td>{stats['high_significance']}</td>
                        <td>{stats['controversial']}</td>
                        <td>{stats['closed_session_actions']}</td>
                        <td>{stats['financial_impact']}</td>
                        <td>{stats['legal_risk']}</td>
                        <td>{stats['personnel_impact']}</td>
                        <td>{stats['policy_changes']}</td>
                    </tr>
                </tbody>
            </table>
        </div>
        """
        return layout("Sprint 2", body)

    @app.route("/high-significance-motions")
    def high_significance_motions():
        with get_cursor() as cur:
            cur.execute("""
                WITH topic_rollup AS (
                    SELECT motion_id, STRING_AGG(DISTINCT topic, ', ' ORDER BY topic) AS topics
                    FROM motion_topics
                    GROUP BY motion_id
                )
                SELECT
                    m.id,
                    m.document_id,
                    d.name AS document_name,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    m.governance_significance_score,
                    m.controversy_score,
                    m.strategic_priority,
                    m.board_action_type,
                    COALESCE(tr.topics, '') AS topics
                FROM motions m
                LEFT JOIN documents d ON d.id = m.document_id
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                WHERE COALESCE(m.governance_significance_score, 0) >= 4
                ORDER BY m.governance_significance_score DESC, m.meeting_date DESC NULLS LAST, m.id DESC
                LIMIT 500
            """)
            rows = cur.fetchall()

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>High Significance Motions</h2>
            <p>Motions scored 4 or 5 by the AI governance scan. These are likely major financial, legal, policy, facilities, or strategic decisions.</p>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Motion</th><th>Document</th><th>Result</th>
                        <th>Priority</th><th>Action Type</th><th>Significance</th><th>Controversy</th>
                        <th>Topics</th><th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>{motion_table(rows) or '<tr><td colspan="10">No high significance motions found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("High Significance Motions", body)

    @app.route("/controversial-motions")
    def controversial_motions():
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
                    d.name AS document_name,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    m.governance_significance_score,
                    m.controversy_score,
                    m.strategic_priority,
                    m.board_action_type,
                    m.closed_session_related,
                    m.legal_risk_flag,
                    m.personnel_impact_flag,
                    m.public_comment_flag,
                    COALESCE(vc.yes_votes, 0) AS yes_votes,
                    COALESCE(vc.no_votes, 0) AS no_votes,
                    COALESCE(vc.abstain_votes, 0) AS abstain_votes,
                    COALESCE(vc.absent_votes, 0) AS absent_votes,
                    COALESCE(tr.topics, '') AS topics
                FROM motions m
                LEFT JOIN documents d ON d.id = m.document_id
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                LEFT JOIN vote_counts vc ON vc.motion_id = m.id
                WHERE COALESCE(m.controversy_score, 0) > 0
                   OR LOWER(COALESCE(m.vote_result, '')) LIKE '%%fail%%'
                   OR COALESCE(vc.no_votes, 0) > 0
                   OR COALESCE(vc.abstain_votes, 0) > 0
                ORDER BY COALESCE(m.controversy_score, 0) DESC, m.meeting_date DESC NULLS LAST, m.id DESC
                LIMIT 500
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            flags = []
            if r.get("closed_session_related"):
                flags.append("Closed Session")
            if r.get("legal_risk_flag"):
                flags.append("Legal")
            if r.get("personnel_impact_flag"):
                flags.append("Personnel")
            if r.get("public_comment_flag"):
                flags.append("Public Comment")
            document_link = f'<a href="/documents/{r["document_id"]}">{esc(r["document_name"])}</a>' if r.get("document_id") else ""
            table_rows += f"""
            <tr>
                <td>{esc(r['meeting_date'])}</td>
                <td><a href="/motions/{r['id']}">Motion #{r['id']}</a></td>
                <td>{document_link}</td>
                <td>{esc(r['vote_result'])}</td>
                <td><strong>{r['controversy_score'] or 0}</strong></td>
                <td>{r['governance_significance_score'] or ''}</td>
                <td>{r['yes_votes']}</td>
                <td>{r['no_votes']}</td>
                <td>{r['abstain_votes']}</td>
                <td>{esc(', '.join(flags))}</td>
                <td>{esc(r['strategic_priority'])}</td>
                <td>{esc(r['topics'])}</td>
                <td>{esc(r['motion_text'])[:300]}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Most Controversial Motions</h2>
            <p>Uses the AI controversy score plus objective disagreement signals such as failed votes, No votes, and abstentions.</p>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Motion</th><th>Document</th><th>Result</th><th>Controversy</th>
                        <th>Significance</th><th>Yes</th><th>No</th><th>Abstain</th>
                        <th>Flags</th><th>Priority</th><th>Topics</th><th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="13">No controversial motions found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Most Controversial Motions", body)

    @app.route("/strategic-priorities")
    def strategic_priorities():
        with get_cursor() as cur:
            cur.execute("""
                SELECT
                    COALESCE(strategic_priority, 'Unclassified') AS strategic_priority,
                    COUNT(*) AS motion_count,
                    ROUND(AVG(COALESCE(governance_significance_score, 0))::numeric, 2) AS avg_significance,
                    ROUND(AVG(COALESCE(controversy_score, 0))::numeric, 2) AS avg_controversy,
                    COUNT(*) FILTER (WHERE COALESCE(governance_significance_score, 0) >= 4) AS high_significance_count,
                    COUNT(*) FILTER (WHERE COALESCE(controversy_score, 0) >= 4) AS controversial_count,
                    COUNT(*) FILTER (WHERE closed_session_related = TRUE) AS closed_session_count,
                    COUNT(*) FILTER (WHERE financial_impact_flag = TRUE) AS financial_impact_count,
                    COUNT(*) FILTER (WHERE legal_risk_flag = TRUE) AS legal_risk_count,
                    COUNT(*) FILTER (WHERE personnel_impact_flag = TRUE) AS personnel_impact_count,
                    MIN(meeting_date) AS first_seen,
                    MAX(meeting_date) AS last_seen
                FROM motions
                GROUP BY COALESCE(strategic_priority, 'Unclassified')
                ORDER BY motion_count DESC, avg_significance DESC
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            priority_url = quote(str(r["strategic_priority"]))
            table_rows += f"""
            <tr>
                <td><a href="/strategic-priorities/{priority_url}">{esc(r['strategic_priority'])}</a></td>
                <td>{r['motion_count']}</td>
                <td>{r['avg_significance']}</td>
                <td>{r['avg_controversy']}</td>
                <td>{r['high_significance_count']}</td>
                <td>{r['controversial_count']}</td>
                <td>{r['closed_session_count']}</td>
                <td>{r['financial_impact_count']}</td>
                <td>{r['legal_risk_count']}</td>
                <td>{r['personnel_impact_count']}</td>
                <td>{esc(r['first_seen'])}</td>
                <td>{esc(r['last_seen'])}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Strategic Priorities Dashboard</h2>
            <p>AI-classified strategic priorities across all motions.</p>
            <table>
                <thead>
                    <tr>
                        <th>Strategic Priority</th><th>Motions</th><th>Avg Significance</th><th>Avg Controversy</th>
                        <th>High Significance</th><th>Controversial</th><th>Closed Session</th>
                        <th>Financial</th><th>Legal</th><th>Personnel</th><th>First Seen</th><th>Last Seen</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="12">No strategic priority data found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Strategic Priorities", body)

    @app.route("/strategic-priorities/<path:priority>")
    def strategic_priority_detail(priority):
        with get_cursor() as cur:
            cur.execute("""
                WITH topic_rollup AS (
                    SELECT motion_id, STRING_AGG(DISTINCT topic, ', ' ORDER BY topic) AS topics
                    FROM motion_topics
                    GROUP BY motion_id
                )
                SELECT
                    m.id,
                    m.document_id,
                    d.name AS document_name,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    m.governance_significance_score,
                    m.controversy_score,
                    m.strategic_priority,
                    m.board_action_type,
                    COALESCE(tr.topics, '') AS topics
                FROM motions m
                LEFT JOIN documents d ON d.id = m.document_id
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                WHERE COALESCE(m.strategic_priority, 'Unclassified') = %s
                ORDER BY COALESCE(m.governance_significance_score, 0) DESC, m.meeting_date DESC NULLS LAST
                LIMIT 500
            """, [priority])
            rows = cur.fetchall()

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Strategic Priority: {esc(priority)}</h2>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Motion</th><th>Document</th><th>Result</th>
                        <th>Priority</th><th>Action Type</th><th>Significance</th><th>Controversy</th>
                        <th>Topics</th><th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>{motion_table(rows) or '<tr><td colspan="10">No motions found for this priority.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout(f"Strategic Priority - {priority}", body)

    @app.route("/election-cycles")
    def election_cycles():
        with get_cursor() as cur:
            cur.execute("""
                WITH base AS (
                    SELECT
                        (
                            FLOOR((EXTRACT(YEAR FROM meeting_date)::int - 1976) / 4.0)::int * 4 + 1976
                        ) AS cycle_start,
                        *
                    FROM motions
                    WHERE meeting_date IS NOT NULL
                ),
                cycle_summary AS (
                    SELECT
                        cycle_start,
                        cycle_start + 3 AS cycle_end,
                        COUNT(*) AS motion_count,
                        ROUND(AVG(COALESCE(governance_significance_score, 0))::numeric, 2) AS avg_significance,
                        ROUND(AVG(COALESCE(controversy_score, 0))::numeric, 2) AS avg_controversy,
                        COUNT(*) FILTER (WHERE COALESCE(governance_significance_score, 0) >= 4) AS high_significance_count,
                        COUNT(*) FILTER (WHERE COALESCE(controversy_score, 0) >= 4) AS controversial_count,
                        COUNT(*) FILTER (WHERE closed_session_related = TRUE) AS closed_session_count,
                        COUNT(*) FILTER (WHERE financial_impact_flag = TRUE) AS financial_impact_count,
                        COUNT(*) FILTER (WHERE legal_risk_flag = TRUE) AS legal_risk_count,
                        COUNT(*) FILTER (WHERE personnel_impact_flag = TRUE) AS personnel_impact_count,
                        COUNT(*) FILTER (WHERE policy_change_flag = TRUE) AS policy_change_count
                    FROM base
                    GROUP BY cycle_start
                ),
                priority_rank AS (
                    SELECT
                        cycle_start,
                        COALESCE(strategic_priority, 'Unclassified') AS strategic_priority,
                        COUNT(*) AS priority_count,
                        ROW_NUMBER() OVER (
                            PARTITION BY cycle_start
                            ORDER BY COUNT(*) DESC, COALESCE(strategic_priority, 'Unclassified')
                        ) AS rn
                    FROM base
                    GROUP BY cycle_start, COALESCE(strategic_priority, 'Unclassified')
                ),
                top_priorities AS (
                    SELECT
                        cycle_start,
                        STRING_AGG(strategic_priority || ' (' || priority_count || ')', ', ' ORDER BY priority_count DESC) AS priorities
                    FROM priority_rank
                    WHERE rn <= 3
                    GROUP BY cycle_start
                )
                SELECT
                    cs.*,
                    COALESCE(tp.priorities, '') AS top_priorities
                FROM cycle_summary cs
                LEFT JOIN top_priorities tp ON tp.cycle_start = cs.cycle_start
                ORDER BY cs.cycle_start DESC
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            cycle_label = f"{r['cycle_start']}-{r['cycle_end']}"
            table_rows += f"""
            <tr>
                <td><a href="/election-cycles/{r['cycle_start']}">{cycle_label}</a></td>
                <td>{r['motion_count']}</td>
                <td>{r['avg_significance']}</td>
                <td>{r['avg_controversy']}</td>
                <td>{r['high_significance_count']}</td>
                <td>{r['controversial_count']}</td>
                <td>{r['closed_session_count']}</td>
                <td>{r['financial_impact_count']}</td>
                <td>{r['legal_risk_count']}</td>
                <td>{r['personnel_impact_count']}</td>
                <td>{r['policy_change_count']}</td>
                <td>{esc(r['top_priorities'])}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Election Cycle History</h2>
            <p>Four-year governance cycles starting in 1976, using AI-classified strategic priorities and governance signals.</p>
            <table>
                <thead>
                    <tr>
                        <th>Cycle</th><th>Motions</th><th>Avg Significance</th><th>Avg Controversy</th>
                        <th>High Significance</th><th>Controversial</th><th>Closed Session</th>
                        <th>Financial</th><th>Legal</th><th>Personnel</th><th>Policy</th><th>Top Priorities</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="12">No election cycle data found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Election Cycle History", body)

    @app.route("/election-cycles/<int:cycle_start>")
    def election_cycle_detail(cycle_start):
        cycle_end = cycle_start + 3
        with get_cursor() as cur:
            cur.execute("""
                WITH topic_rollup AS (
                    SELECT motion_id, STRING_AGG(DISTINCT topic, ', ' ORDER BY topic) AS topics
                    FROM motion_topics
                    GROUP BY motion_id
                )
                SELECT
                    m.id,
                    m.document_id,
                    d.name AS document_name,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    m.governance_significance_score,
                    m.controversy_score,
                    m.strategic_priority,
                    m.board_action_type,
                    COALESCE(tr.topics, '') AS topics
                FROM motions m
                LEFT JOIN documents d ON d.id = m.document_id
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                WHERE EXTRACT(YEAR FROM m.meeting_date)::int BETWEEN %s AND %s
                ORDER BY COALESCE(m.governance_significance_score, 0) DESC,
                         COALESCE(m.controversy_score, 0) DESC,
                         m.meeting_date DESC NULLS LAST
                LIMIT 500
            """, [cycle_start, cycle_end])
            motions = cur.fetchall()

            cur.execute("""
                SELECT
                    COALESCE(strategic_priority, 'Unclassified') AS strategic_priority,
                    COUNT(*) AS motion_count,
                    ROUND(AVG(COALESCE(governance_significance_score, 0))::numeric, 2) AS avg_significance,
                    ROUND(AVG(COALESCE(controversy_score, 0))::numeric, 2) AS avg_controversy
                FROM motions
                WHERE EXTRACT(YEAR FROM meeting_date)::int BETWEEN %s AND %s
                GROUP BY COALESCE(strategic_priority, 'Unclassified')
                ORDER BY motion_count DESC
                LIMIT 10
            """, [cycle_start, cycle_end])
            priorities = cur.fetchall()

        priority_rows = ""
        for p in priorities:
            priority_rows += f"""
            <tr>
                <td>{esc(p['strategic_priority'])}</td>
                <td>{p['motion_count']}</td>
                <td>{p['avg_significance']}</td>
                <td>{p['avg_controversy']}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Election Cycle: {cycle_start}-{cycle_end}</h2>
            <h3>Top Strategic Priorities</h3>
            <table>
                <thead><tr><th>Priority</th><th>Motions</th><th>Avg Significance</th><th>Avg Controversy</th></tr></thead>
                <tbody>{priority_rows or '<tr><td colspan="4">No priority data found.</td></tr>'}</tbody>
            </table>
        </div>

        <div class="card">
            <h3>Most Significant Motions in this Cycle</h3>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Motion</th><th>Document</th><th>Result</th>
                        <th>Priority</th><th>Action Type</th><th>Significance</th><th>Controversy</th>
                        <th>Topics</th><th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>{motion_table(motions) or '<tr><td colspan="10">No motions found for this election cycle.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout(f"Election Cycle {cycle_start}-{cycle_end}", body)

    def flagged_motions_page(route_title, flag_column, description):
        with get_cursor() as cur:
            cur.execute(f"""
                WITH topic_rollup AS (
                    SELECT motion_id, STRING_AGG(DISTINCT topic, ', ' ORDER BY topic) AS topics
                    FROM motion_topics
                    GROUP BY motion_id
                )
                SELECT
                    m.id,
                    m.document_id,
                    d.name AS document_name,
                    m.meeting_date,
                    m.motion_text,
                    m.vote_result,
                    m.governance_significance_score,
                    m.controversy_score,
                    m.strategic_priority,
                    m.board_action_type,
                    m.financial_impact_amount,
                    COALESCE(tr.topics, '') AS topics
                FROM motions m
                LEFT JOIN documents d ON d.id = m.document_id
                LEFT JOIN topic_rollup tr ON tr.motion_id = m.id
                WHERE COALESCE(m.{flag_column}, FALSE) = TRUE
                ORDER BY COALESCE(m.governance_significance_score, 0) DESC,
                         COALESCE(m.controversy_score, 0) DESC,
                         m.meeting_date DESC NULLS LAST
                LIMIT 500
            """)
            rows = cur.fetchall()

        table_rows = ""
        for r in rows:
            document_link = f'<a href="/documents/{r["document_id"]}">{esc(r["document_name"])}</a>' if r.get("document_id") else ""
            amount_col = f"<td>{money(r.get('financial_impact_amount'))}</td>" if flag_column == "financial_impact_flag" else ""
            table_rows += f"""
            <tr>
                <td>{esc(r['meeting_date'])}</td>
                <td><a href="/motions/{r['id']}">Motion #{r['id']}</a></td>
                <td>{document_link}</td>
                <td>{esc(r['vote_result'])}</td>
                <td>{esc(r['strategic_priority'])}</td>
                <td>{esc(r['board_action_type'])}</td>
                <td>{r['governance_significance_score'] or ''}</td>
                <td>{r['controversy_score'] or 0}</td>
                {amount_col}
                <td>{esc(r['topics'])}</td>
                <td>{esc(r['motion_text'])[:320]}</td>
            </tr>
            """

        amount_header = "<th>Amount</th>" if flag_column == "financial_impact_flag" else ""
        colspan = "11" if flag_column == "financial_impact_flag" else "10"

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>{esc(route_title)}</h2>
            <p>{esc(description)}</p>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Motion</th><th>Document</th><th>Result</th>
                        <th>Priority</th><th>Action Type</th><th>Significance</th><th>Controversy</th>
                        {amount_header}<th>Topics</th><th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>{table_rows or f'<tr><td colspan="{colspan}">No matching motions found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout(route_title, body)

    @app.route("/financial-impact-motions")
    def financial_impact_motions():
        return flagged_motions_page(
            "Financial Impact Motions",
            "financial_impact_flag",
            "Motions where the AI identified a likely financial impact, contract, budget, grant, purchase, settlement, or funding decision."
        )

    @app.route("/legal-risk-motions")
    def legal_risk_motions():
        return flagged_motions_page(
            "Legal Risk Motions",
            "legal_risk_flag",
            "Motions where the AI identified litigation, claims, settlements, compliance concerns, or other legal risk."
        )

    @app.route("/personnel-impact-motions")
    def personnel_impact_motions():
        return flagged_motions_page(
            "Personnel Impact Motions",
            "personnel_impact_flag",
            "Motions where the AI identified personnel, labor, employment, discipline, appointment, or HR impact."
        )

    @app.route("/policy-change-motions")
    def policy_change_motions():
        return flagged_motions_page(
            "Policy Change Motions",
            "policy_change_flag",
            "Motions where the AI identified board policy, administrative procedure, or governance rule changes."
        )

    @app.route("/public-comment-motions")
    def public_comment_motions():
        return flagged_motions_page(
            "Public Comment Signal Motions",
            "public_comment_flag",
            "Motions where the AI identified public comment, public concern, or community participation related to the item."
        )

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
                    m.closed_session_ai_status,
                    m.closed_session_action_type,
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
                <td>{esc(r['closed_session_ai_status'])}</td>
                <td>{esc(r['closed_session_action_type'])}</td>
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
            <p>This page now uses the AI-classified closed-session action flag. It should represent reported/approved action, not merely an agenda listing.</p>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Motion</th><th>Document</th><th>Result</th>
                        <th>AI Status</th><th>Action Type</th>
                        <th>Yes</th><th>No</th><th>Abstain</th><th>Absent</th><th>Topics</th><th>Motion Text</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="12">No closed-session-related motions found.</td></tr>'}</tbody>
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
                    ROUND(AVG(COALESCE(m.governance_significance_score, 0))::numeric, 2) AS avg_significance,
                    ROUND(AVG(COALESCE(m.controversy_score, 0))::numeric, 2) AS avg_controversy,
                    SUM(COALESCE(vc.abstain_votes, 0)) AS abstentions,
                    SUM(COALESCE(vc.absent_votes, 0)) AS absences,
                    MIN(m.meeting_date) AS first_seen,
                    MAX(m.meeting_date) AS last_seen
                FROM motion_topics mt
                JOIN motions m ON m.id = mt.motion_id
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
                <td>{r['avg_significance']}</td>
                <td>{r['avg_controversy']}</td>
                <td>{r['abstentions']}</td>
                <td>{r['absences']}</td>
                <td>{esc(r['first_seen'])}</td>
                <td>{esc(r['last_seen'])}</td>
            </tr>
            """

        body = sprint2_nav() + f"""
        <div class="card">
            <h2>Topic Consensus Scores</h2>
            <p>Consensus means the topic had no No votes and no abstentions for that motion. This version also includes AI significance and controversy averages.</p>
            <table>
                <thead>
                    <tr>
                        <th>Topic</th><th>Motions</th><th>Failed</th><th>Non-Unanimous</th>
                        <th>Consensus Motions</th><th>Consensus %</th><th>Closed Session</th>
                        <th>Avg Significance</th><th>Avg Controversy</th>
                        <th>Abstentions</th><th>Absences</th><th>First Seen</th><th>Last Seen</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="13">No topic consensus data found.</td></tr>'}</tbody>
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
                        CASE WHEN {CLOSED_SESSION_SQL} THEN 1 ELSE 0 END AS closed_session_related,
                        m.governance_significance_score,
                        m.controversy_score
                    FROM motions m
                    LEFT JOIN vote_counts vc ON vc.motion_id = m.id
                    WHERE m.meeting_date IS NOT NULL
                )
                SELECT
                    cycle_start,
                    cycle_start + 3 AS cycle_end,
                    COUNT(DISTINCT id) AS motion_count,
                    COUNT(DISTINCT id) FILTER (WHERE LOWER(COALESCE(vote_result, '')) LIKE '%%fail%%') AS failed_count,
                    COUNT(DISTINCT id) FILTER (WHERE no_votes > 0 OR abstain_votes > 0) AS non_unanimous_count,
                    ROUND(AVG(COALESCE(governance_significance_score, 0))::numeric, 2) AS avg_significance,
                    ROUND(AVG(COALESCE(controversy_score, 0))::numeric, 2) AS avg_controversy,
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
                <td>{r['avg_significance']}</td>
                <td>{r['avg_controversy']}</td>
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
                        <th>Consensus %</th><th>Avg Significance</th><th>Avg Controversy</th>
                        <th>Closed Session</th><th>Abstentions</th><th>Absences</th>
                    </tr>
                </thead>
                <tbody>{table_rows or '<tr><td colspan="10">No election-cycle data found.</td></tr>'}</tbody>
            </table>
        </div>
        """
        return layout("Election-Cycle Governance Shifts", body)
