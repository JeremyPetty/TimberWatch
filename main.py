import os
import html
import psycopg2
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

app = FastAPI()


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def esc(value):
    return html.escape(str(value or ""))


@app.get("/", response_class=HTMLResponse)
def home():
    return search()


@app.get("/search", response_class=HTMLResponse)
def search(
    q: str = "",
    source: str = "",
    document_type: str = "",
    start_date: str = "",
    end_date: str = ""
):
    q = q.strip()
    source = source.strip()
    document_type = document_type.strip()
    start_date = start_date.strip()
    end_date = end_date.strip()

    results = []
    error = ""
    dashboard = {
        "documents": 0,
        "motions": 0,
        "failed_motions": 0,
        "abstentions": 0,
        "topics": []
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
                    WHERE topic IS NOT NULL AND topic <> ''
                    GROUP BY topic
                    ORDER BY COUNT(*) DESC
                    LIMIT 5
                """)
                dashboard["topics"] = cur.fetchall()

                if q or source or document_type or start_date or end_date or trustee:
                    where_parts = [
                        """
                        (
                            search_vector @@ plainto_tsquery('english', %s)
                            OR name ILIKE %s
                            OR text_content ILIKE %s
                        )
                        """
                    ]

                    params = [q, f"%{q}%", f"%{q}%"]

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
                            ts_rank(
                                search_vector,
                                plainto_tsquery('english', %s)
                            ) AS rank,
                            ts_headline(
                                'english',
                                coalesce(text_content, ''),
                                plainto_tsquery('english', %s),
                                'StartSel=<mark>, StopSel=</mark>, MaxFragments=2, MaxWords=55, MinWords=15'
                            ) AS match_context
                        FROM documents
                        WHERE {" AND ".join(where_parts)}
                        ORDER BY
                            rank DESC,
                            meeting_date DESC NULLS LAST,
                            modified DESC NULLS LAST
                        LIMIT 100
                    """

                    final_params = [q, q] + params
                    cur.execute(sql, final_params)
                    results = cur.fetchall()

    except Exception as e:
        error = str(e)

    html_out = f"""
    <html>
    <head>
        <title>TimberWatch</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 30px; background:#fafafa; }}
            input, select {{ padding: 8px; font-size: 14px; margin: 4px; }}
            button {{ padding: 8px 12px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; background:white; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
            th {{ background: #f2f2f2; }}
            mark {{ background: yellow; font-weight: bold; }}
            .small {{ font-size: 13px; color: #555; }}
            .cards {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
            .card {{ background:white; border:1px solid #ddd; border-radius:8px; padding:14px; min-width:150px; }}
            .card .num {{ font-size:24px; font-weight:bold; }}
            .filters {{ background:white; border:1px solid #ddd; border-radius:8px; padding:12px; }}
            .topic-pill {{ display:inline-block; background:#e8eef7; padding:5px 8px; border-radius:12px; margin:3px; }}
        </style>
    </head>
    <body>
        <h1>TimberWatch</h1>

        <div class="cards">
            <div class="card"><div class="num">{dashboard["documents"]}</div><div>Total Documents</div></div>
            <div class="card"><div class="num">{dashboard["motions"]}</div><div>Total Motions</div></div>
            <div class="card"><div class="num">{dashboard["failed_motions"]}</div><div>Failed / Nay Motions</div></div>
            <div class="card"><div class="num">{dashboard["abstentions"]}</div><div>Abstentions</div></div>
        </div>

        <div class="card">
            <b>Top Motion Topics</b><br>
    """

    if dashboard["topics"]:
        for topic, count in dashboard["topics"]:
            html_out += f"<span class='topic-pill'>{esc(topic)}: {count}</span>"
    else:
        html_out += "<span class='small'>No motion topics indexed yet.</span>"

    html_out += f"""
        </div>

        <br>

        <form class="filters" action="/search" method="get">
            <input name="q" value="{esc(q)}" placeholder="Search documents..." style="width:360px;">

            <input name="source" value="{esc(source)}" placeholder="Source">

            <form class="filters" action="/search" method="get">
    <input name="q" value="{esc(q)}" placeholder="Search documents..." style="width:360px;">

    <select name="source">
        <option value="">All Sources</option>
        <option value="Board Documents" {"selected" if source == "Board Documents" else ""}>
            Board Documents
        </option>
        <option value="BP/AP/AR" {"selected" if source == "BP/AP/AR" else ""}>
            BP/AP/AR
        </option>
    </select>

    <select name="document_type">
        <option value="">All Document Types</option>

        <option value="Minutes" {"selected" if document_type == "Minutes" else ""}>
            Minutes
        </option>

        <option value="Agenda" {"selected" if document_type == "Agenda" else ""}>
            Agenda
        </option>

        <option value="Board Policy" {"selected" if document_type == "Board Policy" else ""}>
            Board Policy
        </option>

        <option value="Administrative Procedure" {"selected" if document_type == "Administrative Procedure" else ""}>
            Administrative Procedure
        </option>

        <option value="Other" {"selected" if document_type == "Other" else ""}>
            Other
        </option>
    </select>

    <input type="date" name="start_date" value="{esc(start_date)}">

    <input type="date" name="end_date" value="{esc(end_date)}">

    <button type="submit">Search</button>

    <a href="/" style="margin-left:10px;">Clear</a>
</form>

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

    if q and not results and not error:
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
                match_context
            ) = row

            open_url = source_url or url or ""

            html_out += f"""
            <tr>
                <td><b>{esc(name)}</b></td>
                <td>{esc(row_source)}</td>
                <td>{esc(row_document_type)}</td>
                <td>{esc(meeting_date)}</td>
                <td>{esc(created)}</td>
                <td>{esc(modified)}</td>
                <td>{round(rank or 0, 4)}</td>
                <td>{match_context or ""}</td>
                <td>
                    <a href="{esc(open_url)}" target="_blank">Open Original PDF</a><br>
                    <a href="{esc(open_url)}" download>Download</a>
                </td>
            </tr>
            """

        html_out += "</table>"

    html_out += """
    </body>
    </html>
    """

    return html_out
