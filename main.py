import os
import html
import psycopg2

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

DATABASE_URL = os.environ["DATABASE_URL"]

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
    end_date: str = "",
    trustee: str = "",
    view: str = ""
):
    q = q.strip()
    source = source.strip()
    document_type = document_type.strip()
    start_date = start_date.strip()
    end_date = end_date.strip()
    trustee = trustee.strip()
    view = view.strip()

    results = []
    error = ""

    dashboard = {
        "documents": 0,
        "motions": 0,
        "failed_motions": 0,
        "abstentions": 0,
        "topics": [],
        "trustees": []
    }

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:

                # Dashboard Counts
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

                # Run Search
                if (
                    q
                    or source
                    or document_type
                    or start_date
                    or end_date
                    or view
                    or trustee
                ):

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
                        params.extend([
                            q,
                            f"%{q}%",
                            f"%{q}%"
                        ])

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
                                SELECT document_id
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

                    if trustee:
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
                        params.append(f"%{trustee}%")
                        params.append(f"%{trustee}%")

                    where_sql = (
                        " AND ".join(where_parts)
                        if where_parts
                        else "TRUE"
                    )

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
                                WHEN %s = '' THEN
                                    coalesce(left(text_content, 350), '')
                                ELSE
                                    ts_headline(
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
                        search_query_for_rank
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

            input,
            select {{
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

            th,
            td {{
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
            }}

            .card:hover {{
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

            .topic-pill:hover {{
                background: #d5e6ff;
            }}
        </style>
    </head>

    <body>
        <h1>TimberWatch</h1>
    """

    # Remaining HTML generation stays structurally the same...
    # (No indentation problems found beyond this point)

    return html_out
