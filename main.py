import os
import html
import subprocess
from urllib.parse import urlencode

import psycopg2
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

DATABASE_URL = os.environ["DATABASE_URL"]

app = FastAPI()


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def esc(value):
    return html.escape(str(value or ""), quote=True)


def search_url(**kwargs):
    clean = {k: v for k, v in kwargs.items() if v not in (None, "")}
    if not clean:
        return "/search"
    return "/search?" + urlencode(clean)


@app.get("/", response_class=HTMLResponse)
def home():
    return search()


@app.get("/status", response_class=HTMLResponse)
def status():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM documents")
                doc_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM motions")
                motion_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM trustee_votes")
                trustee_vote_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM ai_document_classifications")
                ai_count = cur.fetchone()[0]

        return f"""
        <html>
        <head><title>TimberWatch Status</title></head>
        <body>
            <h1>TimberWatch Status</h1>
            <p><b>Database:</b> Connected</p>
            <p><b>Documents:</b> {doc_count}</p>
            <p><b>Motions:</b> {motion_count}</p>
            <p><b>Trustee Votes:</b> {trustee_vote_count}</p>
            <p><b>AI Classifications:</b> {ai_count}</p>
            <p><a href="/">Back to Search</a></p>
        </body>
        </html>
        """

    except Exception as e:
        return f"""
        <html>
        <head><title>TimberWatch Status</title></head>
        <body>
            <h1>TimberWatch Status</h1>
            <p style="color:red;"><b>Error:</b> {esc(e)}</p>
            <p><a href="/">Back to Search</a></p>
        </body>
        </html>
        """


@app.get("/search", response_class=HTMLResponse)
def search(
    q: str = "",
    source: str = "",
    document_type: str = "",
    start_date: str = "",
    end_date: str = "",
    trustee: str = "",
    vote: str = "",
    view: str = "",
):
    q = q.strip()
    source = source.strip()
    document_type = document_type.strip()
    start_date = start_date.strip()
    end_date = end_date.strip()
    trustee = trustee.strip()
    vote = vote.strip()
    view = view.strip()

    results = []
    error = ""

    dashboard = {
        "documents": 0,
        "motions": 0,
        "failed_motions": 0,
        "abstentions": 0,
        "topics": [],
        "trustees": [],
        "trustee_scorecard": [],
        "ai_classified": 0,
        "ai_contains_votes": 0,
        "ai_failed_unclear": 0,
        "ai_needs_review": 0,
        "ai_topics": [],
    }

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM documents")
                dashboard["documents"] = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM motions")
                dashboard["motions"] = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM motions
                    WHERE vote_result ILIKE '%failed%'
                       OR vote_result ILIKE '%no%'
                       OR vote_result ILIKE '%nay%'
                """)
                dashboard["failed_motions"] = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM trustee_votes
                    WHERE vote ILIKE '%abstain%'
                       OR vote ILIKE '%abstention%'
                """)
                dashboard["abstentions"] = cur.fetchone()[0]

                cur.execute("""
                    SELECT topic, COUNT(*)
                    FROM motions
                    WHERE topic IS NOT NULL
                      AND topic <> ''
                    GROUP BY topic
                    ORDER BY COUNT(*) DESC
                    LIMIT 5
                """)
                dashboard["topics"] = cur.fetchall()

                cur.execute("""
                    SELECT DISTINCT trustee_name
                    FROM trustee_votes
                    WHERE trustee_name IS NOT NULL
                      AND trustee_name <> ''
                    ORDER BY trustee_name
                """)
                dashboard["trustees"] = cur.fetchall()

                cur.execute("""
                    SELECT
                        trustee_name,
                        COUNT(*) FILTER (WHERE vote ILIKE 'yes') AS ayes,
                        COUNT(*) FILTER (WHERE vote ILIKE 'no') AS nays,
                        COUNT(*) FILTER (WHERE vote ILIKE 'abstain' OR vote ILIKE 'abstention') AS abstains,
                        COUNT(*) FILTER (WHERE vote ILIKE 'absent') AS absents
                    FROM trustee_votes
                    WHERE trustee_name IS NOT NULL
                      AND trustee_name <> ''
                    GROUP BY trustee_name
                    ORDER BY trustee_name
                """)
                dashboard["trustee_scorecard"] = cur.fetchall()

                # AI-powered dashboard counts
                cur.execute("SELECT COUNT(*) FROM ai_document_classifications")
                dashboard["ai_classified"] = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM ai_document_classifications
                    WHERE contains_vote = TRUE
                """)
                dashboard["ai_contains_votes"] = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM ai_document_classifications
                    WHERE vote_result IN ('Failed', 'Unclear')
                """)
                dashboard["ai_failed_unclear"] = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM ai_document_classifications
                    WHERE needs_human_review = TRUE
                """)
                dashboard["ai_needs_review"] = cur.fetchone()[0]

                cur.execute("""
                    SELECT primary_topic, COUNT(*)
                    FROM ai_document_classifications
                    WHERE primary_topic IS NOT NULL
                      AND primary_topic <> ''
                    GROUP BY primary_topic
                    ORDER BY COUNT(*) DESC
                    LIMIT 5
                """)
                dashboard["ai_topics"] = cur.fetchall()

                if q or source or document_type or start_date or end_date or view or trustee or vote:
                    where_parts = []
                    params = []

                    if q:
                        where_parts.append("""
                            (
                                search_vector @@ plainto_tsquery('english', %s)
                                OR name ILIKE %s
                                OR text_content ILIKE %s
                            )
                        """)
                        params.extend([q, f"%{q}%", f"%{q}%"])

                    if source:
                        where_parts.append("source = %s")
                        params.append(source)

                    if document_type:
                        where_parts.append("document_type = %s")
                        params.append(document_type)

                    if start_date:
                        where_parts.append("meeting_date >= %s")
                        params.append(start_date)

                    if end_date:
                        where_parts.append("meeting_date <= %s")
                        params.append(end_date)

                    if view == "motions":
                        where_parts.append("""
                            id IN (
                                SELECT document_id
                                FROM motions
                            )
                        """)

                    elif view == "failed":
                        where_parts.append("""
                            id IN (
                                SELECT DISTINCT document_id
                                FROM motions
                                WHERE vote_result ILIKE '%failed%'
                                   OR vote_result ILIKE '%no%'
                                   OR vote_result ILIKE '%nay%'
                            )
                        """)

                    elif view == "abstentions":
                        where_parts.append("""
                            id IN (
                                SELECT m.document_id
                                FROM motions m
                                JOIN trustee_votes tv
                                  ON tv.motion_id = m.id
                                WHERE tv.vote ILIKE '%abstain%'
                                   OR tv.vote ILIKE '%abstention%'
                            )
                        """)

                    elif view == "documents":
                        where_parts.append("TRUE")

                    elif view == "ai_classified":
                        where_parts.append("""
                            id IN (
                                SELECT document_id
                                FROM ai_document_classifications
                            )
                        """)

                    elif view == "ai_votes":
                        where_parts.append("""
                            id IN (
                                SELECT document_id
                                FROM ai_document_classifications
                                WHERE contains_vote = TRUE
                            )
                        """)

                    elif view == "ai_failed_unclear":
                        where_parts.append("""
                            id IN (
                                SELECT document_id
                                FROM ai_document_classifications
                                WHERE vote_result IN ('Failed', 'Unclear')
                            )
                        """)

                    elif view == "ai_review":
                        where_parts.append("""
                            id IN (
                                SELECT document_id
                                FROM ai_document_classifications
                                WHERE needs_human_review = TRUE
                            )
                        """)

                    if trustee and vote:
                        where_parts.append("""
                            id IN (
                                SELECT m.document_id
                                FROM motions m
                                JOIN trustee_votes tv
                                  ON tv.motion_id = m.id
                                WHERE tv.trustee_name ILIKE %s
                                  AND tv.vote ILIKE %s
                            )
                        """)
                        params.extend([f"%{trustee}%", vote])

                    elif trustee:
                        where_parts.append("""
                            (
                                text_content ILIKE %s
                                OR id IN (
                                    SELECT m.document_id
                                    FROM motions m
                                    JOIN trustee_votes tv
                                      ON tv.motion_id = m.id
                                    WHERE tv.trustee_name ILIKE %s
                                )
                            )
                        """)
                        params.extend([f"%{trustee}%", f"%{trustee}%"])

                    where_sql = " AND ".join(where_parts) if where_parts else "TRUE"
                    search_query_for_rank = q if q else ""

                    sql = f"""
                        SELECT
                            source,
                            name,
                            url,
                            created,
                            modified,
                            meeting_date,
                            document_type,
                            source_url,
                            CASE
                                WHEN %s = '' THEN 0
                                ELSE ts_rank(
                                    search_vector,
                                    plainto_tsquery('english', %s)
                                )
                            END AS rank,
                            CASE
                                WHEN %s = '' THEN coalesce(left(text_content, 350), '')
                                ELSE ts_headline(
                                    'english',
                                    coalesce(text_content, ''),
                                    plainto_tsquery('english', %s),
                                    'StartSel=<mark>, StopSel=</mark>, MaxFragments=2, MaxWords=55, MinWords=15'
                                )
                            END AS match_context
                        FROM documents
                        WHERE {where_sql}
                        ORDER BY
                            rank DESC,
                            meeting_date DESC NULLS LAST,
                            modified DESC NULLS LAST
                        LIMIT 100
                    """

                    final_params = [
                        search_query_for_rank,
                        search_query_for_rank,
                        search_query_for_rank,
                        search_query_for_rank,
                    ] + params

                    cur.execute(sql, final_params)
                    results = cur.fetchall()

    except Exception as e:
        error = str(e)

    html_out = f"""
    <html>
    <head>
        <title>TimberWatch</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 30px;
                background: #fafafa;
            }}

            input, select {{
                padding: 8px;
                font-size: 14px;
                margin: 4px;
            }}

            button {{
                padding: 8px 12px;
            }}

            table {{
                border-collapse: collapse;
                width: 100%;
                margin-top: 20px;
                background: white;
            }}

            th, td {{
                border: 1px solid #ddd;
                padding: 8px;
                vertical-align: top;
            }}

            th {{
                background: #f2f2f2;
            }}

            mark {{
                background: yellow;
                font-weight: bold;
            }}

            .small {{
                font-size: 13px;
                color: #555;
            }}

            .cards {{
                display: flex;
                gap: 12px;
                flex-wrap: wrap;
                margin-bottom: 20px;
            }}

            .card {{
                background: white;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 14px;
                min-width: 150px;
                text-decoration: none;
                color: black;
                margin-bottom: 12px;
            }}

            a.card:hover, .topic-pill:hover {{
                background: #f0f6ff;
            }}

            .card .num {{
                font-size: 24px;
                font-weight: bold;
            }}

            .filters {{
                background: white;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 12px;
            }}

            .topic-pill {{
                display: inline-block;
                background: #e8eef7;
                padding: 5px 8px;
                border-radius: 12px;
                margin: 3px;
                text-decoration: none;
                color: black;
            }}

            .actions a {{
                white-space: nowrap;
            }}
        </style>
    </head>

    <body>
        <h1>TimberWatch</h1>

        <div class="cards">
            <a class="card" href="{search_url(view='documents')}">
                <div class="num">{dashboard['documents']}</div>
                <div>Total Documents</div>
            </a>

            <a class="card" href="{search_url(view='motions')}">
                <div class="num">{dashboard['motions']}</div>
                <div>Total Motions</div>
            </a>

            <a class="card" href="{search_url(view='failed')}">
                <div class="num">{dashboard['failed_motions']}</div>
                <div>Failed / Nay Motions</div>
            </a>

            <a class="card" href="{search_url(view='abstentions')}">
                <div class="num">{dashboard['abstentions']}</div>
                <div>Abstentions</div>
            </a>
        </div>

        <div class="cards">
            <a class="card" href="{search_url(view='ai_classified')}">
                <div class="num">{dashboard['ai_classified']}</div>
                <div>AI Classified Docs</div>
            </a>

            <a class="card" href="{search_url(view='ai_votes')}">
                <div class="num">{dashboard['ai_contains_votes']}</div>
                <div>AI Detected Votes</div>
            </a>

            <a class="card" href="{search_url(view='ai_failed_unclear')}">
                <div class="num">{dashboard['ai_failed_unclear']}</div>
                <div>AI Failed / Unclear</div>
            </a>

            <a class="card" href="{search_url(view='ai_review')}">
                <div class="num">{dashboard['ai_needs_review']}</div>
                <div>Needs Human Review</div>
            </a>
        </div>

        <div class="card">
            <b>Top Motion Topics</b><br>
    """

    if dashboard["topics"]:
        for topic, count in dashboard["topics"]:
            html_out += f"""
                <a class="topic-pill" href="{search_url(q=topic)}">
                    {esc(topic)}: {count}
                </a>
            """
    else:
        html_out += "<span class='small'>No motion topics indexed yet.</span>"

    html_out += """
        </div>

        <div class="card">
            <b>Top AI Topics</b><br>
    """

    if dashboard["ai_topics"]:
        for topic, count in dashboard["ai_topics"]:
            html_out += f"""
                <a class="topic-pill" href="{search_url(q=topic)}">
                    {esc(topic)}: {count}
                </a>
            """
    else:
        html_out += "<span class='small'>No AI topics classified yet.</span>"

    html_out += """
        </div>

        <div class="card">
            <b>Trustees</b><br>
    """

    if dashboard["trustees"]:
        for (trustee_name,) in dashboard["trustees"]:
            html_out += f"""
                <a class="topic-pill" href="{search_url(trustee=trustee_name)}">
                    {esc(trustee_name)}
                </a>
            """
    else:
        html_out += "<span class='small'>No trustee votes indexed yet.</span>"

    html_out += """
        </div>

        <div class="card">
            <b>Trustee Vote Scorecard</b><br><br>
            <table>
                <tr>
                    <th>Trustee</th>
                    <th>Ayes</th>
                    <th>Nays</th>
                    <th>Abstains</th>
                    <th>Absents</th>
                </tr>
    """

    if dashboard["trustee_scorecard"]:
        for trustee_name, ayes, nays, abstains, absents in dashboard["trustee_scorecard"]:
            html_out += f"""
                <tr>
                    <td><a href="{search_url(trustee=trustee_name)}">{esc(trustee_name)}</a></td>
                    <td><a href="{search_url(trustee=trustee_name, vote='Yes')}">{ayes}</a></td>
                    <td><a href="{search_url(trustee=trustee_name, vote='No')}">{nays}</a></td>
                    <td><a href="{search_url(trustee=trustee_name, vote='Abstain')}">{abstains}</a></td>
                    <td><a href="{search_url(trustee=trustee_name, vote='Absent')}">{absents}</a></td>
                </tr>
            """
    else:
        html_out += """
                <tr>
                    <td colspan="5" class="small">No trustee scorecard data indexed yet.</td>
                </tr>
        """

    html_out += f"""
            </table>
        </div>

        <form class="filters" action="/search" method="get">
            <input
                name="q"
                value="{esc(q)}"
                placeholder="Search documents..."
                style="width:360px;"
            >

            <select name="source">
                <option value="">All Sources</option>
                <option value="Board Documents" {'selected' if source == 'Board Documents' else ''}>Board Documents</option>
                <option value="BP/AP/AR" {'selected' if source == 'BP/AP/AR' else ''}>BP/AP/AR</option>
            </select>

            <select name="document_type">
                <option value="">All Document Types</option>
                <option value="Minutes" {'selected' if document_type == 'Minutes' else ''}>Minutes</option>
                <option value="Agenda" {'selected' if document_type == 'Agenda' else ''}>Agenda</option>
                <option value="Board Policy" {'selected' if document_type == 'Board Policy' else ''}>Board Policy</option>
                <option value="Administrative Procedure" {'selected' if document_type == 'Administrative Procedure' else ''}>Administrative Procedure</option>
                <option value="Other" {'selected' if document_type == 'Other' else ''}>Other</option>
            </select>

            <input type="date" name="start_date" value="{esc(start_date)}">
            <input type="date" name="end_date" value="{esc(end_date)}">

            <button type="submit">Search</button>
            <a href="/" style="margin-left:10px;">Clear</a>
        </form>

        <p><a href="/status">Status</a></p>
        <hr>
    """

    if error:
        html_out += f"<p style='color:red;'><b>Error:</b> {esc(error)}</p>"

    search_was_requested = bool(q or source or document_type or start_date or end_date or view or trustee or vote)

    if search_was_requested and not results and not error:
        html_out += "<p>No results found.</p>"

    if results:
        html_out += f"<p><b>{len(results)}</b> results found.</p>"
        html_out += """
        <table>
            <tr>
                <th>Document</th>
                <th>Source</th>
                <th>Type</th>
                <th>Meeting Date</th>
                <th>Created</th>
                <th>Modified</th>
                <th>Rank</th>
                <th>Matching Text</th>
                <th>Actions</th>
            </tr>
        """

        for row in results:
            (
                row_source,
                name,
                url,
                created,
                modified,
                meeting_date,
                row_document_type,
                source_url,
                rank,
                match_context,
            ) = row

            open_url = source_url or url or ""

            if open_url:
                actions = f"""
                    <a href="{esc(open_url)}" target="_blank">Open Original PDF</a><br>
                    <a href="{esc(open_url)}" download>Download</a>
                """
            else:
                actions = "<span class='small'>No link available</span>"

            html_out += f"""
            <tr>
                <td><b>{esc(name)}</b></td>
                <td>{esc(row_source)}</td>
                <td>{esc(row_document_type)}</td>
                <td>{esc(meeting_date)}</td>
                <td>{esc(created)}</td>
                <td>{esc(modified)}</td>
                <td>{round(rank or 0, 4)}</td>
                <td>{match_context or ''}</td>
                <td class="actions">{actions}</td>
            </tr>
            """

        html_out += "</table>"

    html_out += """
        <br>

        <div class="card">
            <h3>Definitions</h3>
            <p><b>Total Documents:</b> Number of indexed PDFs/documents currently in TimberWatch.</p>
            <p><b>Total Motions:</b> Motions extracted from board minutes.</p>
            <p><b>Failed / Nay Motions:</b> Motions containing failed or negative vote language.</p>
            <p><b>Abstentions:</b> Trustee votes detected as abstentions.</p>
            <p><b>AI Classified Docs:</b> Documents classified by the AI indexing script.</p>
            <p><b>AI Detected Votes:</b> Documents where the AI detected a vote or voting-related action.</p>
            <p><b>AI Failed / Unclear:</b> AI-classified documents with failed or unclear vote results.</p>
            <p><b>Needs Human Review:</b> AI-classified documents flagged as needing manual verification.</p>
            <p><b>Rank Score:</b> PostgreSQL relevance score. Higher usually means the search terms matched more strongly.</p>
            <p><b>Matching Text:</b> Highlighted text from the source document.</p>
        </div>

    </body>
    </html>
    """

    return html_out


@app.get("/run-ai")
def run_ai(key: str):
    admin_key = os.environ.get("ADMIN_KEY")

    if key != admin_key:
        raise HTTPException(
            status_code=403,
            detail="Unauthorized"
        )

    result = subprocess.run(
        ["python", "ai_classifier.py", "--limit", "1000"],
        capture_output=True,
        text=True
    )

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode
    }
