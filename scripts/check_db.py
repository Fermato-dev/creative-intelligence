import sqlite3
c = sqlite3.connect("data/creative_analysis.db")
tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t[0] for t in tables])
for t in tables:
    cnt = c.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
    print(f"  {t[0]}: {cnt} rows")
    if cnt > 0:
        cols = [d[0] for d in c.execute(f"SELECT * FROM {t[0]} LIMIT 1").description]
        print(f"    columns: {cols}")
c.close()
