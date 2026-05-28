import os
import psycopg2

DATABASE_URL = os.environ["DATABASE_URL"]

TRUSTEES = [
    {"name": "Robert Aguilar", "role": "Trustee", "ward": "Ward 1", "current": True},
    {"name": "Ken Nunes", "role": "Clerk", "ward": "Ward 2", "current": True},
    {"name": "Raymond Macareno", "role": "President", "ward": "Ward 3", "current": True},
    {"name": "Connie Diaz", "role": "Trustee", "ward": "Ward 4", "current": True},
    {"name": "John Lehn", "role": "Vice President", "ward": "Ward 5", "current": True},
    {"name": "Elizabeth Martinez", "role": "Student Trustee", "ward": "2025-2026", "current": True},

    {"name": "Greg Sherman", "role": "Former Trustee", "ward": None, "current": False},
]


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def build_aliases(full_name):
    parts = full_name.split()
    last = parts[-1]

    return list(set([
        full_name,
        last,
        f"Trustee {last}",
        f"Mr. {last}",
        f"Ms. {last}",
        f"Mrs. {last}",
        f"Dr. {last}",
    ]))


def sync_trustees():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trustee_aliases (
                    id SERIAL PRIMARY KEY,
                    trustee_id INTEGER REFERENCES trustees(id) ON DELETE CASCADE,
                    alias TEXT UNIQUE NOT NULL
                );
            """)

            for trustee in TRUSTEES:
                cur.execute("""
                    INSERT INTO trustees (
                        name,
                        ward,
                        is_current
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (name)
                    DO UPDATE SET
                        ward = EXCLUDED.ward,
                        is_current = EXCLUDED.is_current
                    RETURNING id
                """, (
                    trustee["name"],
                    trustee["ward"],
                    trustee["current"],
                ))

                trustee_id = cur.fetchone()[0]

                for alias in build_aliases(trustee["name"]):
                    cur.execute("""
                        INSERT INTO trustee_aliases (
                            trustee_id,
                            alias
                        )
                        VALUES (%s, %s)
                        ON CONFLICT (alias)
                        DO NOTHING
                    """, (
                        trustee_id,
                        alias,
                    ))

    print("Trustee sync complete.")


if __name__ == "__main__":
    sync_trustees()
