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


VALID_VOTES = {
    "Yes",
    "No",
    "Abstain",
    "Absent",
    "Recused",
    "Unknown"
}


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def fetch_motions(conn, limit):
    """
    Pull motions that still need result backfill.
    This avoids reprocessing motions that already have Passed/Failed/etc.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                m.id,
                m.motion_text,
                m.document_id,
                COALESCE(d.name, d.url, '') AS document_title,
                COALESCE(d.text_content, '') AS document_text
            FROM motions m
            JOIN documents d
                ON d.id = m.document_id
            WHERE
                m.result IS NULL
                OR m.result = ''
                OR m.result = 'Unknown'
            ORDER BY m.id
            LIMIT %s;
            """,
            (limit,)
        )
        return cur.fetchall()


def trim_context(document_text, motion_text, max_chars=12000):
    """
    Try to give the AI nearby context around the motion.
    If the exact motion text is found, center around it.
    Otherwise send the beginning of the document text.
    """
    if not document_text:
        return ""

    if motion_text and motion_text in document_text:
        idx = document_text.find(motion_text)
        start = max(0, idx - 4000)
        end = min(len(document_text), idx + len(motion_text) + 8000)
        return document_text[start:end]

    return document_text[:max_chars]


def extract_votes_with_ai(motion_id, motion_text, document_title, context):
    prompt = f"""
You are extracting board trustee votes from public board minutes.

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
Identify individual trustee votes for this motion if available.

Rules:
- Only include named trustees if the document clearly gives their vote or status.
- Do not invent names.
- If the minutes say "motion carried unanimously" but do not list individual names, return an empty votes array.
- If the minutes list trustees present and clearly state unanimous approval, you may mark present trustees as Yes only if the context clearly supports that.
- Normalize votes to one of:
  Yes, No, Abstain, Absent, Recused, Unknown
- Also identify motion_result if clearly stated:
  Passed, Failed, Tabled, Withdrawn, Deferred, No Action, Unknown
- Include a short source_text excerpt supporting the extraction.

Return JSON in this exact structure:
{{
  "motion_result": "Passed",
  "votes": [
    {{
      "trustee_name": "Jane Doe",
      "vote": "Yes",
      "confidence": 0.95,
      "source_text": "short supporting excerpt"
    }}
  ]
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "You extract structured vote data from board minutes. Return only valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    raw = response.choices[0].message.content.strip()

    # Remove accidental markdown fences if returned.
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()

    return json.loads(raw)


def normalize_vote(vote):
    if not vote:
        return "Unknown"

    vote_clean = vote.strip().title()

    mappings = {
        "Aye": "Yes",
        "Yea": "Yes",
        "Yes": "Yes",
        "No": "No",
        "Nay": "No",
        "Abstained": "Abstain",
        "Abstain": "Abstain",
        "Absent": "Absent",
        "Recuse": "Recused",
        "Recused": "Recused",
        "Unknown": "Unknown"
    }

    return mappings.get(vote_clean, "Unknown")


def normalize_result(result):
    if not result:
        return "Unknown"

    result_clean = result.strip().title()

    mappings = {
        "Pass": "Passed",
        "Passed": "Passed",
        "Carried": "Passed",
        "Approved": "Passed",
        "Adopted": "Passed",
        "Failed": "Failed",
        "Fail": "Failed",
        "Denied": "Failed",
        "Tabled": "Tabled",
        "Withdrawn": "Withdrawn",
        "Deferred": "Deferred",
        "No Action": "No Action",
        "Unknown": "Unknown"
    }

    return mappings.get(result_clean, "Unknown")


def save_vote_data(conn, motion_id, data):
    motion_result = normalize_result(data.get("motion_result"))

    votes = data.get("votes", [])
    if not isinstance(votes, list):
        votes = []

    with conn.cursor() as cur:
        # Update motion result if the column exists.
        # If your motions table does not have result yet, add it:
        # ALTER TABLE motions ADD COLUMN IF NOT EXISTS result TEXT;
        if motion_result != "Unknown":
            cur.execute(
                """
                UPDATE motions
                SET result = %s
                WHERE id = %s
                  AND (result IS NULL OR result = '' OR result = 'Unknown');
                """,
                (motion_result, motion_id)
            )

        for item in votes:
            trustee_name = item.get("trustee_name")
            vote = normalize_vote(item.get("vote"))
            confidence = item.get("confidence", 0)
            source_text = item.get("source_text", "")

            if not trustee_name:
                continue

            if vote not in VALID_VOTES:
                vote = "Unknown"

            cur.execute(
                """
                INSERT INTO votes (
                    motion_id,
                    trustee_name,
                    vote,
                    confidence,
                    source_text
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (motion_id, trustee_name)
                DO UPDATE SET
                    vote = EXCLUDED.vote,
                    confidence = EXCLUDED.confidence,
                    source_text = EXCLUDED.source_text;
                """,
                (
                    motion_id,
                    trustee_name.strip(),
                    vote,
                    confidence,
                    source_text[:1000]
                )
            )

    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    conn = get_connection()

    try:
        motions = fetch_motions(conn, args.limit)

        print(f"Found {len(motions)} motions needing vote backfill.")

        for motion_id, motion_text, document_id, document_title, document_text in motions:
            print(f"\nProcessing motion {motion_id}: {document_title}")

            context = trim_context(document_text, motion_text)

            if not context:
                print("No document context found. Skipping.")
                continue

            try:
                data = extract_votes_with_ai(
                    motion_id=motion_id,
                    motion_text=motion_text or "",
                    document_title=document_title or "",
                    context=context
                )

                save_vote_data(conn, motion_id, data)

                vote_count = len(data.get("votes", []))
                result = data.get("motion_result", "Unknown")

                print(f"Inserted/updated {vote_count} vote rows. Result: {result}")

            except Exception as e:
                conn.rollback()
                print(f"ERROR processing motion {motion_id}: {e}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
