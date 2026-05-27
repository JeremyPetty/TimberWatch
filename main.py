import os
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
    results = []

    if q.strip():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT source, name, url,
                           ts_rank(search_vector, plainto_tsquery('english', %s)) AS rank
                    FROM documents
                    WHERE search_vector @@ plainto_tsquery('english', %s)
                       OR name ILIKE %s
                       OR text_content ILIKE %s
                    ORDER BY rank DESC NULLS LAST, modified DESC NULLS LAST
                    LIMIT 100
                """, (q, q, f"%{q}%", f"%{q}%"))

                results = cur.fetchall()

    html = f"""
    <h1>TimberTrack Search</h1>
    <form action="/search" method="get">
        <input name="q" value="{q}" style="width:400px;">
        <button type="submit">Search</button>
    </form>
    <hr>
    """

    for source, name, url, rank in results:
        html += f"""
        <p>
            <b>{name}</b><br>
            Source: {source}<br>
            <a href="{url}" target="_blank">Open Document</a>
        </p>
        <hr>
        """

    return html
