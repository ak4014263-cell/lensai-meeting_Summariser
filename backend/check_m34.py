import sqlite3
conn = sqlite3.connect('sql_app.db')
cur = conn.cursor()
cur.execute('SELECT id, status, title, meet_url, error_message FROM meetings WHERE id=34')
print('Meeting 34:', cur.fetchone())
cur.execute('SELECT id, message FROM meeting_events WHERE meeting_id=34 ORDER BY id ASC')
for row in cur.fetchall():
    print(row)
