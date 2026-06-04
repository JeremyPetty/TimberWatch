"""Classify documents with OpenAI and save into ai_document_classifications.

Run from Render cron or locally:
  python ai_classifier.py --limit 25
"""
import argparse
import json
import os

from openai import OpenAI
from db import get_cursor
from utils import clean_snippet

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
CATEGORIES = [
    "Board Policy", "Budget", "Facilities", "Personnel", "Labor Relations", "Student Services",
    "Academic Affairs", "Consent", "Information", "Governance", "Construction", "Contracts",
    "Audit", "Technology", "Other"
]


def get_client():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Missing OPENAI_API_KEY environment variable.")
    return OpenAI()


def classify_text(client, name, text):
    prompt = f"""
Classify this board document for a civic transparency database.
Return ONLY valid JSON with keys:
category, confidence, vote_result, summary, topics.
category must be one of: {', '.join(CATEGORIES)}.
vote_result should be Passed, Failed, Information Only, Unknown, or null.
topics should be a short array of 1-5 topic strings.

Document name: {name}
Text excerpt: {clean_snippet(text or '', 5000)}
"""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


def mark_status(document_id, ai_processed, error=None):
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO motion_processing_status(document_id, ai_processed, last_ai_error, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (document_id) DO UPDATE SET
                ai_processed=EXCLUDED.ai_processed,
                last_ai_error=EXCLUDED.last_ai_error,
                updated_at=CURRENT_TIMESTAMP
        """, [document_id, ai_processed, error])


def main(limit):
    client = get_client()
    with get_cursor() as cur:
        cur.execute("""
            SELECT d.id, d.name, d.text_content
            FROM documents d
            LEFT JOIN motion_processing_status s ON s.document_id=d.id
            WHERE COALESCE(s.ai_processed,false)=false
              AND COALESCE(d.text_content,'') <> ''
            ORDER BY d.id
            LIMIT %s
        """, [limit])
        docs = cur.fetchall()
    for d in docs:
        print(f"Classifying document {d['id']}: {d['name']}")
        try:
            result = classify_text(client, d["name"], d["text_content"])
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO ai_document_classifications(document_id, model, category, confidence, vote_result, summary, raw_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                    ON CONFLICT (document_id, model) DO UPDATE SET
                        category=EXCLUDED.category,
                        confidence=EXCLUDED.confidence,
                        vote_result=EXCLUDED.vote_result,
                        summary=EXCLUDED.summary,
                        raw_json=EXCLUDED.raw_json,
                        created_at=CURRENT_TIMESTAMP
                """, [d["id"], MODEL, result.get("category"), result.get("confidence"), result.get("vote_result"), result.get("summary"), json.dumps(result)])
            mark_status(d["id"], True)
        except Exception as exc:
            mark_status(d["id"], False, str(exc))
            print(f"ERROR document {d['id']}: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    main(args.limit)
