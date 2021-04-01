import sqlite3

con = sqlite3.connect('db/fplmd.db')

with con:

    cur = con.cursor()
    
    cur.execute("DROP TABLE IF EXISTS player_news")
    cur.execute("CREATE TABLE player_news(id INTEGER PRIMARY KEY NOT NULL, player_id INT NOT NULL, news TEXT, team_id INT, created_at timestamp NOT NULL DEFAULT current_timestamp, updated_at timestamp NOT NULL DEFAULT current_timestamp)")