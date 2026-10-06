import sqlite3
c = sqlite3.connect("sql_app.db")
print("id | status | source | error")
for row in c.execute(
    "select id, status, source, substr(coalesce(error_message,''),1,60) "
    "from meetings order by id desc limit 8"
):
    print(row)
