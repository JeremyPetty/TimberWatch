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
            SELECT category, COUNT(*) AS n
            FROM ai_document_classifications
            WHERE category IS NOT NULL
            GROUP BY category
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

    where = []
    params = []

    if q:
        where.append("""(
            d.name ILIKE %s OR
            d.text_content ILIKE %s OR
            COALESCE(d.document_type, '') ILIKE %s OR
            COALESCE(d.source, '') ILIKE %s
        )""")
        like = f"%{q}%"
        params.extend([like, like, like, like])

    if category:
        where.append("c.category = %s")
        params.append(category)

    if topic:
        where.append("d.document_type = %s")
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
        SELECT
            d.id,
            d.name,
            d.url,
            d.source,
            d.document_type,
            d.created_at,
            d.modified_at,
            d.meeting_date,
            c.category,
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
        WHERE d.id IN (
            SELECT DISTINCT d2.id
            FROM documents d2
            LEFT JOIN LATERAL (
                SELECT *
                FROM ai_document_classifications c3
                WHERE c3.document_id = d2.id
                ORDER BY c3.created_at DESC NULLS LAST
                LIMIT 1
            ) c ON true
            LEFT JOIN motions m ON m.document_id = d2.id
            LEFT JOIN motion_topics mt ON mt.motion_id = m.id
            {where_sql.replace("d.", "d2.")}
        )
        ORDER BY {sort_expr} {direction_sql} NULLS LAST, d.id DESC
        LIMIT %s OFFSET %s
    """

    with get_cursor() as cur:
        cur.execute(count_sql, params)
        total = cur.fetchone()["total"]

        cur.execute(data_sql, [q, f"%{q}%", q] + params + [per_page, offset])
        rows = cur.fetchall()

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
        <input name="category" value="{esc(category)}" placeholder="Category optional">
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
          <td>{esc(r.get('document_type'))}</td>
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


@app.route("/documents/<int:document_id>")
def document_detail(document_id):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM documents WHERE id=%s", [document_id])
        doc = cur.fetchone()
        if not doc:
            return layout("Not Found", '<div class="card">Document not found.</div>'), 404
        cur.execute("SELECT * FROM ai_document_classifications WHERE document_id=%s ORDER BY created_at DESC NULLS LAST", [document_id])
        classifications = cur.fetchall()
        cur.execute("SELECT * FROM motions WHERE document_id=%s ORDER BY id", [document_id])
        motions = cur.fetchall()
    body = f"""
    <div class=\"card\">
      <h1>{esc(doc.get('name'))}</h1>
      <p class=\"muted\">
      Date: {esc(fmt_date(doc.get('meeting_date') or doc.get('created_at')))}
      | Source: {esc(doc.get('source'))}
      | Category: {esc(doc.get('document_type'))}
    </p>
      {f'<p><a class="btn" target="_blank" href="{esc(doc.get("url"))}">Open Original</a></p>' if doc.get('url') else ''}
    </div>
    <div class=\"card\"><h2>Classifications</h2>
      {' '.join(f'<span class="pill">{esc(c.get("category"))} {esc(c.get("confidence"))}</span>' for c in classifications) or '<span class="muted">No classification records.</span>'}
    </div>
    <div class=\"card\"><h2>Motions</h2>
    """
    for m in motions:
        body += f'<p><a href="/motion/{m["id"]}"><b>Motion {m["id"]}</b></a>: {esc(clean_snippet(m.get("motion_text"), 600))}</p>'
    body += "</div>"
    return layout(doc.get("name") or "Document", body)


@app.route("/motions")
def motions():
    q = request.args.get("q", "").strip()
    topic = request.args.get("topic", "").strip()
    page = to_int(request.args.get("page", 1), 1, 1)
    per_page = to_int(request.args.get("per_page", 25), 25, 1, 100)
    where = []
    params = []
    if q:
        where.append("m.motion_text ILIKE %s")
        params.append(f"%{q}%")
    if topic:
        where.append("mt.topic = %s")
        params.append(topic)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    offset = (page - 1) * per_page
    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(DISTINCT m.id) AS total FROM motions m LEFT JOIN motion_topics mt ON mt.motion_id=m.id {where_sql}", params)
        total = cur.fetchone()["total"]
        cur.execute(f"""
            SELECT DISTINCT ON (m.id) m.id, m.motion_text, m.result, m.topic, d.name AS document_name, d.meeting_date,
                   COUNT(tv.id) FILTER (WHERE LOWER(tv.vote) IN ('yes','aye','ayes')) OVER (PARTITION BY m.id) AS yes_votes,
                   COUNT(tv.id) FILTER (WHERE LOWER(tv.vote) IN ('no','nay','nays')) OVER (PARTITION BY m.id) AS no_votes
            FROM motions m
            LEFT JOIN documents d ON d.id=m.document_id
            LEFT JOIN trustee_votes tv ON tv.motion_id=m.id
            LEFT JOIN motion_topics mt ON mt.motion_id=m.id
            {where_sql}
            ORDER BY m.id DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        rows = cur.fetchall()
    total_pages = page_count(total, per_page)
    body = f"""
    <div class=\"card\"><h1>Motions</h1>
      <form><input name=\"q\" value=\"{esc(q)}\" placeholder=\"Search motion text\"><input name=\"topic\" value=\"{esc(topic)}\" placeholder=\"Topic\"><button>Search</button></form>
      <p class=\"muted\">Showing {len(rows):,} of {total:,}</p>
    </div><div class=\"card\"><table><tr><th>ID</th><th>Date</th><th>Motion</th><th>Result</th><th>Yes</th><th>No</th><th>Document</th></tr>
    """
    for r in rows:
        body += f"<tr><td><a href='/motion/{r['id']}'>{r['id']}</a></td><td>{esc(fmt_date(r.get('meeting_date')))}</td><td>{esc(clean_snippet(r.get('motion_text'), 260))}</td><td>{esc(r.get('result'))}</td><td>{r.get('yes_votes',0)}</td><td>{r.get('no_votes',0)}</td><td>{esc(r.get('document_name'))}</td></tr>"
    body += "</table>" + render_pager("/motions", page, total_pages, {"q": q, "topic": topic, "per_page": per_page}) + "</div>"
    return layout("Motions", body)


@app.route("/motion/<int:motion_id>")
def motion_detail(motion_id):
    with get_cursor() as cur:
        cur.execute("""
            SELECT
                m.*,
                d.name AS document_name,
                d.url AS document_url,
                d.source_name
            FROM motions m
            LEFT JOIN documents d ON d.id = m.document_id
            WHERE m.id = %s
        """, [motion_id])
        motion = cur.fetchone()

        if not motion:
            return layout("Motion Not Found", '<div class="card">Motion not found.</div>'), 404

        cur.execute("""
            SELECT
                tv.trustee_name,
                tv.vote
            FROM trustee_votes tv
            WHERE tv.motion_id = %s
            ORDER BY tv.trustee_name
        """, [motion_id])
        votes = cur.fetchall()

    consent_value = motion.get("consent_agenda")
    if consent_value is True:
        consent_display = "Yes"
    elif consent_value is False:
        consent_display = "No"
    else:
        consent_display = "Unknown"

    dollar_display = safe_money(motion.get("dollar_amount"))

    body = f"""
    <div class="card">
        <h1>Motion {motion['id']}</h1>
        <p class="muted">
            Date: {esc(fmt_date(motion.get('meeting_date')))}
            | Result: {esc(motion.get('result'))}
        </p>
    </div>

    <div class="card">
        <h2>Motion Text</h2>
        <p>{esc(motion.get('motion_text') or 'No motion text available.')}</p>
        <p>
            <strong>Moved By:</strong> {esc(motion.get('moved_by')) or 'Not identified'}<br>
            <strong>Seconded By:</strong> {esc(motion.get('seconded_by')) or 'Not identified'}
        </p>
    </div>

    <div class="card">
        <h2>Classification</h2>
        <p><strong>Topic:</strong> {esc(motion.get('topic_category')) or 'Unclassified'}</p>
        <p><strong>Consent Agenda:</strong> {consent_display}</p>
        <p><strong>Dollar Amount:</strong> {esc(dollar_display)}</p>
        <p><strong>Vendor / Department:</strong> {esc(motion.get('vendor_or_department')) or 'Not identified'}</p>
    </div>

    <div class="card">
        <h2>Document</h2>
        <p>
            <strong>Document:</strong> {esc(motion.get('document_name')) or 'Not linked'}<br>
            <strong>Source:</strong> {esc(motion.get('source_name')) or 'Not identified'}
        </p>
        {f'<p><a class="btn" target="_blank" href="{esc(motion.get("document_url"))}">Open Original</a></p>' if motion.get("document_url") else ''}
    </div>

    <div class="card">
        <h2>Trustee Votes</h2>
        <table>
            <tr>
                <th>Trustee</th>
                <th>Vote</th>
            </tr>
    """

    for v in votes:
        body += f"""
            <tr>
                <td>{esc(v.get('trustee_name'))}</td>
                <td>{esc(v.get('vote'))}</td>
            </tr>
        """

    if not votes:
        body += """
            <tr>
                <td colspan="2" class="muted">No trustee votes found for this motion.</td>
            </tr>
        """

    body += """
        </table>
    </div>
    """

    return layout(f"Motion {motion_id}", body)

@app.route("/motions/<int:motion_id>")
def motion_detail_redirect(motion_id):
    return redirect(url_for("motion_detail", motion_id=motion_id))


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
    }

    sort_expr = sort_map.get(sort, "trustee_name")
    dir_sql = "ASC" if direction == "asc" else "DESC"

    with get_cursor() as cur:
        cur.execute(f"""
            WITH normalized_votes AS (
                SELECT
                    tv.id,
                    tv.motion_id,
                    tv.vote,
                    COALESCE(a.normalized_name, tv.trustee_name) AS trustee_name
                FROM trustee_votes tv
                LEFT JOIN trustee_name_aliases a
                    ON LOWER(TRIM(tv.trustee_name)) = LOWER(TRIM(a.raw_name))
                WHERE COALESCE(a.normalized_name, tv.trustee_name) IS NOT NULL
                  AND COALESCE(a.normalized_name, tv.trustee_name) <> ''
                  AND COALESCE(a.normalized_name, tv.trustee_name) <> 'All'
            )
            SELECT
                t.id,
                nv.trustee_name,
                t.ward,
                t.is_current,
                COUNT(nv.id) AS total_votes,
                COUNT(nv.id) FILTER (
                    WHERE LOWER(nv.vote) IN ('yes','aye','ayes')
                ) AS yes_votes,
                COUNT(nv.id) FILTER (
                    WHERE LOWER(nv.vote) IN ('no','nay','nays')
                ) AS no_votes,
                COUNT(nv.id) FILTER (
                    WHERE LOWER(nv.vote) LIKE 'abstain%%'
                ) AS abstain_votes,
                COUNT(nv.id) FILTER (
                    WHERE LOWER(nv.vote) LIKE 'absent%%'
                ) AS absent_votes
            FROM normalized_votes nv
            JOIN trustees t
                ON LOWER(TRIM(t.name)) = LOWER(TRIM(nv.trustee_name))
            WHERE COALESCE(t.is_current, false) = true
            GROUP BY
                t.id,
                nv.trustee_name,
                t.ward,
                t.is_current
            ORDER BY {sort_expr} {dir_sql} NULLS LAST;
        """)
        rows = cur.fetchall()

    body = """
    <div class="card">
        <h1>Trustee Scorecard</h1>
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
    ]:
        body += f"<th>{sort_link('/trustees', label, key, sort, direction)}</th>"

    body += "<th>Ward</th><th>Current</th></tr>"

    for r in rows:
        trustee_display = esc(r["trustee_name"])

        trustee_cell = (
            f"<a href='/trustees/{r['id']}'>{trustee_display}</a>"
            if r["id"]
            else trustee_display
        )

        body += f"""
        <tr>
            <td>{trustee_cell}</td>
            <td>{r['yes_votes']}</td>
            <td>{r['no_votes']}</td>
            <td>{r['abstain_votes']}</td>
            <td>{r['absent_votes']}</td>
            <td>{r['total_votes']}</td>
            <td>{esc(r['ward']) if r['ward'] else ''}</td>
            <td>{"Yes" if r['is_current'] else "No"}</td>
        </tr>
        """

    body += """
        </table>
    </div>
    """

    return layout("Trustees", body)


@app.route("/trustees/<int:trustee_id>")
def trustee_detail(trustee_id):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM trustees WHERE id=%s", [trustee_id])
        t = cur.fetchone()
        if not t:
            return layout("Not Found", '<div class="card">Trustee not found.</div>'), 404
        cur.execute("""
            SELECT tv.vote, m.id AS motion_id, m.motion_text, m.result, d.meeting_date, d.name AS document_name
            FROM trustee_votes tv
            JOIN motions m ON m.id=tv.motion_id
            LEFT JOIN documents d ON d.id=m.document_id
            WHERE tv.trustee_id=%s
            ORDER BY d.meeting_date DESC NULLS LAST, m.id DESC
            LIMIT 250
        """, [trustee_id])
        votes = cur.fetchall()
        cur.execute("""
            SELECT other.id, other.name,
                   COUNT(*) FILTER (WHERE LOWER(tv1.vote)=LOWER(tv2.vote)) AS agree,
                   COUNT(*) AS together,
                   ROUND(100.0 * COUNT(*) FILTER (WHERE LOWER(tv1.vote)=LOWER(tv2.vote)) / NULLIF(COUNT(*),0), 1) AS agreement_pct
            FROM trustee_votes tv1
            JOIN trustee_votes tv2 ON tv1.motion_id=tv2.motion_id AND tv1.trustee_id<>tv2.trustee_id
            JOIN trustees other ON other.id=tv2.trustee_id
            WHERE tv1.trustee_id=%s
            GROUP BY other.id, other.name
            HAVING COUNT(*) >= 3
            ORDER BY agreement_pct DESC NULLS LAST, together DESC
        """, [trustee_id])
        alignment = cur.fetchall()
    body = f"<div class='card'><h1>{esc(t.get('name'))}</h1><p class='muted'>Ward: {esc(t.get('ward'))} | Current: {'Yes' if t.get('is_current') else 'No'}</p></div>"
    body += "<div class='card'><h2>Voting Alignment</h2><table><tr><th>Trustee</th><th>Agreement</th><th>Motions Together</th></tr>"
    for a in alignment:
        body += f"<tr><td>{esc(a['name'])}</td><td>{esc(a['agreement_pct'])}%</td><td>{a['together']}</td></tr>"
    body += "</table></div>"
    body += "<div class='card'><h2>Recent Votes</h2><table><tr><th>Date</th><th>Vote</th><th>Motion</th><th>Result</th></tr>"
    for v in votes:
        body += f"<tr><td>{esc(fmt_date(v.get('meeting_date')))}</td><td>{esc(v.get('vote'))}</td><td><a href='/motion/{v['motion_id']}'>{esc(clean_snippet(v.get('motion_text'), 220))}</a></td><td>{esc(v.get('result'))}</td></tr>"
    body += "</table></div>"
    return layout(t.get("name") or "Trustee", body)


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

@app.route("/failed-motions")
def failed_motions():
    with get_cursor() as cur:
        cur.execute("""
            SELECT m.id, m.motion_text, m.result, d.name AS document_name, d.meeting_date,
                   STRING_AGG(DISTINCT mt.topic, ', ') AS topics,
                   COUNT(tv.id) FILTER (WHERE LOWER(tv.vote) IN ('no','nay','nays')) AS no_votes
            FROM motions m
            LEFT JOIN documents d ON d.id=m.document_id
            LEFT JOIN trustee_votes tv ON tv.motion_id=m.id
            LEFT JOIN motion_topics mt ON mt.motion_id=m.id
            WHERE LOWER(COALESCE(m.result,'')) LIKE '%%fail%%'
               OR LOWER(COALESCE(m.result,'')) LIKE '%%denied%%'
               OR LOWER(COALESCE(m.result,'')) LIKE '%%not approved%%'
            GROUP BY m.id, m.motion_text, m.result, d.name, d.meeting_date
            ORDER BY d.meeting_date DESC NULLS LAST, m.id DESC
        """)
        rows = cur.fetchall()
    body = "<div class='card'><h1>Rare Failed Motions</h1><p class='muted'>Useful for spotting topics that break consensus.</p></div><div class='card'><table><tr><th>Date</th><th>Motion</th><th>Result</th><th>No Votes</th><th>Topics</th><th>Document</th></tr>"
    for r in rows:
        body += f"<tr><td>{esc(fmt_date(r.get('meeting_date')))}</td><td><a href='/motion/{r['id']}'>{esc(clean_snippet(r.get('motion_text'), 300))}</a></td><td>{esc(r.get('result'))}</td><td>{r.get('no_votes')}</td><td>{esc(r.get('topics'))}</td><td>{esc(r.get('document_name'))}</td></tr>"
    body += "</table></div>"
    return layout("Failed Motions", body)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=os.getenv("FLASK_DEBUG") == "1")
