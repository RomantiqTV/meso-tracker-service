"""Download the contributed failed-read crops to a local folder, ready for training / labelling.

  CONTRIB_DATABASE_URL=<the contributions Neon URL> python server/scripts/pull_contrib.py F:\ClaudeScratch\contrib_data [--delete-after]

Writes <out>/png/<sha>.png and appends one row per new crop to <out>/index.jsonl ({sha, kind, meta, created_at, contributor}); a crop already pulled is skipped, so it is safe to rerun.
--delete-after removes the pulled rows from the server (frees the free-tier space). The `contributor` column is the keyed hash, never a licence id or e-mail.
"""
import json
import os
import sys

import psycopg


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    out, delete_after = argv[1], "--delete-after" in argv[2:]
    dsn = os.environ.get("CONTRIB_DATABASE_URL", "")
    if not dsn:
        print("Set CONTRIB_DATABASE_URL (the contributions database, not the licence one).")
        return 2
    os.makedirs(os.path.join(out, "png"), exist_ok=True)
    index = os.path.join(out, "index.jsonl")
    have = set()
    if os.path.exists(index):
        with open(index, encoding="utf-8") as f:
            have = {json.loads(x)["sha"] for x in f if x.strip()}
    new = 0
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT sha256, kind, meta, png, created_at, contributor FROM contrib_crops ORDER BY id")
        rows = cur.fetchall()
        with open(index, "a", encoding="utf-8") as idx:
            for sha, kind, meta, png, ts, who in rows:
                if sha in have:
                    continue
                with open(os.path.join(out, "png", sha + ".png"), "wb") as f:
                    f.write(bytes(png))
                idx.write(json.dumps({"sha": sha, "kind": kind, "meta": meta, "created_at": ts.isoformat(), "contributor": who}) + "\n")
                new += 1
        print("%d on the server, %d new, written to %s" % (len(rows), new, out))
        if delete_after and rows:
            cur.execute("DELETE FROM contrib_crops WHERE sha256 = ANY(%s)", ([r[0] for r in rows],))
            conn.commit()
            print("deleted %d from the server" % cur.rowcount)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
