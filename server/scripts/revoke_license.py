"""One-off admin tool: revoke every active license belonging to a customer email.

Run as a Render "One-Off Job" on meso-tracker-api (rootDir is `server`, so env vars incl. DATABASE_URL
are already present): `python -m scripts.revoke_license someone@example.com`

Does NOT delete rows (keeps the audit trail / activation_log intact) - it just sets `revoked_at`, which
is what `repo.get_license_by_key_hash` already filters on (`WHERE ... revoked_at IS NULL`), so a revoked
license immediately stops being accepted by /v1/activate and /v1/status.
"""
import sys

from app.db import connect


def revoke_for_email(email: str):
    email = email.strip().lower()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE licenses SET revoked_at = now() "
            "WHERE customer_id = (SELECT id FROM customers WHERE email = %s) AND revoked_at IS NULL "
            "RETURNING id, key_hint",
            (email,),
        )
        rows = cur.fetchall()
        conn.commit()
    return rows


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.revoke_license <email>")
        sys.exit(1)
    revoked = revoke_for_email(sys.argv[1])
    if not revoked:
        print(f"No active licenses found for {sys.argv[1]}")
    else:
        for r in revoked:
            print(f"Revoked license {r['id']} ({r['key_hint']})")
