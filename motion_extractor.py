"""Extract motions, topics, sponsors, and trustee votes from document text.

Run:
  python motion_extractor.py --limit 25

This script intentionally stores agenda_item_id as NULL unless you later add reliable agenda-item matching.
That avoids foreign-key failures when an AI guesses agenda item numbers.
"""
import argparse
import json
import os
import re

from openai import OpenAI

from db import get_cursor
from utils import clean_snippet

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

FALLBACK_TOPICS = [
    "Budget", "Facilities", "Personnel", "Labor Relations", "Board Policy", "Student Services",
    "Construction", "Contracts", "Governance", "Academic Affairs", "Technology"
]


def get_client():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Missing OPENAI_API_KEY environment variable.")
    return OpenAI()


def normalize_vote(vote):
    if not vote:
        return "Unknown"
    v = str(vote).strip().lower()
    if v in ("aye", "ayes", "yes", "y"):
        return "Yes"
    if v in ("nay", "nays", "no", "n"):
        return "No"
    if "abstain" in v:
        return "Abstain"
    if "absent" in v:
        return "Absent"
    return vote.strip().title()


def find_trustee_id(name):
    if not name:
        return None
    with get_cursor() as cur:
        cur.execute("SELECT id FROM trustees WHERE LOWER(name)=LOWER(%s)", [name])
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute("SELECT trustee_id AS id FROM trustee_aliases WHERE LOWER(alias)=LOWER(%s)", [name])
        row = cur.fetchone()
        return row["id"] if row else None


def extract_with_ai(client, name, text):
    prompt = f"""
Extract board meeting motions and trustee votes from this document.
Return ONLY valid JSON in this structure:
{{
  "motions": [
    {{
      "motion_text": "exact or summarized motion text",
      "result": "Passed|Failed|Approved|Denied|Information Only|Unknown",
      "topics": [{{"topic":"Budget", "confidence":0.90}}],
      "sponsors": ["Trustee Name"],
      "votes": [{{"trustee":"Trustee Name", "vote":"Yes|No|Abstain|Absent|Unknown"}}]
    }}
  ]
}}
Do not invent trustees. If the document does not contain motions, return an empty motions array.
Use these broad topic examples when applicable: {', '.join(FALLBACK_TOPICS)}.

Document: {name}
Text excerpt:
{clean_snippet(text or '', 12000)}
"""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


def insert_motion(document_id, motion):
    motion_text = clean_snippet(motion.get("motion_text") or "", 4000)
    if not motion_text:
        return None
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO motions(document_id, agenda_item_id, motion_text, result, topic, created_at)
            VALUES (%s, NULL, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
        """, [document_id, motion_text, motion.get("result"), (motion.get("topics") or [{}])[0].get("topic") if motion.get("topics") else None])
        motion_id = cur.fetchone()["id"]

    for topic in motion.get("topics") or []:
        topic_name = topic.get("topic") if isinstance(topic, dict) else str(topic)
        confidence = topic.get("confidence") if isinstance(topic, dict) else None
        if topic_name:
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO motion_topics(motion_id, topic, confidence)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (motion_id, topic) DO UPDATE SET confidence=EXCLUDED.confidence
                """, [motion_id, topic_name, confidence])

    for sponsor in motion.get("sponsors") or []:
        trustee_id = find_trustee_id(sponsor)
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO motion_sponsors(motion_id, trustee_id, sponsor_name)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """, [motion_id, trustee_id, sponsor])

    for vote in motion.get("votes") or []:
        trustee_name = vote.get("trustee")
        trustee_id = find_trustee_id(trustee_name)
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO trustee_votes(motion_id, trustee_id, trustee_name_text, vote, created_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, [motion_id, trustee_id, trustee_name, normalize_vote(vote.get("vote"))])

    return motion_id


def mark_status(document_id, processed, error=None):
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO motion_processing_status(document_id, motion_processed, last_motion_error, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (document_id) DO UPDATE SET
                motion_processed=EXCLUDED.motion_processed,
                last_motion_error=EXCLUDED.last_motion_error,
                updated_at=CURRENT_TIMESTAMP
        """, [document_id, processed, error])


def main(limit):
    client = get_client()
    with get_cursor() as cur:
        cur.execute("""
            SELECT d.id, d.name, d.text_content
            FROM documents d
            LEFT JOIN motion_processing_status s ON s.document_id=d.id
            WHERE COALESCE(s.motion_processed,false)=false
              AND COALESCE(d.text_content,'') <> ''
            ORDER BY d.id
            LIMIT %s
        """, [limit])
        docs = cur.fetchall()

    for d in docs:
        print(f"Processing document {d['id']}: {d['name']}")
        try:
            payload = extract_with_ai(client, d["name"], d["text_content"])
            count = 0
            for motion in payload.get("motions", []):
                if insert_motion(d["id"], motion):
                    count += 1
            mark_status(d["id"], True)
            print(f"Inserted {count} motions.")
        except Exception as exc:
            mark_status(d["id"], False, str(exc))
            print(f"ERROR processing document {d['id']}: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    main(args.limit)
