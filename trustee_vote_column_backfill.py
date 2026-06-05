import os
import argparse
import re
import psycopg2


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL environment variable.")


SKIP_VALUES = {
    "",
    "none",
    "n/a",
    "na",
    "unknown",
    "unanimous",
    "all",
}


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def split_names(value):
    if not value:
        return []

    value = value.strip()

    if value.lower() in SKIP_VALUES:
        return []

    # Handles commas, semicolons, slashes, and "and"
    parts = re.split(r",|;|/|\band\b", value, flags=re.IGNORECASE)

    names = []
    for part in parts:
        name = part.strip()
        if not name:
            continue
        if name.lower() in SKIP_VALUES:
            continue
        names.append(name)

    return names


def fetch_motions(conn, limit):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                ayes,
                nays,
                abstains,
                absent
            FROM motions
            WHERE
                COALESCE(TRIM(ayes), '') <> ''
                OR COALESCE(TRIM(nays), '') <> ''
                OR COALESCE(TRIM(abstains), '') <> ''
                OR COALESCE(TRIM(absent), '') <> ''
            ORDER BY id
            LIMIT %s;
            """,
            (limit,)
        )
        return cur.fetchall()


def upsert_vote(cur, motion_id, trustee_name, vote):
    cur.execute(
        """
        SELECT id
        FROM trustee_votes
        WHERE motion_id = %s
          AND LOWER(TRIM(trustee_name)) = LOWER(TRIM(%s))
        LIMIT 1;
        """,
        (motion_id, trustee_name)
    )

    existing = cur.fetchone()

    if existing:
        cur.execute(
            """
            UPDATE trustee_votes
            SET vote = %s
            WHERE id = %s;
            """,
            (vote, existing[0])
        )
    else:
        cur.execute(
            """
            INSERT INTO trustee_votes (
                motion_id,
                trustee_name,
                vote
            )
            VALUES (%s, %s, %s);
            """,
            (motion_id, trustee_name, vote)
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    conn = get_connection()

    total_inserted = 0

    try:
        motions = fetch_motions(conn, args.limit)
        print(f"Found {len(motions)} motions with vote columns.")

        with conn.cursor() as cur:
            for motion_id, ayes, nays, abstains, absent in motions:
                rows_for_motion = 0

                for name in split_names(ayes):
                    upsert_vote(cur, motion_id, name, "Yes")
                    rows_for_motion += 1

                for name in split_names(nays):
                    upsert_vote(cur, motion_id, name, "No")
                    rows_for_motion += 1

                for name in split_names(abstains):
                    upsert_vote(cur, motion_id, name, "Abstain")
                    rows_for_motion += 1

                for name in split_names(absent):
                    upsert_vote(cur, motion_id, name, "Absent")
                    rows_for_motion += 1

                total_inserted += rows_for_motion

        conn.commit()
        print(f"Inserted/updated {total_inserted} trustee vote rows.")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
