import sqlite3, sys
mid = int(sys.argv[1]) if len(sys.argv) > 1 else 7
c = sqlite3.connect("sql_app.db")
print(f"=== meeting {mid} ===")
for row in c.execute("select id,status,source,duration_ms,external_bot_id from meetings where id=?", (mid,)):
    print("meeting:", row)
segs = list(c.execute("select count(*) from transcript_segments where meeting_id=?", (mid,)))
print("transcript segments:", segs[0][0])
for row in c.execute("select start_time,speaker,substr(text,1,60) from transcript_segments where meeting_id=? order by start_time limit 5", (mid,)):
    print("  seg:", row)
summ = list(c.execute("select substr(executive_summary,1,120), key_points, model from summaries where meeting_id=?", (mid,)))
print("summary:", summ)
print("decisions:", list(c.execute("select count(*) from decisions where meeting_id=?", (mid,)))[0][0])
print("actions:", list(c.execute("select count(*) from action_items where meeting_id=?", (mid,)))[0][0])
print("--- events ---")
for row in c.execute("select level,message from meeting_events where meeting_id=? order by id", (mid,)):
    print(" ", row[0], row[1])
