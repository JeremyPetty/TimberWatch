import os
from urllib.parse import urlencode

from flask import Flask, request, redirect, url_for, render_template
from psycopg2 import sql

from db import get_cursor
from utils import esc, fmt_date, to_int, clean_snippet, build_url, page_count

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")

PER_PAGE_OPTIONS = [25, 50, 100, 250]

def safe_money(value):
    if value is None:
        return "Not identified"

    value_str = str(value).strip()

    if value_str == "":
        return "Not identified"

    if "-" in value_str:
        parts = value_str.split("-", 1)
        try:
            low = float(parts[0].replace(",", "").replace("$", "").strip())
            high = float(parts[1].replace(",", "").replace("$", "").strip())
            return f"${low:,.0f} - ${high:,.0f}"
        except Exception:
            return esc(value_str)

    try:
        return f"${float(value_str.replace(',', '').replace('$', '')):,.2f}"
    except Exception:
        return esc(value_str)

DOC_SORTS = {
    "name": "d.name",
    "date": "COALESCE(d.meeting_date, d.created_at)",
    "created": "d.created_at",
    "modified": "d.modified_at",
    "source": "d.source",
    "category": "d.document_type",
}

VOTE_SORTS = {
    "trustee": "t.name",
    "yes": "yes_votes",
    "no": "no_votes",
    "abstain": "abstain_votes",
    "absent": "absent_votes",
    "total": "total_votes",
}


def layout(title: str, body: str) -> str:
    return f"""
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{esc(title)} - TimberWatch</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #f6f7f8; color: #222; }}
    header {{ background: #163024; color: white; padding: 18px 28px; }}
    header a {{ color: white; margin-right: 18px; text-decoration: none; font-weight: bold; }}
    main {{ padding: 24px; max-width: 1400px; margin: auto; }}
    .card {{ background: white; border-radius: 10px; padding: 18px; margin-bottom: 18px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    table {{ width: 100%; border-collapse: collapse; background: white; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #ddd; vertical-align: top; }}
    th {{ background: #edf2ef; text-align: left; white-space: nowrap; }}
    th a {{ color: #163024; text-decoration: none; }}
    .muted {{ color: #666; font-size: 0.92em; }}
    .snippet {{ color: #333; max-width: 620px; }}
    .btn, button {{ display: inline-block; padding: 7px 10px; border-radius: 6px; background: #1f6f4a; color: white; text-decoration: none; border: 0; cursor: pointer; }}
    .btn.secondary {{ background: #54646b; }}
    .btn.light {{ background: #e8ece9; color: #163024; }}
    input, select {{ padding: 8px; border: 1px solid #bbb; border-radius: 6px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; }}
    .stat {{ font-size: 1.8em; font-weight: bold; }}
    .pager {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 14px; }}
    .pill {{ display: inline-block; background: #edf2ef; border-radius: 999px; padding: 4px 9px; margin: 2px; }}
    .danger {{ color: #8a1c1c; }}
  </style>
</head>
<body>
<header>
  <a href=\"/\">TimberWatch</a>
  <a href=\"/search\">Documents</a>
  <a href=\"/motions\">Motions</a>
  <a href=\"/trustees\">Trustees</a>
  <a href=\"/topics\">Topics</a>
  <a href=\"/failed-motions\">Failed Motions</a>
</header>
<main>{body}</main>
</body>
</html>
"""


def sort_link(path, label, sort_key, current_sort, direction, **params):
    next_dir = "desc" if current_sort == sort_key and direction == "asc" else "asc"
    symbol = " ▲" if current_sort == sort_key and direction == "asc" else (" ▼" if current_sort == sort_key else "")
    params.update({"sort": sort_key, "dir": next_dir, "page": 1})
    return f'<a href="{esc(build_url(path, **params))}">{esc(label)}{symbol}</a>'


@app.route("/")
def home():
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM documents")
        documents = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM motions")
        motions = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM trustee_votes")
        votes = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM trustees WHERE COALESCE(is_current, true)=true")
        trustees = cur.fetchone()["n"]
        cur.execute("""
            SELECT
                COALESCE(NULLIF(document_category, ''), NULLIF(category, '')) AS category,
                COUNT(*) AS n
            FROM ai_document_classifications
            WHERE COALESCE(NULLIF(document_category, ''), NULLIF(category, '')) IS NOT NULL
            GROUP BY COALESCE(NULLIF(document_category, ''), NULLIF(category, ''))
            ORDER BY n DESC, category
            LIMIT 10
        """)
        categories = cur.fetchall()

    body = f"""
    <div class=\"card\">
      <h1>TimberWatch Dashboard</h1>
      <p class=\"muted\">Board document search, motion tracking, trustee vote analytics, and topic patterns.</p>
    </div>
    <div class=\"grid\">
      <div class=\"card\"><div class=\"stat\">{documents:,}</div><div>Documents</div></div>
      <div class=\"card\"><div class=\"stat\">{motions:,}</div><div>Motions</div></div>
      <div class=\"card\"><div class=\"stat\">{votes:,}</div><div>Trustee Votes</div></div>
      <div class=\"card\"><div class=\"stat\">{trustees:,}</div><div>Current Trustees</div></div>
    </div>
    <div class=\"card\">
      <h2>Top Document Categories</h2>
      {' '.join(f'<a class="pill" href="/search?category={esc(row["category"])}">{esc(row["category"])} ({row["n"]})</a>' for row in categories) or '<span class="muted">No categories yet.</span>'}
    </div>
    """
    return layout("Dashboard", body)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    topic = request.args.get("topic", "").strip()
    sort = request.args.get("sort", "date")
    direction = request.args.get("dir", "desc")
    page = to_int(request.args.get("page", 1), default=1, minimum=1)
    per_page = to_int(request.args.get("per_page", 25), default=25, minimum=1, maximum=250)

    if per_page not in PER_PAGE_OPTIONS:
        per_page = 25

    sort_expr = DOC_SORTS.get(sort, DOC_SORTS["date"])
    direction_sql = "ASC" if direction == "asc" else "DESC"
    offset = (page - 1) * per_page

    # Category now comes from the best available source:
    # latest AI classification first, then documents.document_type as fallback.
    category_expr = "COALESCE(NULLIF(c.document_category, ''), NULLIF(c.category, ''), NULLIF(d.document_type, ''))"

    where = []
    params = []

    if q:
        where.append("""(
            d.name ILIKE %s OR
            d.text_content ILIKE %s OR
            COALESCE(d.document_type, '') ILIKE %s OR
            COALESCE(d.source, '') ILIKE %s OR
            COALESCE(c.document_category, '') ILIKE %s OR
            COALESCE(c.category, '') ILIKE %s OR
            COALESCE(c.primary_topic, '') ILIKE %s
        )""")
        like = f"%{q}%"
        params.extend([like, like, like, like, like, like, like])

    if category:
        where.append(f"{category_expr} = %s")
        params.append(category)

    if topic:
        where.append("mt.topic = %s")
        params.append(topic)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    count_sql = f"""
        SELECT COUNT(DISTINCT d.id) AS total
        FROM documents d
        LEFT JOIN LATERAL (
            SELECT *
            FROM ai_document_classifications c2
            WHERE c2.document_id = d.id
            ORDER BY c2.created_at DESC NULLS LAST
            LIMIT 1
        ) c ON true
        LEFT JOIN motions m ON m.document_id = d.id
        LEFT JOIN motion_topics mt ON mt.motion_id = m.id
        {where_sql}
    """

    data_sql = f"""
        SELECT DISTINCT ON (d.id)
            d.id,
            d.name,
            d.url,
            d.source,
            {category_expr} AS display_category,
            d.document_type,
            d.created_at,
            d.modified_at,
            d.meeting_date,
            c.document_category,
            c.category AS classification_category,
            c.vote_result,
            CASE
              WHEN %s <> '' AND d.text_content ILIKE %s
              THEN ts_headline(
                    'english',
                    d.text_content,
                    plainto_tsquery('english', %s),
                    'MaxWords=45, MinWords=18'
              )
              ELSE LEFT(COALESCE(d.text_content, ''), 360)
            END AS snippet
        FROM documents d
        LEFT JOIN LATERAL (
            SELECT *
            FROM ai_document_classifications c2
            WHERE c2.document_id = d.id
            ORDER BY c2.created_at DESC NULLS LAST
            LIMIT 1
        ) c ON true
        LEFT JOIN motions m ON m.document_id = d.id
        LEFT JOIN motion_topics mt ON mt.motion_id = m.id
        {where_sql}
        ORDER BY d.id, {sort_expr} {direction_sql} NULLS LAST
        LIMIT %s OFFSET %s
    """

    with get_cursor() as cur:
        cur.execute(count_sql, params)
        total = cur.fetchone()["total"]

        cur.execute(data_sql, [q, f"%{q}%", q] + params + [per_page, offset])
        rows = cur.fetchall()

        cur.execute("""
            SELECT category
            FROM (
                SELECT DISTINCT NULLIF(TRIM(document_category), '') AS category
                FROM ai_document_classifications
                WHERE NULLIF(TRIM(document_category), '') IS NOT NULL
                UNION
                SELECT DISTINCT NULLIF(TRIM(category), '') AS category
                FROM ai_document_classifications
                WHERE NULLIF(TRIM(category), '') IS NOT NULL
                UNION
                SELECT DISTINCT NULLIF(TRIM(document_type), '') AS category
                FROM documents
                WHERE NULLIF(TRIM(document_type), '') IS NOT NULL
            ) x
            WHERE category IS NOT NULL
            ORDER BY category
        """)
        category_options = cur.fetchall()

    total_pages = page_count(total, per_page)
    base_params = {
        "q": q,
        "category": category,
        "topic": topic,
        "per_page": per_page,
        "sort": sort,
        "dir": direction,
    }

    body = f"""
    <div class="card">
      <h1>Document Search</h1>
      <form method="get" action="/search">
        <input type="hidden" name="topic" value="{esc(topic)}">
        <input name="q" value="{esc(q)}" placeholder="Search documents, text, Board Policy..." size="45">
        <label for="category"><strong>Category:</strong></label>
        <select id="category" name="category">
          <option value="">All Categories</option>
          {''.join(f'<option value="{esc(row["category"])}" {"selected" if row["category"] == category else ""}>{esc(row["category"])}</option>' for row in category_options)}
        </select>
        <select name="per_page">
          {''.join(f'<option value="{n}" {"selected" if n == per_page else ""}>{n} per page</option>' for n in PER_PAGE_OPTIONS)}
        </select>
        <button>Search</button>
      </form>
      <p class="muted">Showing {len(rows):,} of {total:,} results. Page {page:,} of {total_pages:,}.</p>
    </div>

    <div class="card">
      <table>
        <tr>
          <th>Name</th>
          <th>Date</th>
          <th>Source</th>
          <th>Category</th>
          <th>Matching Text</th>
          <th>Links</th>
        </tr>
    """

    for r in rows:
        url = r.get("url") or ""
        body += f"""
        <tr>
          <td><a href="/documents/{r['id']}">{esc(r['name'])}</a></td>
          <td>{esc(fmt_date(r.get('meeting_date') or r.get('created_at')))}</td>
          <td>{esc(r.get('source'))}</td>
          <td>{esc(r.get('display_category') or r.get('document_type'))}</td>
          <td class="snippet">{clean_snippet(r.get('snippet') or '')}</td>
          <td>{f'<a class="btn" target="_blank" href="{esc(url)}">Open</a>' if url else ''}</td>
        </tr>
        """

    if not rows:
        body += '<tr><td colspan="6" class="muted">No results found.</td></tr>'

    body += "</table>"
    body += render_pager("/search", page, total_pages, base_params)
    body += "</div>"

    return layout("Search", body)

def render_pager(path, page, total_pages, params):
    html = '<div class="pager">'
    if page > 1:
        p = dict(params, page=page - 1)
        html += f'<a class="btn secondary" href="{esc(build_url(path, **p))}">Previous</a>'
    start = max(1, page - 3)
    end = min(total_pages, page + 3)
    for n in range(start, end + 1):
        p = dict(params, page=n)
        cls = "btn" if n == page else "btn light"
        html += f'<a class="{cls}" href="{esc(build_url(path, **p))}">{n}</a>'
    if page < total_pages:
        p = dict(params, page=page + 1)
        html += f'<a class="btn secondary" href="{esc(build_url(path, **p))}">Next</a>'
    html += '</div>'
    return html


@app.route("/documents")
def documents_index():
    return redirect(url_for("search"))


@app.route("/documents/<int:document_id>")
def document_detail(document_id):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM documents WHERE id=%s", [document_id])
        doc = cur.fetchone()

        if not doc:
            return layout("Not Found", '<div class="card">Document not found.</div>'), 404

        cur.execute("""
            SELECT *
            FROM ai_document_classifications
            WHERE document_id=%s
            ORDER BY created_at DESC NULLS LAST
        """, [document_id])
        classifications = cur.fetchall()

        cur.execute("""
            SELECT *
            FROM motions
            WHERE document_id=%s
            ORDER BY id
        """, [document_id])
        motions = cur.fetchall()

    body = f"""
    <div class="card">
      <h1>{esc(doc.get('name'))}</h1>
      <p class="muted">
        Date: {esc(fmt_date(doc.get('meeting_date') or doc.get('created_at')))}
        | Source: {esc(doc.get('source'))}
        | Category: {esc(doc.get('document_type'))}
      </p>
      {f'<p><a class="btn" target="_blank" href="{esc(doc.get("url"))}">Open Original</a></p>' if doc.get('url') else ''}
    </div>
    """

    body += """
    <div class="card">
      <h2>Classification</h2>
    """

    if classifications:
        body += """
        <table>
          <tr>
            <th>Document Category</th>
            <th>Primary Topic</th>
            <th>Category</th>
            <th>Confidence</th>
            <th>Vote Result</th>
          </tr>
        """

        for c in classifications:
            body += f"""
            <tr>
              <td>{esc(c.get('document_category') or '')}</td>
              <td>{esc(c.get('primary_topic') or '')}</td>
              <td>{esc(c.get('category') or '')}</td>
              <td>{esc(c.get('classification_confidence') or c.get('confidence') or '')}</td>
              <td>{esc(c.get('vote_result') or '')}</td>
            </tr>
            """

        body += "</table>"
    else:
        body += '<p class="muted">No classification records found for this document.</p>'

    body += "</div>"

    body += """
    <div class="card">
      <h2>Motions</h2>
    """

    if motions:
        for m in motions:
            body += (
                f'<p><a href="/motions/{m["id"]}"><b>Motion {m["id"]}</b></a>: '
                f'{esc(clean_snippet(m.get("motion_text"), 600))}</p>'
            )
    else:
        body += '<p class="muted">No motions linked to this document.</p>'

    body += "</div>"

    return layout(doc.get("name") or "Document", body)





def pct(numerator, denominator):
    try:
        if not denominator:
            return "0.0%"
        return f"{(float(numerator or 0) / float(denominator or 0) * 100):.1f}%"
    except Exception:
        return "0.0%"


@app.route("/motions")
def motions():
    q = request.args.get("q", "").strip()
    topic = request.args.get("topic", "").strip()
    page = to_int(request.args.get("page", 1), default=1, minimum=1)
    per_page = to_int(request.args.get("per_page", 25), default=25, minimum=1, maximum=100)

    where = []
    params = []

    if q:
        where.append("m.motion_text ILIKE %s")
        params.append(f"%{q}%")

    if topic:
        where.append("EXISTS (SELECT 1 FROM motion_topics mtf WHERE mtf.motion_id = m.id AND mtf.topic = %s)")
        params.append(topic)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    offset = (page - 1) * per_page

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT COUNT(*) AS total
            FROM motions m
            {where_sql}
        """, params)
        total = cur.fetchone()["total"]

        cur.execute(f"""
            SELECT
                m.id,
                m.motion_text,
                m.result,
                d.name AS document_name,
                COALESCE(m.meeting_date, d.meeting_date) AS meeting_date,
                COALESCE((
                    SELECT STRING_AGG(DISTINCT mt.topic, ', ')
                    FROM motion_topics mt
                    WHERE mt.motion_id = m.id
                ), '') AS topics,
                COALESCE((
                    SELECT COUNT(*)
                    FROM trustee_votes tv
                    WHERE tv.motion_id = m.id
                      AND LOWER(TRIM(tv.vote)) IN ('yes','aye','ayes','y')
                ), 0) AS yes_votes,
                COALESCE((
                    SELECT COUNT(*)
                    FROM trustee_votes tv
                    WHERE tv.motion_id = m.id
                      AND LOWER(TRIM(tv.vote)) IN ('no','nay','nays','n')
                ), 0) AS no_votes,
                COALESCE((
                    SELECT COUNT(*)
                    FROM trustee_votes tv
                    WHERE tv.motion_id = m.id
                      AND LOWER(TRIM(tv.vote)) LIKE 'abstain%%'
                ), 0) AS abstain_votes,
                COALESCE((
                    SELECT COUNT(*)
                    FROM trustee_votes tv
                    WHERE tv.motion_id = m.id
                      AND LOWER(TRIM(tv.vote)) LIKE 'absent%%'
                ), 0) AS absent_votes
            FROM motions m
            LEFT JOIN documents d ON d.id = m.document_id
            {where_sql}
            ORDER BY COALESCE(m.meeting_date, d.meeting_date) DESC NULLS LAST, m.id DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        rows = cur.fetchall()

    total_pages = page_count(total, per_page)

    body = f"""
    <div class="card">
      <h1>Motions</h1>
      <form method="get" action="/motions">
        <input name="q" value="{esc(q)}" placeholder="Search motion text">
        <input name="topic" value="{esc(topic)}" placeholder="Topic">
        <select name="per_page">
          {''.join(f'<option value="{n}" {"selected" if n == per_page else ""}>{n} per page</option>' for n in [25, 50, 100])}
        </select>
        <button>Search</button>
      </form>
      <p class="muted">Showing {len(rows):,} of {total:,}</p>
    </div>
    <div class="card">
      <table>
        <tr>
          <th>ID</th>
          <th>Date</th>
          <th>Motion</th>
          <th>Result</th>
          <th>Margin</th>
          <th>Yes</th>
          <th>No</th>
          <th>Topic(s)</th>
          <th>Document</th>
        </tr>
    """

    for r in rows:
        yes_votes = r.get('yes_votes') or 0
        no_votes = r.get('no_votes') or 0
        vote_margin = yes_votes - no_votes
        body += f"""
        <tr>
          <td><a href="/motions/{r['id']}">{r['id']}</a></td>
          <td>{esc(fmt_date(r.get('meeting_date')))}</td>
          <td>{esc(clean_snippet(r.get('motion_text'), 260))}</td>
          <td>{esc(r.get('result'))}</td>
          <td>{vote_margin}</td>
          <td>{yes_votes}</td>
          <td>{no_votes}</td>
          <td>{esc(r.get('topics'))}</td>
          <td>{esc(r.get('document_name'))}</td>
        </tr>
        """

    if not rows:
        body += '<tr><td colspan="9" class="muted">No motions found.</td></tr>'

    body += "</table>"
    body += render_pager("/motions", page, total_pages, {"q": q, "topic": topic, "per_page": per_page})
    body += "</div>"

    return layout("Motions", body)

@app.route("/motion/<int:motion_id>")
def old_motion_detail_redirect(motion_id):
    return redirect(url_for("motion_detail", motion_id=motion_id))


@app.route("/motions/<int:motion_id>")
def motion_detail(motion_id):
    with get_cursor() as cur:
        cur.execute("""
            SELECT
                m.*,
                d.id AS document_id,
                d.name AS document_name,
                d.url AS document_url,
                d.source AS document_source,
                COALESCE(m.meeting_date, d.meeting_date) AS display_meeting_date
            FROM motions m
            LEFT JOIN documents d ON d.id = m.document_id
            WHERE m.id = %s
        """, [motion_id])
        motion = cur.fetchone()

        if not motion:
            return layout("Motion Not Found", '<div class="card">Motion not found.</div>'), 404

        cur.execute("""
            SELECT
                COALESCE(a.normalized_name, tv.trustee_name) AS trustee_name,
                tv.vote
            FROM trustee_votes tv
            LEFT JOIN trustee_name_aliases a
                ON LOWER(TRIM(tv.trustee_name)) = LOWER(TRIM(a.raw_name))
            WHERE tv.motion_id = %s
              AND COALESCE(a.normalized_name, tv.trustee_name) IS NOT NULL
              AND TRIM(COALESCE(a.normalized_name, tv.trustee_name)) <> ''
              AND LOWER(TRIM(COALESCE(a.normalized_name, tv.trustee_name))) <> 'all'
            ORDER BY trustee_name
        """, [motion_id])
        votes = cur.fetchall()

        cur.execute("""
            SELECT topic, confidence
            FROM motion_topics
            WHERE motion_id = %s
            ORDER BY topic
        """, [motion_id])
        topics = cur.fetchall()

    yes_votes = sum(1 for v in votes if str(v.get("vote") or "").strip().lower() in ("yes", "aye", "ayes", "y"))
    no_votes = sum(1 for v in votes if str(v.get("vote") or "").strip().lower() in ("no", "nay", "nays", "n"))
    computed_margin = yes_votes - no_votes
    vote_margin = motion.get("vote_margin")
    if vote_margin is None:
        vote_margin = computed_margin

    topic_html = " ".join(
        f'<a class="pill" href="{esc(build_url("/motions", topic=t.get("topic")))}">{esc(t.get("topic"))}</a>'
        for t in topics
    ) or '<span class="muted">No topics found.</span>'

    votes_html = ""
    for v in votes:
        votes_html += f"""
        <tr>
            <td>{esc(v.get('trustee_name'))}</td>
            <td>{esc(v.get('vote'))}</td>
        </tr>
        """

    if not votes:
        votes_html = '<tr><td colspan="2" class="muted">No trustee votes found for this motion.</td></tr>'

    source_doc = "Not linked"
    if motion.get("document_id"):
        source_doc = f'<a href="/documents/{motion.get("document_id")}">{esc(motion.get("document_name") or "Source Document")}</a>'

    body = f"""
    <div class="card">
        <p><a href="/documents/{motion.get('document_id')}">← Back to Document</a></p>
        <h1>Motion {motion['id']}</h1>
        <p class="muted">
            Date: {esc(fmt_date(motion.get('display_meeting_date')))}
            | Result: {esc(motion.get('result') or 'Unknown')}
            | Vote Margin: {esc(vote_margin)}
        </p>
    </div>

    <div class="card">
        <h2>Motion Text</h2>
        <p>{esc(motion.get('motion_text') or 'No motion text available.')}</p>
    </div>

    <div class="grid">
        <div class="card"><div class="stat">{yes_votes}</div><div>Yes Votes</div></div>
        <div class="card"><div class="stat">{no_votes}</div><div>No Votes</div></div>
        <div class="card"><div class="stat">{esc(vote_margin)}</div><div>Vote Margin</div></div>
        <div class="card"><div class="stat">{len(votes)}</div><div>Total Trustee Votes</div></div>
    </div>

    <div class="card">
        <h2>Topic(s)</h2>
        <p>{topic_html}</p>
    </div>

    <div class="card">
        <h2>Source Document</h2>
        <p>
            <strong>Document:</strong> {source_doc}<br>
            <strong>Source:</strong> {esc(motion.get('document_source') or 'Not identified')}
        </p>
        {f'<p><a class="btn" target="_blank" href="{esc(motion.get("document_url"))}">Open Original</a></p>' if motion.get("document_url") else ''}
    </div>

    <div class="card">
        <h2>Trustee Votes</h2>
        <table>
            <tr><th>Trustee</th><th>Vote</th></tr>
            {votes_html}
        </table>
    </div>
    """

    return layout(f"Motion {motion_id}", body)


@app.route("/trustees")
def trustees():
    sort = request.args.get("sort", "trustee")
    direction = request.args.get("dir", "asc")

    sort_map = {
        "trustee": "trustee_name",
        "yes": "yes_votes",
        "no": "no_votes",
        "abstain": "abstain_votes",
        "absent": "absent_votes",
        "total": "total_votes",
        "majority": "majority_pct",
        "attendance": "attendance_pct",
    }

    sort_expr = sort_map.get(sort, "trustee_name")
    dir_sql = "ASC" if direction == "asc" else "DESC"

    with get_cursor() as cur:
        cur.execute(f"""
            WITH normalized_votes AS (
                SELECT
                    tv.id,
                    tv.motion_id,
                    LOWER(TRIM(tv.vote)) AS vote_norm,
                    COALESCE(a.normalized_name, tv.trustee_name) AS trustee_name
                FROM trustee_votes tv
                LEFT JOIN trustee_name_aliases a
                    ON LOWER(TRIM(tv.trustee_name)) = LOWER(TRIM(a.raw_name))
                WHERE COALESCE(a.normalized_name, tv.trustee_name) IS NOT NULL
                  AND TRIM(COALESCE(a.normalized_name, tv.trustee_name)) <> ''
                  AND LOWER(TRIM(COALESCE(a.normalized_name, tv.trustee_name))) <> 'all'
            ),
            majority_by_motion AS (
                SELECT
                    motion_id,
                    CASE
                        WHEN COUNT(*) FILTER (WHERE vote_norm IN ('yes','aye','ayes','y')) >
                             COUNT(*) FILTER (WHERE vote_norm IN ('no','nay','nays','n')) THEN 'yes'
                        WHEN COUNT(*) FILTER (WHERE vote_norm IN ('no','nay','nays','n')) >
                             COUNT(*) FILTER (WHERE vote_norm IN ('yes','aye','ayes','y')) THEN 'no'
                        ELSE NULL
                    END AS majority_vote
                FROM normalized_votes
                GROUP BY motion_id
            ),
            trustee_stats AS (
                SELECT
                    t.id,
                    t.name AS trustee_name,
                    t.ward,
                    t.is_current,
                    COUNT(nv.id) AS total_votes,
                    COUNT(nv.id) FILTER (WHERE nv.vote_norm IN ('yes','aye','ayes','y')) AS yes_votes,
                    COUNT(nv.id) FILTER (WHERE nv.vote_norm IN ('no','nay','nays','n')) AS no_votes,
                    COUNT(nv.id) FILTER (WHERE nv.vote_norm LIKE 'abstain%%') AS abstain_votes,
                    COUNT(nv.id) FILTER (WHERE nv.vote_norm LIKE 'absent%%') AS absent_votes,
                    ROUND(100.0 * COUNT(nv.id) FILTER (WHERE nv.vote_norm IN ('yes','aye','ayes','y')) / NULLIF(COUNT(nv.id), 0), 1) AS yes_pct,
                    ROUND(100.0 * COUNT(nv.id) FILTER (WHERE nv.vote_norm IN ('no','nay','nays','n')) / NULLIF(COUNT(nv.id), 0), 1) AS no_pct,
                    ROUND(100.0 * COUNT(nv.id) FILTER (WHERE nv.vote_norm LIKE 'abstain%%') / NULLIF(COUNT(nv.id), 0), 1) AS abstain_pct,
                    ROUND(100.0 * COUNT(nv.id) FILTER (WHERE nv.vote_norm NOT LIKE 'absent%%') / NULLIF(COUNT(nv.id), 0), 1) AS attendance_pct,
                    ROUND(
                        100.0 * COUNT(nv.id) FILTER (
                            WHERE mbm.majority_vote IS NOT NULL
                              AND (
                                (mbm.majority_vote = 'yes' AND nv.vote_norm IN ('yes','aye','ayes','y')) OR
                                (mbm.majority_vote = 'no' AND nv.vote_norm IN ('no','nay','nays','n'))
                              )
                        ) / NULLIF(COUNT(nv.id) FILTER (WHERE mbm.majority_vote IS NOT NULL), 0),
                        1
                    ) AS majority_pct
                FROM trustees t
                LEFT JOIN normalized_votes nv
                    ON LOWER(TRIM(nv.trustee_name)) = LOWER(TRIM(t.name))
                LEFT JOIN majority_by_motion mbm ON mbm.motion_id = nv.motion_id
                WHERE COALESCE(t.is_current, false) = true
                GROUP BY t.id, t.name, t.ward, t.is_current
            )
            SELECT *
            FROM trustee_stats
            ORDER BY {sort_expr} {dir_sql} NULLS LAST;
        """)
        rows = cur.fetchall()

    body = """
    <div class="card">
        <h1>Trustee Scorecard</h1>
        <p class="muted">Current trustees only. Vote names are normalized through trustee_name_aliases.</p>
    </div>

    <div class="card">
        <table>
            <tr>
    """

    for label, key in [
        ("Trustee", "trustee"),
        ("Yes", "yes"),
        ("No", "no"),
        ("Abstain", "abstain"),
        ("Absent", "absent"),
        ("Total", "total"),
        ("With Majority", "majority"),
        ("Attendance", "attendance"),
    ]:
        body += f"<th>{sort_link('/trustees', label, key, sort, direction)}</th>"

    body += "<th>Yes %</th><th>No %</th><th>Abstain %</th><th>Ward</th></tr>"

    for r in rows:
        trustee_display = esc(r["trustee_name"])
        body += f"""
        <tr>
            <td><a href="/trustees/{r['id']}">{trustee_display}</a></td>
            <td>{r.get('yes_votes') or 0}</td>
            <td>{r.get('no_votes') or 0}</td>
            <td>{r.get('abstain_votes') or 0}</td>
            <td>{r.get('absent_votes') or 0}</td>
            <td>{r.get('total_votes') or 0}</td>
            <td>{esc(r.get('majority_pct') if r.get('majority_pct') is not None else '0.0')}%</td>
            <td>{esc(r.get('attendance_pct') if r.get('attendance_pct') is not None else '0.0')}%</td>
            <td>{esc(r.get('yes_pct') if r.get('yes_pct') is not None else '0.0')}%</td>
            <td>{esc(r.get('no_pct') if r.get('no_pct') is not None else '0.0')}%</td>
            <td>{esc(r.get('abstain_pct') if r.get('abstain_pct') is not None else '0.0')}%</td>
            <td>{esc(r.get('ward') or '')}</td>
        </tr>
        """

    if not rows:
        body += '<tr><td colspan="12" class="muted">No current trustees found.</td></tr>'

    body += """
        </table>
    </div>
    """

    return layout("Trustees", body)


@app.route("/trustees/<int:trustee_id>")
def trustee_detail(trustee_id):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM trustees WHERE id = %s AND COALESCE(is_current, false) = true", [trustee_id])
        trustee = cur.fetchone()
        if not trustee:
            return layout("Not Found", '<div class="card">Current trustee not found.</div>'), 404

        cur.execute("""
            WITH normalized_votes AS (
                SELECT
                    tv.id,
                    tv.motion_id,
                    tv.vote,
                    LOWER(TRIM(tv.vote)) AS vote_norm,
                    COALESCE(a.normalized_name, tv.trustee_name) AS trustee_name
                FROM trustee_votes tv
                LEFT JOIN trustee_name_aliases a
                    ON LOWER(TRIM(tv.trustee_name)) = LOWER(TRIM(a.raw_name))
                WHERE COALESCE(a.normalized_name, tv.trustee_name) IS NOT NULL
                  AND TRIM(COALESCE(a.normalized_name, tv.trustee_name)) <> ''
                  AND LOWER(TRIM(COALESCE(a.normalized_name, tv.trustee_name))) <> 'all'
            ),
            majority_by_motion AS (
                SELECT
                    motion_id,
                    CASE
                        WHEN COUNT(*) FILTER (WHERE vote_norm IN ('yes','aye','ayes','y')) >
                             COUNT(*) FILTER (WHERE vote_norm IN ('no','nay','nays','n')) THEN 'yes'
                        WHEN COUNT(*) FILTER (WHERE vote_norm IN ('no','nay','nays','n')) >
                             COUNT(*) FILTER (WHERE vote_norm IN ('yes','aye','ayes','y')) THEN 'no'
                        ELSE NULL
                    END AS majority_vote
                FROM normalized_votes
                GROUP BY motion_id
            )
            SELECT
                COUNT(nv.id) AS total_votes,
                COUNT(nv.id) FILTER (WHERE nv.vote_norm IN ('yes','aye','ayes','y')) AS yes_votes,
                COUNT(nv.id) FILTER (WHERE nv.vote_norm IN ('no','nay','nays','n')) AS no_votes,
                COUNT(nv.id) FILTER (WHERE nv.vote_norm LIKE 'abstain%%') AS abstain_votes,
                COUNT(nv.id) FILTER (WHERE nv.vote_norm LIKE 'absent%%') AS absent_votes,
                ROUND(100.0 * COUNT(nv.id) FILTER (WHERE nv.vote_norm IN ('yes','aye','ayes','y')) / NULLIF(COUNT(nv.id), 0), 1) AS yes_pct,
                ROUND(100.0 * COUNT(nv.id) FILTER (WHERE nv.vote_norm IN ('no','nay','nays','n')) / NULLIF(COUNT(nv.id), 0), 1) AS no_pct,
                ROUND(100.0 * COUNT(nv.id) FILTER (WHERE nv.vote_norm LIKE 'abstain%%') / NULLIF(COUNT(nv.id), 0), 1) AS abstain_pct,
                ROUND(100.0 * COUNT(nv.id) FILTER (WHERE nv.vote_norm NOT LIKE 'absent%%') / NULLIF(COUNT(nv.id), 0), 1) AS attendance_pct,
                ROUND(
                    100.0 * COUNT(nv.id) FILTER (
                        WHERE mbm.majority_vote IS NOT NULL
                          AND (
                            (mbm.majority_vote = 'yes' AND nv.vote_norm IN ('yes','aye','ayes','y')) OR
                            (mbm.majority_vote = 'no' AND nv.vote_norm IN ('no','nay','nays','n'))
                          )
                    ) / NULLIF(COUNT(nv.id) FILTER (WHERE mbm.majority_vote IS NOT NULL), 0),
                    1
                ) AS majority_pct
            FROM normalized_votes nv
            LEFT JOIN majority_by_motion mbm ON mbm.motion_id = nv.motion_id
            WHERE LOWER(TRIM(nv.trustee_name)) = LOWER(TRIM(%s))
        """, [trustee.get("name")])
        stats = cur.fetchone()

        cur.execute("""
            WITH normalized_votes AS (
                SELECT
                    tv.id,
                    tv.motion_id,
                    tv.vote,
                    LOWER(TRIM(tv.vote)) AS vote_norm,
                    COALESCE(a.normalized_name, tv.trustee_name) AS trustee_name
                FROM trustee_votes tv
                LEFT JOIN trustee_name_aliases a
                    ON LOWER(TRIM(tv.trustee_name)) = LOWER(TRIM(a.raw_name))
                WHERE COALESCE(a.normalized_name, tv.trustee_name) IS NOT NULL
                  AND TRIM(COALESCE(a.normalized_name, tv.trustee_name)) <> ''
                  AND LOWER(TRIM(COALESCE(a.normalized_name, tv.trustee_name))) <> 'all'
            )
            SELECT
                nv.vote,
                m.id AS motion_id,
                m.motion_text,
                m.result,
                (
                    SELECT
                        COUNT(tv2.id) FILTER (WHERE LOWER(TRIM(tv2.vote)) IN ('yes','aye','ayes','y')) -
                        COUNT(tv2.id) FILTER (WHERE LOWER(TRIM(tv2.vote)) IN ('no','nay','nays','n'))
                    FROM trustee_votes tv2
                    WHERE tv2.motion_id = m.id
                ) AS vote_margin,
                COALESCE(m.meeting_date, d.meeting_date) AS meeting_date,
                d.name AS document_name,
                STRING_AGG(DISTINCT mt.topic, ', ') AS topics
            FROM normalized_votes nv
            JOIN motions m ON m.id = nv.motion_id
            LEFT JOIN documents d ON d.id = m.document_id
            LEFT JOIN motion_topics mt ON mt.motion_id = m.id
            WHERE LOWER(TRIM(nv.trustee_name)) = LOWER(TRIM(%s))
            GROUP BY nv.vote, m.id, m.motion_text, m.result, m.meeting_date, d.meeting_date, d.name
            ORDER BY COALESCE(m.meeting_date, d.meeting_date) DESC NULLS LAST, m.id DESC
            LIMIT 500
        """, [trustee.get("name")])
        votes = cur.fetchall()

    total_votes = stats.get("total_votes") or 0
    body = f"""
    <div class="card">
        <p><a href="/trustees">← Back to Trustees</a></p>
        <h1>{esc(trustee.get('name'))}</h1>
        <p class="muted">Ward: {esc(trustee.get('ward') or '')} | Current: Yes</p>
    </div>

    <div class="grid">
        <div class="card"><div class="stat">{stats.get('yes_votes') or 0}</div><div>Yes</div></div>
        <div class="card"><div class="stat">{stats.get('no_votes') or 0}</div><div>No</div></div>
        <div class="card"><div class="stat">{stats.get('abstain_votes') or 0}</div><div>Abstain</div></div>
        <div class="card"><div class="stat">{stats.get('absent_votes') or 0}</div><div>Absent</div></div>
        <div class="card"><div class="stat">{total_votes}</div><div>Total Votes</div></div>
        <div class="card"><div class="stat">{esc(stats.get('majority_pct') if stats.get('majority_pct') is not None else '0.0')}%</div><div>Voting With Majority</div></div>
        <div class="card"><div class="stat">{esc(stats.get('attendance_pct') if stats.get('attendance_pct') is not None else '0.0')}%</div><div>Attendance</div></div>
    </div>

    <div class="card">
        <h2>Consensus Metrics</h2>
        <table>
            <tr><th>Yes %</th><th>No %</th><th>Abstain %</th><th>Attendance %</th><th>Voting With Majority %</th></tr>
            <tr>
                <td>{esc(stats.get('yes_pct') if stats.get('yes_pct') is not None else '0.0')}%</td>
                <td>{esc(stats.get('no_pct') if stats.get('no_pct') is not None else '0.0')}%</td>
                <td>{esc(stats.get('abstain_pct') if stats.get('abstain_pct') is not None else '0.0')}%</td>
                <td>{esc(stats.get('attendance_pct') if stats.get('attendance_pct') is not None else '0.0')}%</td>
                <td>{esc(stats.get('majority_pct') if stats.get('majority_pct') is not None else '0.0')}%</td>
            </tr>
        </table>
    </div>

    <div class="card">
        <h2>Motion History</h2>
        <table>
            <tr><th>Date</th><th>Vote</th><th>Motion</th><th>Result</th><th>Margin</th><th>Topic(s)</th><th>Document</th></tr>
    """

    for v in votes:
        body += f"""
        <tr>
            <td>{esc(fmt_date(v.get('meeting_date')))}</td>
            <td>{esc(v.get('vote'))}</td>
            <td><a href="/motions/{v['motion_id']}">{esc(clean_snippet(v.get('motion_text'), 260))}</a></td>
            <td>{esc(v.get('result'))}</td>
            <td>{esc(v.get('vote_margin'))}</td>
            <td>{esc(v.get('topics'))}</td>
            <td>{esc(v.get('document_name'))}</td>
        </tr>
        """

    if not votes:
        body += '<tr><td colspan="7" class="muted">No motion history found for this trustee.</td></tr>'

    body += """
        </table>
    </div>
    """

    return layout(trustee.get("name") or "Trustee", body)


@app.route("/failed-motions")
def failed_motions_old_url():
    return redirect(url_for("failed_motions"))


@app.route("/failed_motions")
def failed_motions():
    with get_cursor() as cur:
        cur.execute("""
            WITH vote_counts AS (
                SELECT
                    m.id AS motion_id,
                    COUNT(tv.id) FILTER (WHERE LOWER(TRIM(tv.vote)) IN ('yes','aye','ayes','y')) AS yes_votes,
                    COUNT(tv.id) FILTER (WHERE LOWER(TRIM(tv.vote)) IN ('no','nay','nays','n')) AS no_votes,
                    COUNT(tv.id) FILTER (WHERE LOWER(TRIM(tv.vote)) LIKE 'abstain%%') AS abstain_votes,
                    COUNT(tv.id) FILTER (WHERE LOWER(TRIM(tv.vote)) LIKE 'absent%%') AS absent_votes,
                    COUNT(tv.id) AS total_votes
                FROM motions m
                LEFT JOIN trustee_votes tv ON tv.motion_id = m.id
                GROUP BY m.id
            ),
            failed AS (
                SELECT
                    m.id,
                    m.motion_text,
                    m.result,
                    (COALESCE(vc.yes_votes, 0) - COALESCE(vc.no_votes, 0)) AS margin,
                    COALESCE(m.meeting_date, d.meeting_date) AS meeting_date,
                    d.name AS document_name,
                    STRING_AGG(DISTINCT mt.topic, ', ') AS topics,
                    vc.yes_votes,
                    vc.no_votes,
                    vc.abstain_votes,
                    vc.absent_votes,
                    vc.total_votes
                FROM motions m
                LEFT JOIN documents d ON d.id = m.document_id
                LEFT JOIN motion_topics mt ON mt.motion_id = m.id
                LEFT JOIN vote_counts vc ON vc.motion_id = m.id
                WHERE LOWER(COALESCE(m.result,'')) LIKE '%%fail%%'
                   OR LOWER(COALESCE(m.result,'')) LIKE '%%failed%%'
                   OR LOWER(COALESCE(m.result,'')) LIKE '%%denied%%'
                   OR LOWER(COALESCE(m.result,'')) LIKE '%%not approved%%'
                GROUP BY m.id, m.motion_text, m.result, m.meeting_date, d.meeting_date, d.name,
                         vc.yes_votes, vc.no_votes, vc.abstain_votes, vc.absent_votes, vc.total_votes
            )
            SELECT *
            FROM failed
            ORDER BY meeting_date DESC NULLS LAST, id DESC
        """)
        rows = cur.fetchall()

        cur.execute("""
            SELECT
                COUNT(*) AS total_motions,
                COUNT(*) FILTER (
                    WHERE LOWER(COALESCE(result,'')) LIKE '%%fail%%'
                       OR LOWER(COALESCE(result,'')) LIKE '%%failed%%'
                       OR LOWER(COALESCE(result,'')) LIKE '%%denied%%'
                       OR LOWER(COALESCE(result,'')) LIKE '%%not approved%%'
                ) AS failed_motions
            FROM motions
        """)
        totals = cur.fetchone()

        cur.execute("""
            WITH failed AS (
                SELECT m.id
                FROM motions m
                WHERE LOWER(COALESCE(m.result,'')) LIKE '%%fail%%'
                   OR LOWER(COALESCE(m.result,'')) LIKE '%%failed%%'
                   OR LOWER(COALESCE(m.result,'')) LIKE '%%denied%%'
                   OR LOWER(COALESCE(m.result,'')) LIKE '%%not approved%%'
            )
            SELECT mt.topic, COUNT(DISTINCT f.id) AS failed_count
            FROM failed f
            JOIN motion_topics mt ON mt.motion_id = f.id
            GROUP BY mt.topic
            ORDER BY failed_count DESC, mt.topic
            LIMIT 20
        """)
        by_topic = cur.fetchall()

        cur.execute("""
            WITH failed AS (
                SELECT m.id
                FROM motions m
                WHERE LOWER(COALESCE(m.result,'')) LIKE '%%fail%%'
                   OR LOWER(COALESCE(m.result,'')) LIKE '%%failed%%'
                   OR LOWER(COALESCE(m.result,'')) LIKE '%%denied%%'
                   OR LOWER(COALESCE(m.result,'')) LIKE '%%not approved%%'
            ),
            normalized_votes AS (
                SELECT
                    f.id AS motion_id,
                    COALESCE(a.normalized_name, tv.trustee_name) AS trustee_name,
                    LOWER(TRIM(tv.vote)) AS vote_norm
                FROM failed f
                JOIN trustee_votes tv ON tv.motion_id = f.id
                LEFT JOIN trustee_name_aliases a
                    ON LOWER(TRIM(tv.trustee_name)) = LOWER(TRIM(a.raw_name))
            )
            SELECT trustee_name, COUNT(*) AS failed_motion_votes,
                   COUNT(*) FILTER (WHERE vote_norm IN ('no','nay','nays','n')) AS no_votes_on_failed
            FROM normalized_votes
            WHERE trustee_name IS NOT NULL
              AND TRIM(trustee_name) <> ''
              AND LOWER(TRIM(trustee_name)) <> 'all'
            GROUP BY trustee_name
            ORDER BY failed_motion_votes DESC, trustee_name
            LIMIT 20
        """)
        by_trustee = cur.fetchall()

    total_motions = totals.get("total_motions") or 0
    failed_total = totals.get("failed_motions") or 0
    failure_rate = pct(failed_total, total_motions)

    closest = sorted(rows, key=lambda r: abs(int(r.get("margin") or 0)))[:5]

    body = f"""
    <div class="card">
        <h1>Failed Motion Analytics</h1>
        <p class="muted">Failed motions are based on motion.result containing fail, failed, denied, or not approved.</p>
    </div>

    <div class="grid">
        <div class="card"><div class="stat">{failed_total:,}</div><div>Total Failed Motions</div></div>
        <div class="card"><div class="stat">{failure_rate}</div><div>Failure Rate</div></div>
        <div class="card"><div class="stat">{total_motions:,}</div><div>Total Motions</div></div>
    </div>

    <div class="card">
        <h2>Closest Failed Motions</h2>
        <table><tr><th>Date</th><th>Motion</th><th>Vote</th><th>Margin</th><th>Topic</th></tr>
    """

    for r in closest:
        vote_text = f"Yes {r.get('yes_votes') or 0} / No {r.get('no_votes') or 0}"
        body += f"""
        <tr>
            <td>{esc(fmt_date(r.get('meeting_date')))}</td>
            <td><a href="/motions/{r['id']}">{esc(clean_snippet(r.get('motion_text'), 260))}</a></td>
            <td>{esc(vote_text)}</td>
            <td>{esc(r.get('margin'))}</td>
            <td>{esc(r.get('topics'))}</td>
        </tr>
        """

    if not closest:
        body += '<tr><td colspan="5" class="muted">No failed motions found.</td></tr>'

    body += "</table></div>"

    body += """
    <div class="grid">
      <div class="card">
        <h2>Failed Motions by Topic</h2>
        <table><tr><th>Topic</th><th>Failed Motions</th></tr>
    """
    for r in by_topic:
        body += f"<tr><td>{esc(r.get('topic'))}</td><td>{r.get('failed_count')}</td></tr>"
    if not by_topic:
        body += '<tr><td colspan="2" class="muted">No failed-motion topics found.</td></tr>'
    body += "</table></div>"

    body += """
      <div class="card">
        <h2>Failed Motions by Trustee</h2>
        <table><tr><th>Trustee</th><th>Failed-Motion Votes</th><th>No Votes on Failed</th></tr>
    """
    for r in by_trustee:
        body += f"<tr><td>{esc(r.get('trustee_name'))}</td><td>{r.get('failed_motion_votes')}</td><td>{r.get('no_votes_on_failed')}</td></tr>"
    if not by_trustee:
        body += '<tr><td colspan="3" class="muted">No failed-motion trustee votes found.</td></tr>'
    body += "</table></div></div>"

    body += """
    <div class="card">
        <h2>All Failed Motions</h2>
        <table>
            <tr><th>Date</th><th>Motion</th><th>Topic</th><th>Vote</th><th>Margin</th></tr>
    """

    for r in rows:
        vote_text = f"Yes {r.get('yes_votes') or 0} / No {r.get('no_votes') or 0} / Abstain {r.get('abstain_votes') or 0} / Absent {r.get('absent_votes') or 0}"
        body += f"""
        <tr>
            <td>{esc(fmt_date(r.get('meeting_date')))}</td>
            <td><a href="/motions/{r['id']}">{esc(clean_snippet(r.get('motion_text'), 300))}</a></td>
            <td>{esc(r.get('topics'))}</td>
            <td>{esc(vote_text)}</td>
            <td>{esc(r.get('margin'))}</td>
        </tr>
        """

    if not rows:
        body += '<tr><td colspan="5" class="muted">No failed motions found.</td></tr>'

    body += "</table></div>"

    return layout("Failed Motions", body)


@app.route("/topics")
def topics():
    with get_cursor() as cur:
        cur.execute("""
            SELECT
                mt.topic,
                COUNT(*) AS motion_count,
                ROUND(AVG(mt.confidence)::numeric, 4) AS avg_confidence
            FROM motion_topics mt
            JOIN motions m
                ON m.id = mt.motion_id
            GROUP BY mt.topic
            ORDER BY motion_count DESC, mt.topic;
        """)
        topic_rows = cur.fetchall()

    body = """
    <div class="card">
        <h1>Motion Topics</h1>
    </div>

    <div class="card">
        <table>
            <tr>
                <th>Topic</th>
                <th>Motion Count</th>
                <th>Avg Confidence</th>
            </tr>
    """

    for r in topic_rows:
        topic = r.get("topic")
        body += f"""
            <tr>
                <td><a href="{esc(build_url('/search', topic=topic))}">{esc(topic)}</a></td>
                <td>{r.get("motion_count")}</td>
                <td>{r.get("avg_confidence")}</td>
            </tr>
        """

    if not topic_rows:
        body += '<tr><td colspan="3" class="muted">No topics found.</td></tr>'

    body += """
        </table>
    </div>
    """

    return layout("Motion Topics", body)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=os.getenv("FLASK_DEBUG") == "1")
