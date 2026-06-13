import sqlite3
import json

c = sqlite3.connect("data/tendia.db")
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("=== TABLES ===")
for t in tables:
    print(f"  {t}")

print()
print("=== SCHEMAS ===")
for t in tables:
    schema = c.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{t}'").fetchone()
    print(f"\n--- {t} ---")
    print(schema[0] if schema else "(no schema)")

if "kv_storage" in tables:
    print()
    print("=== KV_STORAGE collections (distinct) ===")
    rows = c.execute("SELECT DISTINCT collection, COUNT(*) FROM kv_storage GROUP BY collection").fetchall()
    for col, cnt in rows:
        print(f"  {col}: {cnt} entries")

    print()
    print("=== KV_STORAGE : echantillon des collections liees au profil ===")
    for col in [r[0] for r in rows]:
        if "profil" in col.lower() or "organisme" in col.lower():
            sample = c.execute(f"SELECT id FROM kv_storage WHERE collection=? LIMIT 5", (col,)).fetchall()
            print(f"\n  Collection '{col}' :")
            for (sid,) in sample:
                print(f"    id = {sid}")

c.close()
