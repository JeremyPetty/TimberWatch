import os
import json
import argparse
import psycopg2
from openai import OpenAI

DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL environment variable.")

if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

client = OpenAI(api_key=OPENAI_API_KEY)


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def fetch_motions(conn, limit):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                m.id,
                m.motion_text,
                COALESCE(d.name, d.url, '') AS document_title,
                COALESCE(d.text_content, '') AS document_text
            FROM motions m
            JOIN documents d
                ON d.id = m.document_id
            WHERE m.result IS NULL
               OR m.result = ''
               OR m.result = 'Unknown'
            ORDER BY m.id
            LIMIT %s;
            """,
            (limit,)
        )
        return cur.fetchall()


def trim_context(document_text, motion_text, max_chars=10000):
    if not document_text:
        return ""

    if motion_text and motion_text in document_text:
        idx = document_text.find(motion_text)
        start = max(0, idx - 3000)
        end = min(len(document_text), idx + len(motion_text) + 7000)
        return document_text[start:end]

    return document_text[:max_chars]


def normalize_result(result):
    if not result:
        return "Unknown"

    result = result.strip().lower()

    if result in ["passed", "pass", "carried", "approved", "adopted", "motion carried", "motion passed"]:
        return "Passed"

    if result in ["failed", "fail", "denied", "not approved", "motion failed", "did not pass"]:
        return "Failed"

    if result in ["tabled", "postponed"]:
        return "Tabled"

    if result in ["withdrawn"]:
        return "Withdrawn"

    if result in ["deferred"]:
        return "Deferred"

    if result in ["no action", "no vote", "information only"]:
        return "No Action"

    return "Unknown"


def extract_result_with_ai(motion_id, motion_text, document_title, context):
    prompt = f"""
You are extracting the final result of a board motion from public board minutes.

Return ONLY valid JSON.

Motion ID:
{motion_id}

Document title:
{document_title}

Motion text:
{motion_text}

Nearby document context:
{context}

Task:
Determine the final result of this motion.

Use only one of these result values:
Passed
Failed
Tabled
Withdrawn
Deferred
No Action
Unknown

Rules:
- If the motion carried, was approved, passed, or adopted, use Passed.
- If the motion failed, was denied, or did not pass, use Failed.
- If it was only an information item with no vote, use No Action.
- If the context does not clearly say what happened, use Unknown.
- Do not guess.

Return JSON exactly like this:
{{
  "result": "Passed",
  "confidence": 0.95,
  "source_text": "short supporting excerpt"
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "You extract structured board motion results. Return only valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    raw = response.choices[0].message.content.strip()

    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()

    return json.loads(raw)


def save_result(conn, motion_id, result_data):
    result = normalize_result(result_data.get("result"))
    confidence = result_data.get("confidence")
    source_text = result_data.get("source_text", "")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE motions
            SET result = %s
            WHERE id = %s;
            """,
            (result, motion_id)
        )

    conn.commit()

    return result, confidence, source_text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    conn = get_connection()

    try:
        motions = fetch_motions(conn, args.limit)

        print(f"Found {len(motions)} motions needing result backfill.")

        for motion_id, motion_text, document_title, document_text in motions:
            print(f"\nProcessing motion {motion_id}: {document_title}")

            context = trim_context(document_text, motion_text)

            if not context:
                print("No document context found. Marking Unknown.")

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE motions
                        SET result = 'Unknown'
                        WHERE id = %s;
                        """,
                        (motion_id,)
                    )
                conn.commit()
                continue

            try:
                result_data = extract_result_with_ai(
                    motion_id=motion_id,
                    motion_text=motion_text or "",
                    document_title=document_title or "",
                    context=context
                )

                result, confidence, source_text = save_result(conn, motion_id, result_data)

                print(f"Result: {result} | Confidence: {confidence}")
                print(f"Source: {source_text[:250]}")

            except Exception as e:
                conn.rollback()
                print(f"ERROR processing motion {motion_id}: {e}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
