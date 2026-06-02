import os
import json
import argparse
import psycopg2
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


def get_unprocessed_documents(limit=25):
    """
    Pull documents that do not already have extracted motions.
    This version assumes your documents table has:
    id, name, text_content.
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
        ORDER BY
            CASE
                WHEN d.document_type ILIKE '%minutes%' THEN 1
                WHEN d.name ILIKE '%minutes%' THEN 1
                WHEN d.document_type ILIKE '%agenda%' THEN 2
                WHEN d.name ILIKE '%agenda%' THEN 2
                ELSE 3
            END,
            d.meeting_date DESC NULLS LAST,
            d.id
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

GENERAL RULES:
- Extract formal motions only, not general discussion.
- If no motions are found, return {{"motions": []}}.
- Do not invent names, dates, dollar amounts, or votes.
- Leave unknown fields blank.
- confidence_score must be between 0 and 1.
- source_excerpt should be a short nearby excerpt from the document showing where the motion came from.

MOTION RULES:
- motion_text should describe the actual action voted on.
- moved_by should contain the person who moved the item, if listed.
- seconded_by should contain the person who seconded the item, if listed.
- vote_result should be one of: Approved, Failed, Tabled, Pulled, No Action, Unknown.
- topic_category should be a short category such as Personnel, Finance, Contract, Policy, Curriculum, Facilities, Governance, Consent Agenda, Legal, Student Services, Other.
- consent_agenda should be true if the item appears to be part of a consent agenda or consent calendar.
- dollar_amount should include any dollar amount tied to the motion, if present.
- vendor_or_department should include the vendor, department, employee group, or office tied to the motion, if present.

IMPORTANT TRUSTEE VOTE RULES:
- Extract individual trustee names whenever the document lists them.
- Put trustees voting yes, aye, or approving in the "ayes" field.
- Put trustees voting no, nay, or opposing in the "nays" field.
- Put trustees abstaining in the "abstains" field.
- Put trustees absent in the "absent" field.
- Store multiple trustee names as comma-separated values.
- Example: "John Doe, Jane Smith, Robert Jones"
- Preserve names as written in the document when possible.
- If the document says "Ayes: X, Y, Z" then put X, Y, Z in ayes.
- If the document says "Noes:" or "Nays:" then put those names in nays.
- If the document says "Absent:" then put those names in absent.
- If the document says "Abstain:" or "Abstentions:" then put those names in abstains.
- If the document only says "motion carried unanimously" but does not list names, leave ayes blank unless the same excerpt clearly lists all voting trustees present.
- If the document lists board members present and says a specific motion was unanimous, you may use the present board members as ayes only when the text clearly supports that they were voting members and no abstentions/absences are listed for that motion.
- Do not put staff names, presenters, vendors, or administrators into trustee vote fields unless they are clearly board/trustee voters.

COMMON BOARD MINUTES PATTERNS TO WATCH FOR:
- "Motion by Smith, seconded by Jones, carried unanimously."
- "Ayes: Smith, Jones, Brown. Noes: Garcia. Abstain: Lee. Absent: Miller."
- "The motion passed 5-0."
- "MSC Smith/Jones to approve..."
- "It was moved by Trustee Smith and seconded by Trustee Jones..."

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
                "content": "You extract structured motion and trustee vote data from board meeting documents. Return only valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    # Remove common code fence wrapping if the model returns it despite instructions.
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json\n", "", 1).replace("JSON\n", "", 1).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print("AI returned invalid JSON:")
        print(raw)
        return {"motions": []}


def normalize_motion(motion):
    """Normalize one AI motion object before inserting."""
    return {
        "meeting_date": motion.get("meeting_date") or None,
        "agenda_item": motion.get("agenda_item") or None,
        "motion_text": motion.get("motion_text") or None,
        "moved_by": motion.get("moved_by") or None,
        "seconded_by": motion.get("seconded_by") or None,
        "vote_result": motion.get("vote_result") or None,
        "ayes": motion.get("ayes") or None,
        "nays": motion.get("nays") or None,
        "abstains": motion.get("abstains") or None,
        "absent": motion.get("absent") or None,
        "topic_category": motion.get("topic_category") or None,
        "consent_agenda": bool(motion.get("consent_agenda", False)),
        "dollar_amount": motion.get("dollar_amount") or None,
        "vendor_or_department": motion.get("vendor_or_department") or None,
        "confidence_score": motion.get("confidence_score"),
        "source_excerpt": motion.get("source_excerpt") or None,
    }


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
        clean_motion = normalize_motion(motion)
        clean_motion["document_id"] = document_id
        rows.append(clean_motion)

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

        if motions:
            with_votes = sum(
                1 for m in motions
                if m.get("ayes") or m.get("nays") or m.get("abstains") or m.get("absent")
            )
            print(f"Motions with trustee vote names: {with_votes}")


if __name__ == "__main__":
    main()
