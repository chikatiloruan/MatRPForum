import sqlite3

conn = sqlite3.connect("data.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS tracks (
    peer_id INTEGER,
    url TEXT,
    type TEXT,
    last_id TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS warns (
    peer_id INTEGER,
    user_id INTEGER,
    count INTEGER DEFAULT 0
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS bans (
    peer_id INTEGER,
    user_id INTEGER
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS stats (
    key TEXT PRIMARY KEY,
    value INTEGER
)""")

conn.commit()

# ===== TRACKS =====

def add_track(peer_id, url, typ):
    cur.execute("INSERT INTO tracks VALUES (?, ?, ?, ?)",
                (peer_id, url, typ, None))
    conn.commit()

def remove_track(peer_id, url):
    cur.execute("DELETE FROM tracks WHERE peer_id=? AND url=?",
                (peer_id, url))
    conn.commit()

def list_tracks(peer_id):
    return cur.execute("SELECT url, type, last_id FROM tracks WHERE peer_id=?",
                       (peer_id,)).fetchall()

def list_all_tracks():
    return cur.execute("SELECT peer_id, url, type, last_id FROM tracks").fetchall()

def update_last(peer_id, url, last_id):
    cur.execute("UPDATE tracks SET last_id=? WHERE peer_id=? AND url=?",
                (last_id, peer_id, url))
    conn.commit()

# ===== WARNS =====

def add_warn(peer_id, user_id):
    row = cur.execute("SELECT count FROM warns WHERE peer_id=? AND user_id=?",
                      (peer_id, user_id)).fetchone()
    if row:
        cur.execute("UPDATE warns SET count=count+1 WHERE peer_id=? AND user_id=?",
                    (peer_id, user_id))
    else:
        cur.execute("INSERT INTO warns VALUES (?, ?, 1)",
                    (peer_id, user_id))
    conn.commit()

def get_warns(peer_id, user_id):
    row = cur.execute("SELECT count FROM warns WHERE peer_id=? AND user_id=?",
                      (peer_id, user_id)).fetchone()
    return row[0] if row else 0

def clear_warns(peer_id, user_id):
    cur.execute("DELETE FROM warns WHERE peer_id=? AND user_id=?",
                (peer_id, user_id))
    conn.commit()

# ===== BANS =====

def add_ban(peer_id, user_id):
    cur.execute("INSERT INTO bans VALUES (?, ?)", (peer_id, user_id))
    conn.commit()

def remove_ban(peer_id, user_id):
    cur.execute("DELETE FROM bans WHERE peer_id=? AND user_id=?",
                (peer_id, user_id))
    conn.commit()

def is_banned(peer_id, user_id):
    row = cur.execute("SELECT user_id FROM bans WHERE peer_id=? AND user_id=?",
                      (peer_id, user_id)).fetchone()
    return bool(row)

# ===== STATS =====

def stat_inc(key):
    cur.execute("INSERT INTO stats(key, value) VALUES (?,1) "
                "ON CONFLICT(key) DO UPDATE SET value=value+1", (key,))
    conn.commit()

def stat_get(key):
    row = cur.execute("SELECT value FROM stats WHERE key=?", (key,)).fetchone()
    return row[0] if row else 0
