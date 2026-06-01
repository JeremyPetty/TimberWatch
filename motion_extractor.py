import os
import json
import psycopg2
import argparse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL environment variable.")

if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

client = OpenAI(api_key=OPENAI_API_KEY)


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def get_unprocessed_documents(limit=5):
    """
    Pull documents that do not already have extracted motions.
    Assumes your documents table has: id, title/name, text_content, meeting_date.
    Adjust column names if needed.
    """

    sql = """
        SELECT 
            d.id,
            COALESCE(d.name, 'Untitled Document') AS title,
            d.text_content,
            NULL AS meeting_date
        FROM documents d
        WHERE d.text_content IS NOT NULL
          AND LENGTH(d.text_content) > 100
          AND NOT EXISTS (
              SELECT 1
              FROM motions m
              WHERE m.document_id = d.id
          )
        ORDER BY d.id
        LIMIT %s;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return cur.fetchall()


def extract_motions_with_ai(document_title, meeting_date, text_content):
    prompt = f"""
You are analyzing public board meeting documents.

Extract every formal motion from the document text.

Return ONLY valid JSON in this exact structure:

{{
  "motions": [
    {{
      "meeting_date": "",
      "agenda_item": "",
      "motion_text": "",
      "moved_by": "",
      "seconded_by": "",
      "vote_result": "",
      "ayes": "",
      "nays": "",
      "abstains": "",
      "absent": "",
      "topic_category": "",
      "consent_agenda": false,
      "dollar_amount": "",
      "vendor_or_department": "",
      "confidence_score": 0.0,
      "source_excerpt": ""
    }}
  ]
}}

Rules:
- Extract motions only, not general agenda discussion.
- If no motions are found, return {{"motions": []}}.
- vote_result should be values like Approved, Failed, Tabled, Pulled, No Action, Unknown.
- topic_category should be a short category such as Personnel, Finance, Contract, Policy, Curriculum, Facilities, Governance, Consent Agenda, Other.
- consent_agenda should be true if the item appears to be part of a consent agenda.
- confidence_score should be between 0 and 1.
- source_excerpt should be a short quote or nearby text showing where the motion came from.
- Do not invent names or votes. Leave unknown fields blank.

Document title:
{document_title}

Meeting date:
{meeting_date}

Document text:
{text_content[:50000]}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "You extract structured motion data from board meeting documents."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print("AI returned invalid JSON:")
        print(raw)
        return {"motions": []}


def insert_motions(document_id, motions):
    sql = """
        INSERT INTO motions (
            document_id,
            meeting_date,
            agenda_item,
            motion_text,
            moved_by,
            seconded_by,
            vote_result,
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
            %(document_id)s,
            %(meeting_date)s,
            %(agenda_item)s,
            %(motion_text)s,
            %(moved_by)s,
            %(seconded_by)s,
            %(vote_result)s,
            %(ayes)s,
            %(nays)s,
            %(abstains)s,
            %(absent)s,
            %(topic_category)s,
            %(consent_agenda)s,
            %(dollar_amount)s,
            %(vendor_or_department)s,
            %(confidence_score)s,
            %(source_excerpt)s
        );
    """

    rows = []

    for motion in motions:
        rows.append({
            "document_id": document_id,
            "meeting_date": motion.get("meeting_date"),
            "agenda_item": motion.get("agenda_item"),
            "motion_text": motion.get("motion_text"),
            "moved_by": motion.get("moved_by"),
            "seconded_by": motion.get("seconded_by"),
            "vote_result": motion.get("vote_result"),
            "ayes": motion.get("ayes"),
            "nays": motion.get("nays"),
            "abstains": motion.get("abstains"),
            "absent": motion.get("absent"),
            "topic_category": motion.get("topic_category"),
            "consent_agenda": motion.get("consent_agenda", False),
            "dollar_amount": motion.get("dollar_amount"),
            "vendor_or_department": motion.get("vendor_or_department"),
            "confidence_score": motion.get("confidence_score"),
            "source_excerpt": motion.get("source_excerpt"),
        })

    if not rows:
        return 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()

    return len(rows)


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    docs = get_unprocessed_documents(limit=args.limit)

    if not docs:
        print("No unprocessed documents found.")
        return

    for document_id, title, text_content, meeting_date in docs:
        print(f"\nProcessing document {document_id}: {title}")

        result = extract_motions_with_ai(
            document_title=title,
            meeting_date=meeting_date,
            text_content=text_content
        )

        motions = result.get("motions", [])

        inserted = insert_motions(document_id, motions)

        print(f"Inserted {inserted} motions.")


if __name__ == "__main__":
    main()
