import os
import json
import argparse
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI


DATABASE_URL = os.environ.get("DATABASE_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL environment variable.")

if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

client = OpenAI(api_key=OPENAI_API_KEY)


TOPIC_LIST = [
    "Budget / Finance",
    "Board Policy",
    "Facilities / Construction",
    "Personnel / HR",
    "Labor Relations / Collective Bargaining",
    "Student Services",
    "Academic Programs",
    "Contracts / Agreements",
    "Governance / Board Operations",
    "Safety / Security",
    "Technology / IT",
    "Grants / Funding",
    "Legal / Compliance",
    "Enrollment / Admissions",
    "Community / Partnerships",
    "Other"
]


def classify_motion_topic(motion_text):
    prompt = f"""
You are classifying board meeting motions for a public governance transparency project.

Choose the best topic from this list:
{", ".join(TOPIC_LIST)}

Return only valid JSON in this exact format:
{{
  "topic": "one topic from the list",
  "confidence": 0.00
}}

Motion text:
\"\"\"{motion_text}\"\"\"
"""

    response = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "You classify board motions into concise governance topics."},
            {"role": "user", "content": prompt},
        ],
        temperature=0
    )

    raw = response.choices[0].message.content.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "topic": "Other",
            "confidence": 0.25
        }

    topic = data.get("topic", "Other")
    confidence = data.get("confidence", 0.50)

    if topic not in TOPIC_LIST:
        topic = "Other"

    try:
        confidence = float(confidence)
    except Exception:
        confidence = 0.50

    return {
        "topic": topic,
        "confidence": confidence
    }


def get_motion_text_column(cur):
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'motions'
        ORDER BY ordinal_position;
    """)
    columns = [row["column_name"] for row in cur.fetchall()]

    for possible_column in ["motion_text", "text", "description", "motion", "summary"]:
        if possible_column in columns:
            return possible_column

    raise RuntimeError(
        f"Could not find a motion text column in motions table. Found columns: {columns}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            motion_text_column = get_motion_text_column(cur)

            cur.execute(f"""
                SELECT
                    m.id,
                    m.{motion_text_column} AS motion_text
                FROM motions m
                WHERE COALESCE(TRIM(m.{motion_text_column}), '') <> ''
                  AND NOT EXISTS (
                      SELECT 1
                      FROM motion_topics mt
                      WHERE mt.motion_id = m.id
                  )
                ORDER BY m.id
                LIMIT %s;
            """, (args.limit,))

            motions = cur.fetchall()

            if not motions:
                print("No motions remaining for topic classification.")
                return

            print(f"Classifying {len(motions)} motions...")

            for motion in motions:
                motion_id = motion["id"]
                motion_text = motion["motion_text"]

                print(f"Processing motion {motion_id}...")

                result = classify_motion_topic(motion_text)

                cur.execute("""
                    INSERT INTO motion_topics (
                        motion_id,
                        topic,
                        confidence,
                        created_at
                    )
                    VALUES (%s, %s, %s, NOW());
                """, (
                    motion_id,
                    result["topic"],
                    result["confidence"]
                ))

                conn.commit()

                print(
                    f"Inserted topic for motion {motion_id}: "
                    f"{result['topic']} ({result['confidence']})"
                )

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
