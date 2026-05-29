"""
TimberWatch AI Classifier
-------------------------
Offline classification script for categorizing indexed board documents using an LLM.

What it does:
1. Reads documents from the existing `documents` table.
2. Sends document text to an AI model for structured classification.
3. Stores the result in a separate `ai_document_classifications` table.
4. Does NOT change your public FastAPI search app yet.

Required environment variables:
- DATABASE_URL
- OPENAI_API_KEY

Optional environment variables:
- AI_MODEL          default: gpt-4.1-mini
- AI_BATCH_LIMIT    default: 10
- AI_TEXT_LIMIT     default: 25000

Install dependencies:
    pip install psycopg2-binary openai

Run locally or in your Render shell:
    python ai_classifier.py

Run only one document:
    python ai_classifier.py --document-id 123

Reprocess documents already classified:
    python ai_classifier.py --reprocess
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from openai import OpenAI

import os

print("OPENAI_API_KEY exists:", "OPENAI_API_KEY" in os.environ)
print("Available vars:", list(os.environ.keys()))

DATABASE_URL = os.environ.get("DATABASE_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-4.1-mini")
AI_BATCH_LIMIT = int(os.environ.get("AI_BATCH_LIMIT", "10"))
AI_TEXT_LIMIT = int(os.environ.get("AI_TEXT_LIMIT", "25000"))

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL environment variable.")

if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

client = OpenAI(api_key=OPENAI_API_KEY)


CLASSIFICATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "document_category": {
            "type": "string",
            "enum": [
                "Board Agenda",
                "Board Minutes",
                "Board Policy",
                "Administrative Procedure",
                "Resolution",
                "Report",
                "Contract/Agreement",
                "Other",
                "Unknown",
            ],
        },
        "primary_topic": {"type": "string"},
        "topics": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 10,
        },
        "summary": {"type": "string"},
        "contains_motion": {"type": "boolean"},
        "contains_vote": {"type": "boolean"},
        "vote_result": {
            "type": "string",
            "enum": ["Passed", "Failed", "Tabled", "No Action", "Unclear", "None"],
        },
        "vote_margin": {"type": "string"},
        "motion_count_estimate": {"type": "integer", "minimum": 0},
        "failed_motion_count_estimate": {"type": "integer", "minimum": 0},
        "abstention_count_estimate": {"type": "integer", "minimum": 0},
        "notable_governance_flags": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "Split vote",
                    "Failed motion",
                    "Abstention",
                    "Absent trustee",
                    "Consent agenda action",
                    "Closed session reference",
                    "Public comment",
                    "Agenda control issue",
                    "Policy change",
                    "Budget/finance action",
                    "Personnel action",
                    "Land/facilities action",
                    "No clear issue",
                ],
            },
            "maxItems": 10,
        },
        "trustee_vote_summary": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "trustee_name": {"type": "string"},
                    "vote": {
                        "type": "string",
                        "enum": ["Yes", "No", "Abstain", "Absent", "Recused", "Unclear"],
                    },
                    "motion_or_item": {"type": "string"},
                    "supporting_excerpt": {"type": "string"},
                },
                "required": [
                    "trustee_name",
                    "vote",
                    "motion_or_item",
                    "supporting_excerpt",
                ],
            },
            "maxItems": 25,
        },
        "supporting_excerpt": {"type": "string"},
        "classification_confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "needs_human_review": {"type": "boolean"},
        "review_reason": {"type": "string"},
    },
    "required": [
        "document_category",
        "primary_topic",
        "topics",
        "summary",
        "contains_motion",
        "contains_vote",
        "vote_result",
        "vote_margin",
        "motion_count_estimate",
        "failed_motion_count_estimate",
        "abstention_count_estimate",
        "notable_governance_flags",
        "trustee_vote_summary",
        "supporting_excerpt",
        "classification_confidence",
        "needs_human_review",
        "review_reason",
    ],
}


SYSTEM_PROMPT = """
You are an offline civic records classification assistant for TimberWatch.
Your job is to classify board documents and identify actual governance actions.

Important rules:
- Do not classify casual mentions of words like yes, no, nay, failed, absent, or abstain as votes.
- Only mark contains_vote=true when the text clearly records a motion, action, roll call, vote result, or trustee vote.
- Only mark vote_result='Failed' when a motion clearly failed, was defeated, or did not pass.
- Phrases like "no public comment", "no discussion", "no report", or "no action taken" are not trustee no votes.
- Store uncertainty honestly. If the document is unclear, use vote_result='Unclear' and needs_human_review=true.
- Always include a short supporting excerpt copied from the provided text when possible.
- Keep summaries neutral and factual.
""".strip()


USER_PROMPT_TEMPLATE = """
Classify this TimberWatch document.

Document metadata:
- ID: {document_id}
- Name: {name}
- Source: {source}
- Document type: {document_type}
- Meeting date: {meeting_date}

Document text:
{text}
""".strip()


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def create_ai_table() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS ai_document_classifications (
        id SERIAL PRIMARY KEY,
        document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        model TEXT NOT NULL,
        document_category TEXT,
        primary_topic TEXT,
        topics JSONB,
        summary TEXT,
        contains_motion BOOLEAN,
        contains_vote BOOLEAN,
        vote_result TEXT,
        vote_margin TEXT,
        motion_count_estimate INTEGER,
        failed_motion_count_estimate INTEGER,
        abstention_count_estimate INTEGER,
        notable_governance_flags JSONB,
        trustee_vote_summary JSONB,
        supporting_excerpt TEXT,
        classification_confidence NUMERIC,
        needs_human_review BOOLEAN,
        review_reason TEXT,
        raw_json JSONB NOT NULL,
        classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (document_id, model)
    );

    CREATE INDEX IF NOT EXISTS idx_ai_doc_classifications_document_id
        ON ai_document_classifications(document_id);

    CREATE INDEX IF NOT EXISTS idx_ai_doc_classifications_vote_result
        ON ai_document_classifications(vote_result);

    CREATE INDEX IF NOT EXISTS idx_ai_doc_classifications_category
        ON ai_document_classifications(document_category);

    CREATE INDEX IF NOT EXISTS idx_ai_doc_classifications_review
        ON ai_document_classifications(needs_human_review);
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def fetch_documents(limit: int, document_id: Optional[int], reprocess: bool) -> List[Dict[str, Any]]:
    params: List[Any] = []

    where_parts = ["coalesce(text_content, '') <> ''"]

    if document_id is not None:
        where_parts.append("d.id = %s")
        params.append(document_id)

    if not reprocess:
        where_parts.append(
            """
            NOT EXISTS (
                SELECT 1
                FROM ai_document_classifications a
                WHERE a.document_id = d.id
                  AND a.model = %s
            )
            """
        )
        params.append(AI_MODEL)

    params.append(limit)

    sql = f"""
        SELECT
            d.id,
            d.source,
            d.name,
            d.document_type,
            d.meeting_date,
            d.text_content
        FROM documents d
        WHERE {' AND '.join(where_parts)}
        ORDER BY d.meeting_date DESC NULLS LAST, d.modified DESC NULLS LAST, d.id DESC
        LIMIT %s
    """

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def truncate_text(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text

    # Keep the beginning and end. Minutes often contain headings up top and votes later.
    head_len = int(limit * 0.65)
    tail_len = limit - head_len
    return text[:head_len] + "\n\n[... middle of document truncated ...]\n\n" + text[-tail_len:]


def classify_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    text = truncate_text(doc.get("text_content") or "", AI_TEXT_LIMIT)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        document_id=doc.get("id"),
        name=doc.get("name") or "",
        source=doc.get("source") or "",
        document_type=doc.get("document_type") or "",
        meeting_date=doc.get("meeting_date") or "",
        text=text,
    )

    response = client.responses.create(
        model=AI_MODEL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "timberwatch_document_classification",
                "schema": CLASSIFICATION_SCHEMA,
                "strict": True,
            }
        },
    )

    output_text = response.output_text
    return json.loads(output_text)


def save_classification(document_id: int, result: Dict[str, Any]) -> None:
    sql = """
        INSERT INTO ai_document_classifications (
            document_id,
            model,
            document_category,
            primary_topic,
            topics,
            summary,
            contains_motion,
            contains_vote,
            vote_result,
            vote_margin,
            motion_count_estimate,
            failed_motion_count_estimate,
            abstention_count_estimate,
            notable_governance_flags,
            trustee_vote_summary,
            supporting_excerpt,
            classification_confidence,
            needs_human_review,
            review_reason,
            raw_json,
            classified_at
        ) VALUES (
            %(document_id)s,
            %(model)s,
            %(document_category)s,
            %(primary_topic)s,
            %(topics)s,
            %(summary)s,
            %(contains_motion)s,
            %(contains_vote)s,
            %(vote_result)s,
            %(vote_margin)s,
            %(motion_count_estimate)s,
            %(failed_motion_count_estimate)s,
            %(abstention_count_estimate)s,
            %(notable_governance_flags)s,
            %(trustee_vote_summary)s,
            %(supporting_excerpt)s,
            %(classification_confidence)s,
            %(needs_human_review)s,
            %(review_reason)s,
            %(raw_json)s,
            %(classified_at)s
        )
        ON CONFLICT (document_id, model)
        DO UPDATE SET
            document_category = EXCLUDED.document_category,
            primary_topic = EXCLUDED.primary_topic,
            topics = EXCLUDED.topics,
            summary = EXCLUDED.summary,
            contains_motion = EXCLUDED.contains_motion,
            contains_vote = EXCLUDED.contains_vote,
            vote_result = EXCLUDED.vote_result,
            vote_margin = EXCLUDED.vote_margin,
            motion_count_estimate = EXCLUDED.motion_count_estimate,
            failed_motion_count_estimate = EXCLUDED.failed_motion_count_estimate,
            abstention_count_estimate = EXCLUDED.abstention_count_estimate,
            notable_governance_flags = EXCLUDED.notable_governance_flags,
            trustee_vote_summary = EXCLUDED.trustee_vote_summary,
            supporting_excerpt = EXCLUDED.supporting_excerpt,
            classification_confidence = EXCLUDED.classification_confidence,
            needs_human_review = EXCLUDED.needs_human_review,
            review_reason = EXCLUDED.review_reason,
            raw_json = EXCLUDED.raw_json,
            classified_at = EXCLUDED.classified_at;
    """

    payload = {
        "document_id": document_id,
        "model": AI_MODEL,
        "document_category": result.get("document_category"),
        "primary_topic": result.get("primary_topic"),
        "topics": json.dumps(result.get("topics", [])),
        "summary": result.get("summary"),
        "contains_motion": result.get("contains_motion"),
        "contains_vote": result.get("contains_vote"),
        "vote_result": result.get("vote_result"),
        "vote_margin": result.get("vote_margin"),
        "motion_count_estimate": result.get("motion_count_estimate"),
        "failed_motion_count_estimate": result.get("failed_motion_count_estimate"),
        "abstention_count_estimate": result.get("abstention_count_estimate"),
        "notable_governance_flags": json.dumps(result.get("notable_governance_flags", [])),
        "trustee_vote_summary": json.dumps(result.get("trustee_vote_summary", [])),
        "supporting_excerpt": result.get("supporting_excerpt"),
        "classification_confidence": result.get("classification_confidence"),
        "needs_human_review": result.get("needs_human_review"),
        "review_reason": result.get("review_reason"),
        "raw_json": json.dumps(result),
        "classified_at": datetime.now(timezone.utc),
    }

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, payload)
        conn.commit()


def print_result(document_id: int, result: Dict[str, Any]) -> None:
    category = result.get("document_category")
    topic = result.get("primary_topic")
    vote = result.get("vote_result")
    confidence = result.get("classification_confidence")
    review = result.get("needs_human_review")

    print(
        f"Document {document_id}: {category} | {topic} | "
        f"vote={vote} | confidence={confidence} | review={review}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify TimberWatch documents with AI.")
    parser.add_argument("--document-id", type=int, default=None, help="Classify one document ID.")
    parser.add_argument("--limit", type=int, default=AI_BATCH_LIMIT, help="Maximum documents to classify.")
    parser.add_argument("--reprocess", action="store_true", help="Reprocess already-classified documents.")
    parser.add_argument("--sleep", type=float, default=0.25, help="Seconds to sleep between documents.")
    args = parser.parse_args()

    create_ai_table()

    docs = fetch_documents(
        limit=args.limit,
        document_id=args.document_id,
        reprocess=args.reprocess,
    )

    if not docs:
        print("No documents found to classify.")
        return 0

    print(f"Classifying {len(docs)} document(s) using model {AI_MODEL}...")

    success_count = 0
    failure_count = 0

    for doc in docs:
        document_id = doc["id"]
        name = doc.get("name") or "Untitled"
        print(f"\nProcessing document {document_id}: {name}")

        try:
            result = classify_document(doc)
            save_classification(document_id, result)
            print_result(document_id, result)
            success_count += 1
        except Exception as exc:
            failure_count += 1
            print(f"ERROR classifying document {document_id}: {exc}", file=sys.stderr)

        if args.sleep:
            time.sleep(args.sleep)

    print(f"\nDone. Successful: {success_count}. Failed: {failure_count}.")
    return 0 if failure_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
