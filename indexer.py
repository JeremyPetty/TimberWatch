"""Index public board documents into the documents table.

Usage examples:
  python indexer.py --source-name "COS BoardDocs" --url "https://example.com/board" --limit 100
  python indexer.py --csv documents.csv --source-name "Manual Import"

CSV columns supported: name,url,text_content,source_name,meeting_date,file_type
"""
import argparse
import csv
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from db import get_cursor

PDF_RE = re.compile(r"\.pdf($|\?)", re.I)
DATE_RE = re.compile(r"(20\d{2}|19\d{2})[-_/\.](\d{1,2})[-_/\.](\d{1,2})|(\d{1,2})[-_/\.](\d{1,2})[-_/\.](20\d{2}|19\d{2})")


def parse_date_from_text(text):
    if not text:
        return None
    match = DATE_RE.search(text)
    if not match:
        return None
    groups = match.groups()
    try:
        if groups[0]:
            return datetime(int(groups[0]), int(groups[1]), int(groups[2])).date()
        return datetime(int(groups[5]), int(groups[3]), int(groups[4])).date()
    except Exception:
        return None


def upsert_document(name, url, source_name=None, text_content=None, meeting_date=None, file_type=None):
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO documents(name, url, source_name, text_content, meeting_date, file_type, created_at, modified_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (url) DO UPDATE SET
                name=EXCLUDED.name,
                source_name=COALESCE(EXCLUDED.source_name, documents.source_name),
                text_content=COALESCE(NULLIF(EXCLUDED.text_content,''), documents.text_content),
                meeting_date=COALESCE(EXCLUDED.meeting_date, documents.meeting_date),
                file_type=COALESCE(EXCLUDED.file_type, documents.file_type),
                modified_at=CURRENT_TIMESTAMP
            RETURNING id
        """, [name, url, source_name, text_content, meeting_date, file_type])
        return cur.fetchone()["id"]


def index_url(source_name, page_url, limit=100):
    resp = requests.get(page_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    count = 0
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not PDF_RE.search(href):
            continue
        url = urljoin(page_url, href)
        name = " ".join(a.get_text(" ", strip=True).split()) or url.rsplit("/", 1)[-1]
        meeting_date = parse_date_from_text(name) or parse_date_from_text(url)
        doc_id = upsert_document(name=name, url=url, source_name=source_name, meeting_date=meeting_date, file_type="pdf")
        print(f"Indexed {doc_id}: {name}")
        count += 1
        if limit and count >= limit:
            break
    print(f"Indexed {count} documents.")


def index_csv(csv_path, default_source=None, limit=None):
    count = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name") or row.get("title") or row.get("filename")
            url = row.get("url") or row.get("link")
            if not name or not url:
                continue
            meeting_date = row.get("meeting_date") or parse_date_from_text(name)
            doc_id = upsert_document(
                name=name,
                url=url,
                source_name=row.get("source_name") or default_source,
                text_content=row.get("text_content"),
                meeting_date=meeting_date or None,
                file_type=row.get("file_type") or "pdf",
            )
            print(f"Indexed {doc_id}: {name}")
            count += 1
            if limit and count >= limit:
                break
    print(f"Indexed {count} CSV rows.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-name", default="Board Documents")
    parser.add_argument("--url")
    parser.add_argument("--csv")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.csv:
        index_csv(args.csv, args.source_name, args.limit)
    elif args.url:
        index_url(args.source_name, args.url, args.limit)
    else:
        raise SystemExit("Provide --url or --csv")
