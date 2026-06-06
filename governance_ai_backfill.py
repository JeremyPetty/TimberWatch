import os
import json
import argparse
import time
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from openai import OpenAI


DATABASE_URL = os.environ.get("DATABASE_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL environment variable.")

if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

client = OpenAI(api_key=OPENAI_API_KEY)


SYSTEM_PROMPT = """
You are analyzing community college district board motions, agendas, and minutes.

Your job is to extract governance intelligence from the motion and its source document.

Important closed session distinction:
- CLOSED_SESSION_AGENDA_ONLY means the document merely lists a closed session agenda item or heading.
- CLOSED_SESSION_NO_ACTION means the document says no reportable action was taken.
- CLOSED_SESSION_ACTION_REPORTED means the document reports actual action taken, approval, ratification, settlement approval, expulsion approval, discipline action, employment action, or another concrete action arising from closed session.
- NOT_CLOSED_SESSION means unrelated to closed session.

Do not mark a motion as CLOSED_SESSION_ACTION_REPORTED just because the agenda contains:
"Closed Session", "Closed Session Reportable Actions", "Conference with Legal Counsel", "Labor Negotiator", "Public Employee Discipline", or similar headings.

Only mark CLOSED_SESSION_ACTION_REPORTED if actual action is described.

Return only valid JSON with this schema:
{
  "closed_session_status": "NOT_CLOSED_SESSION | CLOSED_SESSION_AGENDA_ONLY | CLOSED_SESSION_NO_ACTION | CLOSED_SESSION_ACTION_REPORTED",
  "closed_session_action_type": "None | Student Discipline | Personnel | Labor Negotiations | Legal / Litigation | Real Estate | Settlement | Other",
  "board_action_type": "Approval | Adoption | Ratification | Authorization | Information Only | First Reading | Second Reading | No Action | Tabled | Rejected | Other",
  "governance_significance_score": 1,
  "controversy_score": 0,
  "consent_agenda_related": false,
  "financial_impact_flag": false,
  "financial_impact_amount": null,
  "personnel_impact_flag": false,
  "legal_risk_flag": false,
  "policy_change_flag": false,
  "public_comment_flag": false,
  "public_comment_topic": "",
  "strategic_priority": "Budget Stability | Facilities Expansion | Labor Relations | Technology Modernization | Enrollment Growth | Student Success | Governance Operations | Legal Compliance | Community Partnerships | Workforce Development | Other",
  "election_cycle_theme": "",
  "governance_flags": [],
  "confidence": 0.0,
  "reason": ""
}

Scoring:
- governance_significance_score: 1 routine, 2 minor, 3 meaningful, 4 major, 5 transformational.
- controversy_score: 0 routine/no controversy, 10 highly controversial.
"""


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def trim_text(value, limit):
    value = value or ""
    value = " ".join(value.split())
    return value[:limit]


def safe_int(value, default=0, min_value=None, max_value=None):
    try:
        number = int(value)
    except Exception:
        number = default

    if min_value is not None:
        number = max(number, min_value)
    if max_value is not None:
        number = min(number, max_value)

    return number


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def safe_decimal_or_none(value):
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", ""))
    except Exception:
        return None


def safe_bool(value):
    return bool(value) if isinstance(value, bool) else str(value).lower() in ("true", "yes", "1")


def classify_motion(row):
    user_prompt = f"""
MOTION ID: {row["motion_id"]}
MEETING DATE: {row.get("meeting_date")}

MOTION TEXT:
{trim_text(row.get("motion_text"), 4000)}

SOURCE DOCUMENT NAME:
{row.get("document_name")}

SOURCE DOCUMENT TEXT:
{trim_text(row.get("document_text"), 14000)}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    return json.loads(response.choices[0].message.content)


def normalize_result(result):
    status = result.get("closed_session_status") or "NOT_CLOSED_SESSION"
    if status not in {
        "NOT_CLOSED_SESSION",
        "CLOSED_SESSION_AGENDA_ONLY",
        "CLOSED_SESSION_NO_ACTION",
        "CLOSED_SESSION_ACTION_REPORTED",
    }:
        status = "NOT_CLOSED_SESSION"

    closed_session_related = status == "CLOSED_SESSION_ACTION_REPORTED"

    normalized = {
        "closed_session_status": status,
        "closed_session_related": closed_session_related,
        "closed_session_action_type": result.get("closed_session_action_type") or "None",
        "board_action_type": result.get("board_action_type") or "Other",
        "governance_significance_score": safe_int(
            result.get("governance_significance_score"), default=1, min_value=1, max_value=5
        ),
        "controversy_score": safe_int(
            result.get("controversy_score"), default=0, min_value=0, max_value=10
        ),
        "consent_agenda_related": safe_bool(result.get("consent_agenda_related")),
        "financial_impact_flag": safe_bool(result.get("financial_impact_flag")),
        "financial_impact_amount": safe_decimal_or_none(result.get("financial_impact_amount")),
        "personnel_impact_flag": safe_bool(result.get("personnel_impact_flag")),
        "legal_risk_flag": safe_bool(result.get("legal_risk_flag")),
        "policy_change_flag": safe_bool(result.get("policy_change_flag")),
        "public_comment_flag": safe_bool(result.get("public_comment_flag")),
        "strategic_priority": result.get("strategic_priority") or "Other",
        "confidence": safe_float(result.get("confidence"), default=0.0),
        "reason": result.get("reason") or "",
        "raw": result,
    }

    return normalized


def main(limit, dry_run, force, sleep_seconds):
    with get_conn() as conn:
        with conn.cursor() as cur:
            where_force = "" if force else "AND m.ai_governance_signals IS NULL"

            cur.execute(f"""
                SELECT
                    m.id AS motion_id,
                    m.meeting_date,
                    m.motion_text,
                    d.name AS document_name,
                    d.text_content AS document_text
                FROM motions m
                LEFT JOIN documents d ON d.id = m.document_id
                WHERE 1=1
                    {where_force}
                    AND (
                        COALESCE(m.motion_text, '') <> ''
                        OR COALESCE(d.text_content, '') <> ''
                    )
                ORDER BY m.meeting_date DESC NULLS LAST, m.id DESC
                LIMIT %s
            """, [limit])

            rows = cur.fetchall()

            if not rows:
                print("No motions remaining for governance AI backfill.")
                return

            print(f"Processing {len(rows)} motions...")

            for row in rows:
                motion_id = row["motion_id"]

                try:
                    result = classify_motion(row)
                    normalized = normalize_result(result)

                    print(
                        f"Motion {motion_id}: "
                        f"{normalized['closed_session_status']} | "
                        f"significance={normalized['governance_significance_score']} | "
                        f"controversy={normalized['controversy_score']} | "
                        f"priority={normalized['strategic_priority']}"
                    )

                    if not dry_run:
                        cur.execute("""
                            UPDATE motions
                            SET
                                closed_session_ai_status = %s,
                                closed_session_ai_confidence = %s,
                                closed_session_ai_reason = %s,
                                closed_session_related = %s,
                                closed_session_action_type = %s,
                                governance_significance_score = %s,
                                consent_agenda_related = %s,
                                financial_impact_flag = %s,
                                financial_impact_amount = %s,
                                personnel_impact_flag = %s,
                                legal_risk_flag = %s,
                                policy_change_flag = %s,
                                public_comment_flag = %s,
                                board_action_type = %s,
                                strategic_priority = %s,
                                ai_governance_signals = %s
                            WHERE id = %s
                        """, [
                            normalized["closed_session_status"],
                            normalized["confidence"],
                            normalized["reason"],
                            normalized["closed_session_related"],
                            normalized["closed_session_action_type"],
                            normalized["governance_significance_score"],
                            normalized["consent_agenda_related"],
                            normalized["financial_impact_flag"],
                            normalized["financial_impact_amount"],
                            normalized["personnel_impact_flag"],
                            normalized["legal_risk_flag"],
                            normalized["policy_change_flag"],
                            normalized["public_comment_flag"],
                            normalized["board_action_type"],
                            normalized["strategic_priority"],
                            Json(normalized["raw"]),
                            motion_id,
                        ])
                        conn.commit()

                    if sleep_seconds:
                        time.sleep(sleep_seconds)

                except Exception as e:
                    conn.rollback()
                    print(f"ERROR processing motion {motion_id}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.0)
    args = parser.parse_args()

    main(
        limit=args.limit,
        dry_run=args.dry_run,
        force=args.force,
        sleep_seconds=args.sleep,
    )
