import sqlite3

con = sqlite3.connect('fplmd.db')

with con:

    cur = con.cursor()

    cur.execute("DROP TABLE IF EXISTS subscriptions")
    cur.execute(
        "CREATE TABLE subscriptions(id INTEGER PRIMARY KEY NOT NULL, subscribed INTEGER NOT NULL, handle TEXT NOT NULL, team_id INT NOT NULL, mention_id INT NOT NULL, created_at timestamp NOT NULL DEFAULT current_timestamp, updated_at timestamp NOT NULL DEFAULT current_timestamp)"
        )