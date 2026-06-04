"""Backfill simple motion_topics from existing motions.topic values."""
from db import get_cursor

with get_cursor() as cur:
    cur.execute("""
        INSERT INTO motion_topics(motion_id, topic, confidence)
        SELECT id, topic, 0.60
        FROM motions
        WHERE topic IS NOT NULL AND TRIM(topic) <> ''
        ON CONFLICT (motion_id, topic) DO NOTHING
    """)
print("Topic backfill complete.")
