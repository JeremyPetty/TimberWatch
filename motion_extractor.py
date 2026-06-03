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


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def ensure_motion_tracking_columns(cur):
    cur.execute("""
        ALTER TABLE documents
        ADD COLUMN IF NOT EXISTS motion_processed BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS motion_processed_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS motion_process_notes TEXT;
    """)


def fetch_documents(cur, limit):
    cur.execute("""
        SELECT id, name, text_content, meeting_date, document_type
        FROM documents
        WHERE motion_processed = FALSE
          AND text_content IS NOT NULL
          AND length(text_content) > 100
        ORDER BY id
        LIMIT %s;
    """, (limit,))
    return cur.fetchall()


def extract_motions_with_ai(doc_name, text_content):
    trimmed_text = text_content[:45000]

    prompt = f"""
You are extracting Board of Trustees motions from a public meeting document.

Document name:
{doc_name}

Extract any board motions, recommended actions, approvals, resolutions, consent items, action items, vote outcomes, moved/seconded information, ayes, nays, abstains, and absent trustees.

Return ONLY valid JSON in this format:

{{
  "motions": [
    {{
      "meeting_date": "YYYY-MM-DD or null",
      "agenda_item_id": "string or null",
      "motion_text": "string",
      "moved_by": "string or null",
      "seconded_by": "string or null",
      "vote_result": "Approved, Failed, Passed, No Action, Unknown, or null",
      "topic": "string or null",
      "agenda_item": "string or null",
      "ayes": "comma-separated names or null",
      "nays": "comma-separated names or null",
      "abstains": "comma-separated names or null",
      "absent": "comma-separated names or null",
      "topic_category": "Personnel, Contract, Budget, Policy, Facilities, Academic, Student Services, Governance, Resolution, Consent, Other, or null",
      "consent_agenda": true or false,
      "dollar_amount": "numeric amount or null",
      "vendor_or_department": "string or null",
      "confidence_score": 0.0,
      "source_excerpt": "short supporting excerpt"
    }}
  ]
}}

Important:
- Include consent agenda approvals if they represent board action.
- Include recommended actions even when the document does not show the final vote.
- If no motions/actions are present, return: {{"motions": []}}
- Do not invent trustee names.
- Do not include commentary outside JSON.

Document text:
{trimmed_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You extract structured board motion data as valid JSON only."},
            {"role": "user", "content": prompt}
        ],
    )

    content = response.choices[0].message.content
    data = json.loads(content)

    return data.get("motions", [])


def clean_value(value):
    if value in ("", "null", "None"):
        return None
    return value


def insert_motion(cur, document_id, fallback_meeting_date, motion):
    meeting_date = clean_value(motion.get("meeting_date")) or fallback_meeting_date

    cur.execute("""
        INSERT INTO motions (
            document_id,
            meeting_date,
            agenda_item_id,
            motion_text,
            moved_by,
            seconded_by,
            vote_result,
            topic,
            agenda_item,
            ayes,
            nays,
            abstains,
            absent,
            topic_category,
            consent_agenda,
            dollar_amount,
            vendor_or_department,
            confidence_score,
            source_excerpt
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        );
    """, (
        document_id,
        meeting_date,
        clean_value(motion.get("agenda_item_id")),
        clean_value(motion.get("motion_text")),
        clean_value(motion.get("moved_by")),
        clean_value(motion.get("seconded_by")),
        clean_value(motion.get("vote_result")),
        clean_value(motion.get("topic")),
        clean_value(motion.get("agenda_item")),
        clean_value(motion.get("ayes")),
        clean_value(motion.get("nays")),
        clean_value(motion.get("abstains")),
        clean_value(motion.get("absent")),
        clean_value(motion.get("topic_category")),
        bool(motion.get("consent_agenda")) if motion.get("consent_agenda") is not None else False,
        clean_value(motion.get("dollar_amount")),
        clean_value(motion.get("vendor_or_department")),
        motion.get("confidence_score"),
        clean_value(motion.get("source_excerpt")),
    ))


def mark_document_processed(cur, document_id, note):
    cur.execute("""
        UPDATE documents
        SET motion_processed = TRUE,
            motion_processed_at = NOW(),
            motion_process_notes = %s
        WHERE id = %s;
    """, (note, document_id))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    conn = get_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                ensure_motion_tracking_columns(cur)

        with conn:
            with conn.cursor() as cur:
                docs = fetch_documents(cur, args.limit)

        if not docs:
            print("No unprocessed documents found.")
            return

        for doc_id, name, text_content, meeting_date, document_type in docs:
            print(f"Processing document {doc_id}: {name}")

            inserted_count = 0

            try:
                motions = extract_motions_with_ai(name, text_content)

                with conn:
                    with conn.cursor() as cur:
                        for motion in motions:
                            motion_text = clean_value(motion.get("motion_text"))

                            if not motion_text:
                                continue

                            insert_motion(cur, doc_id, meeting_date, motion)
                            inserted_count += 1

                        mark_document_processed(
                            cur,
                            doc_id,
                            f"completed: inserted {inserted_count} motions"
                        )

                print(f"Inserted {inserted_count} motions.")

            except Exception as e:
                error_message = str(e)[:500]

                with conn:
                    with conn.cursor() as cur:
                        mark_document_processed(
                            cur,
                            doc_id,
                            f"error: {error_message}"
                        )

                print(f"ERROR processing document {doc_id}: {error_message}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
