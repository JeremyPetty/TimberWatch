from db import get_cursor

TABLES = [
    "agenda_items", "ai_document_classifications", "ai_motions", "ai_trustee_votes", "documents",
    "meetings", "motion_processing_status", "motion_sponsors", "motion_topics", "motions",
    "trustee_aliases", "trustee_votes", "trustees"
]

with get_cursor() as cur:
    for table in TABLES:
        try:
            cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            print(f"{table}: {cur.fetchone()['n']}")
        except Exception as exc:
            print(f"{table}: ERROR {exc}")
