import os
import re
import requests
import fitz
import psycopg2

from urllib.parse import quote
from datetime import datetime


DATABASE_URL = os.environ["DATABASE_URL"]
SITE_ROOT = "https://www.cos.edu"

SOURCES = {
    "Board Documents": (
        "https://www.cos.edu/en-us/Governance/Board/_api/web/"
        "GetFolderByServerRelativeUrl('/en-us/Governance/Board/Documents')/Files"
        "?$select=Name,ServerRelativeUrl,TimeCreated,TimeLastModified,Length"
        "&$top=5000&$format=json"
    ),
    "BP/AP/AR": (
        "https://www.cos.edu/en-us/Governance/Board/BoardPolicies/_api/web/"
        "GetFolderByServerRelativeUrl('/en-us/Governance/Board/BoardPolicies/Documents')/Files"
        "?$select=Name,ServerRelativeUrl,TimeCreated,TimeLastModified,Length"
        "&$top=5000&$format=json"
    ),
}

HEADERS = {
    "Accept": "application/json;odata=verbose",
    "User-Agent": "Mozilla/5.0 TimberWatch"
}


TOPIC_KEYWORDS = {
    "Budget / Finance": ["budget", "audit", "financial", "expenditure", "warrant", "fund", "fiscal"],
    "Facilities": ["construction", "facility", "building", "campus", "bond"],
    "Personnel": ["employment", "appointment", "salary", "resignation", "hiring"],
    "Policy": ["board policy", "administrative procedure", "bp ", "ap "],
    "Curriculum": ["curriculum", "course", "program"],
    "Governance": ["trustee", "agenda", "election", "governance", "board"],
    "Closed Session": ["closed session", "litigation", "labor negotiations"],
}


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def clean_text_for_postgres(value):
    if value is None:
        return ""

    value = str(value)
    value = value.replace("\x00", "").replace("\u0000", "")

    return "".join(
        ch for ch in value
        if ch in ("\n", "\r", "\t") or ord(ch) >= 32
    )


def clean_date(value):
    if not value:
        return None

    return value.replace("T", " ").replace("Z", "")


def classify_topic(text):
    text_lower = (text or "").lower()

    for topic, keywords in TOPIC_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return topic

    return "General"


def extract_meeting_date(text):
    patterns = [
        r"([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text or "")

        if match:
            raw_date = match.group(1)

            for fmt in ("%B %d, %Y", "%m/%d/%Y"):
                try:
                    return datetime.strptime(raw_date, fmt).date()
                except ValueError:
                    pass

    return None


def classify_document_type(name, text):
    combined = f"{name} {text}".lower()

    if "minutes" in combined:
        return "Minutes"

    if "agenda" in combined:
        return "Agenda"

    if "board policy" in combined or "bp " in combined:
        return "Board Policy"

    if "administrative procedure" in combined or "ap " in combined:
        return "Administrative Procedure"

    return "Other"


def extract_motions(text):
    motions = []

    if not text:
        return motions

    motion_patterns = [
        r"Motion.*?(approved|passed|failed|carried|defeated)",
        r"Moved by.*?(approved|passed|failed|carried|defeated)",
        r"AYES:.*?(NOES:.*?)(?=Motion|Moved by|AYES:|$)",
    ]

    seen = set()

    for pattern in motion_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)

        for match in matches:
            motion_text = clean_text_for_postgres(match.group(0).strip())

            if not motion_text:
                continue

            motion_key = motion_text[:500]

            if motion_key in seen:
                continue

            seen.add(motion_key)

            motion_lower = motion_text.lower()
            vote_result = "Passed"

            if "failed" in motion_lower or "defeated" in motion_lower:
                vote_result = "Failed"

            motions.append({
                "motion_text": motion_text[:4000],
                "vote_result": vote_result,
                "topic": classify_topic(motion_text),
            })

    return motions


def extract_trustee_votes(motion_text):
    votes = []

    if not motion_text:
        return votes

    vote_sections = {
        "Yes": ["AYES", "AYE", "YES"],
        "No": ["NOES", "NO", "NAY", "NAYS"],
        "Abstain": ["ABSTAIN", "ABSTENTIONS", "ABSTENTIONS"],
        "Absent": ["ABSENT"],
    }

    section_labels = (
        "AYES|AYE|YES|NOES|NO|NAY|NAYS|ABSTAIN|ABSTENTIONS|ABSENT"
    )

    for vote_type, labels in vote_sections.items():
        for label in labels:
            pattern = rf"{label}\s*:\s*(.*?)(?={section_labels}|$)"
            match = re.search(pattern, motion_text, re.IGNORECASE | re.DOTALL)

            if not match:
                continue

            names_text = match.group(1)
            names_text = names_text.replace("\n", " ")
            names_text = re.sub(r"\s+", " ", names_text)

            names = re.split(r",|;|\band\b", names_text)

            for name in names:
                cleaned = name.strip(" .:-")

                if len(cleaned) < 3:
                    continue

                if len(cleaned.split()) > 6:
                    continue

                votes.append({
                    "trustee_name": cleaned[:200],
                    "vote": vote_type,
                })

    return votes


def extract_pdf_text(pdf_bytes):
    text_parts = []

    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        for page_num, page in enumerate(pdf, start=1):
            text = page.get_text("text")

            if text.strip():
                text_parts.append(f"\n--- Page {page_num} ---\n{text}")

    return "\n".join(text_parts).strip()


def fetch_files(api_url):
    files = []
    url = api_url

    while url:
        response = requests.get(url, headers=HEADERS, timeout=60)
        response.raise_for_status()

        data = response.json()
        files.extend(data["d"]["results"])
        url = data["d"].get("__next")

    return files


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            cur.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id SERIAL PRIMARY KEY,
                    source TEXT,
                    name TEXT,
                    url TEXT UNIQUE,
                    server_relative_url TEXT,
                    created TIMESTAMP NULL,
                    modified TIMESTAMP NULL,
                    size BIGINT,
                    text_content TEXT,
                    indexed_at TIMESTAMP,
                    search_vector tsvector
                );
            """)

            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS meeting_date DATE;")
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_type TEXT;")
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url TEXT;")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS trustees (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    ward TEXT,
                    is_current BOOLEAN DEFAULT TRUE,
                    first_seen DATE,
                    last_seen DATE
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS agenda_items (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
                    meeting_date DATE,
                    item_text TEXT,
                    topic TEXT
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS motions (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
                    meeting_date DATE,
                    agenda_item_id INTEGER REFERENCES agenda_items(id) ON DELETE SET NULL,
                    motion_text TEXT,
                    moved_by TEXT,
                    seconded_by TEXT,
                    vote_result TEXT,
                    topic TEXT
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS trustee_votes (
                    id SERIAL PRIMARY KEY,
                    motion_id INTEGER REFERENCES motions(id) ON DELETE CASCADE,
                    trustee_name TEXT,
                    vote TEXT
                );
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS documents_search_idx
                ON documents USING GIN(search_vector);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS documents_name_trgm_idx
                ON documents USING GIN(name gin_trgm_ops);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_documents_meeting_date
                ON documents(meeting_date);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_motions_document_id
                ON motions(document_id);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_motions_topic
                ON motions(topic);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_votes_motion_id
                ON trustee_votes(motion_id);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_votes_trustee
                ON trustee_votes(trustee_name);
            """)


def index_source(source_name, api_url):
    print(f"Checking {source_name}...", flush=True)

    files = fetch_files(api_url)

    with get_conn() as conn:
        with conn.cursor() as cur:
            for item in files:
                name = item.get("Name", "")
                server_url = item.get("ServerRelativeUrl", "")
                full_url = SITE_ROOT + quote(server_url, safe="/:-_.()'")
                created = clean_date(item.get("TimeCreated", ""))
                modified = clean_date(item.get("TimeLastModified", ""))
                size = int(item.get("Length", 0))

                cur.execute("""
                    SELECT modified, size
                    FROM documents
                    WHERE url = %s
                """, (full_url,))

                existing = cur.fetchone()

                if existing and str(existing[0]) == str(modified) and existing[1] == size:
                    print(f"Skipping unchanged: {name}", flush=True)
                    continue

                text_content = ""

                if name.lower().endswith(".pdf"):
                    try:
                        print(f"Indexing PDF: {name}", flush=True)

                        pdf_response = requests.get(
                            full_url,
                            headers=HEADERS,
                            timeout=120
                        )

                        pdf_response.raise_for_status()
                        text_content = extract_pdf_text(pdf_response.content)

                    except Exception as e:
                        print(
                            f"FAILED PDF: {name} | {full_url} | {e}",
                            flush=True
                        )
                        text_content = ""

                source_clean = clean_text_for_postgres(source_name)
                name_clean = clean_text_for_postgres(name)
                full_url_clean = clean_text_for_postgres(full_url)
                server_url_clean = clean_text_for_postgres(server_url)
                text_content_clean = clean_text_for_postgres(text_content)

                meeting_date = extract_meeting_date(text_content_clean)
                document_type = classify_document_type(name_clean, text_content_clean)
                source_url = full_url_clean

                cur.execute("""
                    INSERT INTO documents (
                        source,
                        name,
                        url,
                        server_relative_url,
                        created,
                        modified,
                        size,
                        text_content,
                        indexed_at,
                        search_vector,
                        meeting_date,
                        document_type,
                        source_url
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        to_tsvector(
                            'english',
                            unaccent(
                                coalesce(%s,'') || ' ' ||
                                coalesce(%s,'')
                            )
                        ),
                        %s,
                        %s,
                        %s
                    )
                    ON CONFLICT (url)
                    DO UPDATE SET
                        source = EXCLUDED.source,
                        name = EXCLUDED.name,
                        server_relative_url = EXCLUDED.server_relative_url,
                        created = EXCLUDED.created,
                        modified = EXCLUDED.modified,
                        size = EXCLUDED.size,
                        text_content = EXCLUDED.text_content,
                        indexed_at = EXCLUDED.indexed_at,
                        search_vector = EXCLUDED.search_vector,
                        meeting_date = EXCLUDED.meeting_date,
                        document_type = EXCLUDED.document_type,
                        source_url = EXCLUDED.source_url
                    RETURNING id
                """, (
                    source_clean,
                    name_clean,
                    full_url_clean,
                    server_url_clean,
                    created,
                    modified,
                    size,
                    text_content_clean,
                    datetime.utcnow(),
                    name_clean,
                    text_content_clean,
                    meeting_date,
                    document_type,
                    source_url,
                ))

                document_id_row = cur.fetchone()

                if not document_id_row:
                    print(
                        f"WARNING: No document id returned for {name_clean}",
                        flush=True
                    )
                    continue

                document_id = document_id_row[0]

                cur.execute("""
                    DELETE FROM motions
                    WHERE document_id = %s
                """, (document_id,))

                motions = extract_motions(text_content_clean)

                for motion in motions:
                    cur.execute("""
                        INSERT INTO motions (
                            document_id,
                            meeting_date,
                            motion_text,
                            vote_result,
                            topic
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        document_id,
                        meeting_date,
                        motion["motion_text"],
                        motion["vote_result"],
                        motion["topic"],
                    ))

                    motion_id = cur.fetchone()[0]

                    trustee_votes = extract_trustee_votes(motion["motion_text"])

                    for vote in trustee_votes:
                        trustee_name = clean_text_for_postgres(vote["trustee_name"])
                        vote_value = clean_text_for_postgres(vote["vote"])

                        cur.execute("""
                            INSERT INTO trustees (
                                name,
                                first_seen,
                                last_seen
                            )
                            VALUES (%s, %s, %s)
                            ON CONFLICT (name)
                            DO UPDATE SET
                                last_seen = EXCLUDED.last_seen,
                                is_current = TRUE
                        """, (
                            trustee_name,
                            meeting_date,
                            meeting_date,
                        ))

                        cur.execute("""
                            INSERT INTO trustee_votes (
                                motion_id,
                                trustee_name,
                                vote
                            )
                            VALUES (%s, %s, %s)
                        """, (
                            motion_id,
                            trustee_name,
                            vote_value,
                        ))

    print(f"Finished {source_name}", flush=True)


def main():
    init_db()

    for source_name, api_url in SOURCES.items():
        index_source(source_name, api_url)

    print("Indexing complete.", flush=True)


if __name__ == "__main__":
    main()
