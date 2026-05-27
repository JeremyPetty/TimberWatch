import os
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
    "User-Agent": "Mozilla/5.0 TimberTrack"
}


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
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

            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            cur.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")

            cur.execute("""
                CREATE INDEX IF NOT EXISTS documents_search_idx
                ON documents USING GIN(search_vector);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS documents_name_trgm_idx
                ON documents USING GIN(name gin_trgm_ops);
            """)

def clean_text_for_postgres(value):
    if value is None:
        return ""

    value = str(value)

    # PostgreSQL cannot store NUL bytes in text fields
    value = value.replace("\x00", "").replace("\u0000", "")

    # Remove other low-level control characters except normal whitespace
    value = "".join(
        ch for ch in value
        if ch == "\n" or ch == "\r" or ch == "\t" or ord(ch) >= 32
    )

    return value
    
def clean_date(value):
    if not value:
        return None
    return value.replace("T", " ").replace("Z", "")


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
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()
        files.extend(data["d"]["results"])
        url = data["d"].get("__next")

    return files


def index_source(source_name, api_url):
    print(f"Checking {source_name}...")

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
                    print(f"Skipping unchanged: {name}")
                    continue

                text_content = ""

                if name.lower().endswith(".pdf"):
                    try:
                        print(f"Indexing PDF: {name}", flush=True)
                        pdf_response = requests.get(full_url, headers=HEADERS, timeout=120)
                        pdf_response.raise_for_status()
                        text_content = clean_text_for_postgres(extract_pdf_text(pdf_response.content))
                    except Exception as e:
                        print(f"FAILED PDF: {name} | {full_url} | {e}", flush=True)
                        text_content = ""

                        source_name = clean_text_for_postgres(source_name)
                        name = clean_text_for_postgres(name)
                        full_url = clean_text_for_postgres(full_url)
                        server_url = clean_text_for_postgres(server_url)
                        text_content = clean_text_for_postgres(text_content)
                
                cur.execute("""
                    INSERT INTO documents (
                        source, name, url, server_relative_url,
                        created, modified, size, text_content,
                        indexed_at, search_vector
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s,
                        to_tsvector('english', unaccent(coalesce(%s,'') || ' ' || coalesce(%s,'')))
                    )
                    ON CONFLICT (url) DO UPDATE SET
                        source = EXCLUDED.source,
                        name = EXCLUDED.name,
                        server_relative_url = EXCLUDED.server_relative_url,
                        created = EXCLUDED.created,
                        modified = EXCLUDED.modified,
                        size = EXCLUDED.size,
                        text_content = EXCLUDED.text_content,
                        indexed_at = EXCLUDED.indexed_at,
                        search_vector = EXCLUDED.search_vector
                """, (
                    source_name, name, full_url, server_url,
                    created, modified, size, text_content,
                    datetime.utcnow(),
                    name, text_content
                ))

    print(f"Finished {source_name}")


def main():
    init_db()

    for source_name, api_url in SOURCES.items():
        index_source(source_name, api_url)

    print("Indexing complete.")


if __name__ == "__main__":
    main()
