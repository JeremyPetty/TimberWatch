import argparse
from db import get_cursor

CURRENT_TRUSTEES = [
    ("Greg Sherman", "Ward 1", True),
    ("Ken Nunes", "Ward 2", True),
    ("Raymond Macareno", "Ward 3", True),
    ("Connie Diaz", "Ward 4", True),
    ("John Lehn", "Ward 5", True),
]

ALIASES = {
    "Greg Sherman": ["Sherman", "Trustee Sherman"],
    "Ken Nunes": ["Nunes", "Trustee Nunes"],
    "Raymond Macareno": ["Macareno", "Ray Macareno", "Trustee Macareno"],
    "Connie Diaz": ["Diaz", "Trustee Diaz"],
    "John Lehn": ["Lehn", "Trustee Lehn"],
}


def sync_trustees(mark_existing_not_current=False):
    with get_cursor() as cur:
        if mark_existing_not_current:
            cur.execute("UPDATE trustees SET is_current=false")
        for name, ward, is_current in CURRENT_TRUSTEES:
            cur.execute("""
                INSERT INTO trustees(name, ward, is_current)
                VALUES (%s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET ward=EXCLUDED.ward, is_current=EXCLUDED.is_current
                RETURNING id
            """, [name, ward, is_current])
            trustee_id = cur.fetchone()["id"]
            for alias in ALIASES.get(name, []):
                cur.execute("""
                    INSERT INTO trustee_aliases(trustee_id, alias)
                    VALUES (%s, %s)
                    ON CONFLICT (alias) DO UPDATE SET trustee_id=EXCLUDED.trustee_id
                """, [trustee_id, alias])
    print("Trustee sync complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mark-existing-not-current", action="store_true")
    args = parser.parse_args()
    sync_trustees(args.mark_existing_not_current)
