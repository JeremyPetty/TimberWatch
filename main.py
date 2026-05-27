import os
import html
import psycopg2
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

app = FastAPI()


def get_conn():
    return psycopg2.connect(DATABASE_URL)


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <h1>TimberTrack</h1>
    <form action="/search" method="get">
        <input name="q" placeholder="Search documents..." style="width:400px;">
        <button type="submit">Search</button>
    </form>
    """


@app.get("/search", response_class=HTMLResponse)
def search(q: str = ""):
    q = q.strip()
    results = []
    error = ""

    if q:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            source,
                            name,
                            url,
                            created,
                            modified,
                            ts_headline(
                                'english',
                                coalesce(text_content, ''),
                                plainto_tsquery('english', %s),
                                'StartSel=<mark>, StopSel=</mark>, MaxWords=55, MinWords=20'
                            ) AS match_context
                        FROM documents
                        WHERE
                            search_vector @@ plainto_tsquery('english', %s)
                            OR name ILIKE %s
                            OR text_content ILIKE %s
                        ORDER BY modified DESC NULLS LAST
                        LIMIT 100
                    """, (q, q, f"%{q}%", f"%{q}%"))

                    results = cur.fetchall()

        except Exception as e:
            error = str(e)

    html_out = f"""
    <html>
    <head>
        <title>TimberWatch Search</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 30px; }}
            input {{ padding: 8px; font-size: 16px; }}
            button {{ padding: 8px 12px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
            th {{ background: #f2f2f2; }}
            mark {{ background: yellow; font-weight: bold; }}
            .small {{ font-size: 13px; color: #555; }}
        </style>
    </head>
    <body>
        <h1>TimberWatch Search</h1>

        <form action="/search" method="get">
            <input name="q" value="{html.escape(q)}" placeholder="Search documents..." style="width:450px;">
            <button type="submit">Search</button>
        </form>

        <p><a href="/status">Status</a></p>
        <hr>
    """

    if error:
        html_out += f"<p style='color:red;'><b>Error:</b> {html.escape(error)}</p>"

    if q and not results and not error:
        html_out += "<p>No results found.</p>"

    if results:
        html_out += f"<p><b>{len(results)}</b> results found.</p>"
        html_out += """
        <table>
            <tr>
                <th>Document</th>
                <th>Source</th>
                <th>Created On</th>
                <th>Modified On</th>
                <th>Matching Text</th>
                <th>Actions</th>
            </tr>
        """

        for source, name, url, created, modified, match_context in results:
            html_out += f"""
            <tr>
                <td><b>{html.escape(name)}</b></td>
                <td>{html.escape(source or "")}</td>
                <td>{html.escape(str(created or ""))}</td>
                <td>{html.escape(str(modified or ""))}</td>
                <td>{match_context or ""}</td>
                <td>
                    <a href="{html.escape(url)}" target="_blank">Open</a><br>
                    <a href="{html.escape(url)}" download>Download</a>
                </td>
            </tr>
            """

        html_out += "</table>"

    html_out += """
    </body>
    </html>
    """

    return html_out
    
print("Indexing complete.", flush=True)
