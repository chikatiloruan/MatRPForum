import os
import sqlite3
import time
import threading
from datetime import datetime
from functools import wraps
from queue import Queue, Empty

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, jsonify, send_from_directory
)
from flask_sock import Sock

# try load config
try:
    import config as cfg
    ADMIN_USER = getattr(cfg, "ADMIN_USER", "admin")
    ADMIN_PASS = getattr(cfg, "ADMIN_PASS", "admin")
    DEBUG_PASS = getattr(cfg, "DEBUG_PASS", "debug")
    PANEL_SECRET = getattr(cfg, "PANEL_SECRET", "panel-secret-key")
    FORUM_BASE = getattr(cfg, "FORUM_BASE", "")
except Exception:
    ADMIN_USER = "admin"
    ADMIN_PASS = "admin"
    DEBUG_PASS = "debug"
    PANEL_SECRET = "panel-secret-key"
    FORUM_BASE = ""

# try to import bot modules if present
try:
    from bot.forum_tracker import ForumTracker, stay_online_loop
except Exception:
    ForumTracker = None

try:
    from bot import storage as bot_storage
except Exception:
    bot_storage = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(APP_DIR, "panel.db")
LOG_DIR = os.path.join(APP_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
ACTIONS_LOG = os.path.join(LOG_DIR, "actions.log")
VISITS_LOG = os.path.join(LOG_DIR, "visits.log")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("PANEL_SECRET") or PANEL_SECRET
sock = Sock(app)

# WebSocket connections (we'll send JSON messages)
ws_clients = []
ws_lock = threading.Lock()

# queue for background messages to broadcast
broadcast_q = Queue()

# DB helpers
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS visits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER,
        ts_iso TEXT,
        ip TEXT,
        path TEXT,
        ua TEXT,
        user TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER,
        ts_iso TEXT,
        actor TEXT,
        action TEXT,
        details TEXT
    )""")
    conn.commit()
    conn.close()

# logging utils
def append_file(path, line):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def log_action(actor, action, details=""):
    ts = int(time.time())
    ts_iso = datetime.utcfromtimestamp(ts).isoformat()
    # DB
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO actions (ts, ts_iso, actor, action, details) VALUES (?,?,?,?,?)",
                    (ts, ts_iso, actor or "", action or "", details or ""))
        conn.commit()
        conn.close()
    except Exception:
        pass
    # file
    line = f"[{ts_iso}] {actor or '-'} | {action} | {details}"
    append_file(ACTIONS_LOG, line)
    # broadcast
    broadcast_q.put({"type":"action", "payload": {"ts": ts, "ts_iso": ts_iso, "actor": actor, "action": action, "details": details}})

def log_visit(ip, path, ua, user):
    ts = int(time.time())
    ts_iso = datetime.utcfromtimestamp(ts).isoformat()
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO visits (ts, ts_iso, ip, path, ua, user) VALUES (?,?,?,?,?,?)",
                    (ts, ts_iso, ip or "", path or "", ua or "", user or ""))
        conn.commit()
        conn.close()
    except Exception:
        pass
    line = f"[{ts_iso}] {ip} {user or '-'} -> {path} // UA:{ua[:200]}"
    append_file(VISITS_LOG, line)
    broadcast_q.put({"type":"visit", "payload": {"ts": ts, "ts_iso": ts_iso, "ip": ip, "path": path, "ua": ua, "user": user}})

# auth decorators
def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper

def debug_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if session.get("debug") is not True:
            return redirect(url_for("debug_login", next=request.path))
        return f(*a, **kw)
    return wrapper

# before_request: log visits (but ignore static)
@app.before_request
def _before():
    ip = request.headers.get("X-Real-IP") or request.remote_addr or ""
    ua = request.headers.get("User-Agent", "")[:400]
    path = request.path
    user = session.get("user")
    if not path.startswith("/static"):
        try:
            log_visit(ip, path, ua, user)
        except Exception:
            pass

# ROUTES
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username","")
        p = request.form.get("password","")
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["user"] = u
            log_action(u, "login", "admin login")
            flash("Успешный вход", "success")
            return redirect(url_for("index"))
        flash("Неверный логин/пароль", "danger")
    return render_template("login.html", title="Вход в панель")

@app.route("/debug-login", methods=["GET","POST"])
def debug_login():
    if request.method == "POST":
        p = request.form.get("password","")
        if p == DEBUG_PASS:
            session["debug"] = True
            log_action(session.get("user","ANON"), "debug_login", "opened debug")
            return redirect(url_for("debug"))
        flash("Неверный debug пароль", "danger")
    return render_template("login.html", debug=True, title="Debug вход")

@app.route("/logout")
def logout():
    user = session.pop("user", None)
    session.pop("debug", None)
    log_action(user, "logout", "admin logout")
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM actions ORDER BY ts DESC LIMIT 30")
    actions = cur.fetchall()
    cur.execute("SELECT * FROM visits ORDER BY ts DESC LIMIT 40")
    visits = cur.fetchall()
    conn.close()

    # tracks from bot.storage (if available)
    tracks = []
    try:
        if bot_storage and hasattr(bot_storage, "list_all_tracks"):
            tracks = bot_storage.list_all_tracks()
        elif bot_storage and hasattr(bot_storage, "list_tracks"):
            tracks = bot_storage.list_tracks()
    except Exception:
        tracks = []

    # masked cookies
    cookies_masked = {}
    try:
        import config as cfg
        cookies_masked = {
            "xf_user": (getattr(cfg, "XF_USER","")[:8] + "...") if getattr(cfg, "XF_USER","") else "",
            "xf_session": (getattr(cfg, "XF_SESSION","")[:8] + "...") if getattr(cfg, "XF_SESSION","") else "",
            "xf_tfa_trust": (getattr(cfg, "XF_TFA_TRUST","")[:8] + "...") if getattr(cfg, "XF_TFA_TRUST","") else "",
        }
    except Exception:
        pass

    return render_template("dashboard.html",
                           actions=actions, visits=visits, tracks=tracks,
                           cookies=cookies_masked, forum_base=FORUM_BASE)

@app.route("/tracks/add", methods=["POST"])
@login_required
def add_track_route():
    url = request.form.get("url","").strip()
    peer_id = request.form.get("peer_id","").strip()
    actor = session.get("user")
    if not url:
        flash("URL обязателен", "warning")
        return redirect(url_for("index"))
    try:
        if bot_storage and hasattr(bot_storage, "add_track"):
            bot_storage.add_track(int(peer_id) if peer_id else 0, url, "forum")
            flash("Отслеживание добавлено (bot.storage)", "success")
            log_action(actor, "add_track", f"url={url} peer={peer_id}")
        else:
            # simulation
            flash("Отслеживание добавлено (симуляция)", "success")
            log_action(actor, "add_track_sim", f"url={url} peer={peer_id}")
    except Exception as e:
        flash(f"Ошибка: {e}", "danger")
        log_action(actor, "add_track_err", str(e))
    return redirect(url_for("index"))

@app.route("/tracks/remove", methods=["POST"])
@login_required
def remove_track_route():
    url = request.form.get("url","").strip()
    peer_id = request.form.get("peer_id","").strip()
    actor = session.get("user")
    try:
        if bot_storage and hasattr(bot_storage, "remove_track"):
            bot_storage.remove_track(int(peer_id) if peer_id else 0, url)
            flash("Отслеживание удалено", "success")
            log_action(actor, "remove_track", f"{url} peer={peer_id}")
        else:
            flash("Удалено (симуляция)", "success")
            log_action(actor, "remove_track_sim", f"{url} peer={peer_id}")
    except Exception as e:
        flash(f"Ошибка: {e}", "danger")
        log_action(actor, "remove_track_err", str(e))
    return redirect(url_for("index"))

@app.route("/debug")
@debug_required
def debug():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM actions ORDER BY ts DESC LIMIT 200")
    actions = cur.fetchall()
    cur.execute("SELECT * FROM visits ORDER BY ts DESC LIMIT 200")
    visits = cur.fetchall()
    conn.close()
    tracker_debug = None
    try:
        if ForumTracker:
            # quick debug on forum base
            tr = None
            try:
                tr = ForumTracker(None)
            except Exception:
                try:
                    import config as cfg
                    tr = ForumTracker(getattr(cfg,"XF_USER",""), getattr(cfg,"XF_TFA_TRUST",""), getattr(cfg,"XF_SESSION",""), None)
                except Exception:
                    tr = None
            if tr and hasattr(tr, "debug_reply_form"):
                tracker_debug = tr.debug_reply_form(FORUM_BASE or "/")
    except Exception as e:
        tracker_debug = f"tracker debug error: {e}"
    return render_template("debug.html", actions=actions, visits=visits, tracker_debug=tracker_debug)

@app.route("/logs/actions")
@login_required
def view_actions():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM actions ORDER BY ts DESC LIMIT 1000")
    rows = cur.fetchall()
    conn.close()
    return render_template("logs_actions.html", rows=rows)

@app.route("/logs/visits")
@login_required
def view_visits():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM visits ORDER BY ts DESC LIMIT 1000")
    rows = cur.fetchall()
    conn.close()
    return render_template("logs_visits.html", rows=rows)

# serve masked cookies via API
@app.route("/api/cookies")
@login_required
def api_cookies():
    try:
        import config as cfg
        cookies = {
            "xf_user": (getattr(cfg,"XF_USER","")[:8] + "...") if getattr(cfg,"XF_USER","") else "",
            "xf_session": (getattr(cfg,"XF_SESSION","")[:8] + "...") if getattr(cfg,"XF_SESSION","") else "",
            "xf_tfa_trust": (getattr(cfg,"XF_TFA_TRUST","")[:8] + "...") if getattr(cfg,"XF_TFA_TRUST","") else "",
        }
        return jsonify({"ok": True, "cookies": cookies})
    except Exception:
        return jsonify({"ok": False, "cookies": {}})

# WebSocket endpoint for live logs
@sock.route("/ws/logs")
def ws_logs(ws):
    # register
    with ws_lock:
        ws_clients.append(ws)
    try:
        # send a welcome message
        ws.send_json({"type":"info","payload":"connected"})
        # keep listening (client can send pings)
        while True:
            try:
                data = ws.receive(timeout=30)
                if data is None:
                    # timeout — continue to keep connection alive
                    continue
                # optionally handle messages from client
                # we'll ignore for now
            except Exception:
                # receive timeout or connection closed
                break
    finally:
        with ws_lock:
            try:
                ws_clients.remove(ws)
            except Exception:
                pass

# thread: broadcaster from queue -> all ws clients
def broadcaster_loop():
    while True:
        try:
            msg = broadcast_q.get(timeout=1)
        except Empty:
            continue
        with ws_lock:
            for c in list(ws_clients):
                try:
                    c.send_json(msg)
                except Exception:
                    try:
                        ws_clients.remove(c)
                    except Exception:
                        pass

# helper to broadcast simple text
def broadcast_text(txt):
    broadcast_q.put({"type":"info","payload": txt})

# start background broadcaster
threading.Thread(target=broadcaster_loop, daemon=True).start()

# try to start tracker if present (non-blocking)
if ForumTracker:
    try:
        # try to create with cookies from config if available
        try:
            tr = ForumTracker(None)
        except Exception:
            import config as cfg
            tr = ForumTracker(getattr(cfg,"XF_USER",""), getattr(cfg,"XF_TFA_TRUST",""), getattr(cfg,"XF_SESSION",""), None)
        # start it if has start()
        if hasattr(tr, "start"):
            try:
                tr.start()
                log_action("system","tracker_start","started by panel")
            except Exception:
                pass
    except Exception:
        pass

# init DB on startup
init_db()

if __name__ == "__main__":
    # ensure logs exist
    open(ACTIONS_LOG, "a", encoding="utf-8").close()
    open(VISITS_LOG, "a", encoding="utf-8").close()
    # run flask app
    app.run(host="0.0.0.0", port=8080, debug=False)
import os
import sqlite3
import time
import threading
from datetime import datetime
from functools import wraps
from queue import Queue, Empty

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, jsonify, send_from_directory
)
from flask_sock import Sock

# try load config
try:
    import config as cfg
    ADMIN_USER = getattr(cfg, "ADMIN_USER", "admin")
    ADMIN_PASS = getattr(cfg, "ADMIN_PASS", "admin")
    DEBUG_PASS = getattr(cfg, "DEBUG_PASS", "debug")
    PANEL_SECRET = getattr(cfg, "PANEL_SECRET", "panel-secret-key")
    FORUM_BASE = getattr(cfg, "FORUM_BASE", "")
except Exception:
    ADMIN_USER = "admin"
    ADMIN_PASS = "admin"
    DEBUG_PASS = "debug"
    PANEL_SECRET = "panel-secret-key"
    FORUM_BASE = ""

# try to import bot modules if present
try:
    from bot.forum_tracker import ForumTracker, stay_online_loop
except Exception:
    ForumTracker = None

try:
    from bot import storage as bot_storage
except Exception:
    bot_storage = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(APP_DIR, "panel.db")
LOG_DIR = os.path.join(APP_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
ACTIONS_LOG = os.path.join(LOG_DIR, "actions.log")
VISITS_LOG = os.path.join(LOG_DIR, "visits.log")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("PANEL_SECRET") or PANEL_SECRET
sock = Sock(app)

# WebSocket connections (we'll send JSON messages)
ws_clients = []
ws_lock = threading.Lock()

# queue for background messages to broadcast
broadcast_q = Queue()

# DB helpers
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS visits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER,
        ts_iso TEXT,
        ip TEXT,
        path TEXT,
        ua TEXT,
        user TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER,
        ts_iso TEXT,
        actor TEXT,
        action TEXT,
        details TEXT
    )""")
    conn.commit()
    conn.close()

# logging utils
def append_file(path, line):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def log_action(actor, action, details=""):
    ts = int(time.time())
    ts_iso = datetime.utcfromtimestamp(ts).isoformat()
    # DB
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO actions (ts, ts_iso, actor, action, details) VALUES (?,?,?,?,?)",
                    (ts, ts_iso, actor or "", action or "", details or ""))
        conn.commit()
        conn.close()
    except Exception:
        pass
    # file
    line = f"[{ts_iso}] {actor or '-'} | {action} | {details}"
    append_file(ACTIONS_LOG, line)
    # broadcast
    broadcast_q.put({"type":"action", "payload": {"ts": ts, "ts_iso": ts_iso, "actor": actor, "action": action, "details": details}})

def log_visit(ip, path, ua, user):
    ts = int(time.time())
    ts_iso = datetime.utcfromtimestamp(ts).isoformat()
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO visits (ts, ts_iso, ip, path, ua, user) VALUES (?,?,?,?,?,?)",
                    (ts, ts_iso, ip or "", path or "", ua or "", user or ""))
        conn.commit()
        conn.close()
    except Exception:
        pass
    line = f"[{ts_iso}] {ip} {user or '-'} -> {path} // UA:{ua[:200]}"
    append_file(VISITS_LOG, line)
    broadcast_q.put({"type":"visit", "payload": {"ts": ts, "ts_iso": ts_iso, "ip": ip, "path": path, "ua": ua, "user": user}})

# auth decorators
def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper

def debug_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if session.get("debug") is not True:
            return redirect(url_for("debug_login", next=request.path))
        return f(*a, **kw)
    return wrapper

# before_request: log visits (but ignore static)
@app.before_request
def _before():
    ip = request.headers.get("X-Real-IP") or request.remote_addr or ""
    ua = request.headers.get("User-Agent", "")[:400]
    path = request.path
    user = session.get("user")
    if not path.startswith("/static"):
        try:
            log_visit(ip, path, ua, user)
        except Exception:
            pass

# ROUTES
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username","")
        p = request.form.get("password","")
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["user"] = u
            log_action(u, "login", "admin login")
            flash("Успешный вход", "success")
            return redirect(url_for("index"))
        flash("Неверный логин/пароль", "danger")
    return render_template("login.html", title="Вход в панель")

@app.route("/debug-login", methods=["GET","POST"])
def debug_login():
    if request.method == "POST":
        p = request.form.get("password","")
        if p == DEBUG_PASS:
            session["debug"] = True
            log_action(session.get("user","ANON"), "debug_login", "opened debug")
            return redirect(url_for("debug"))
        flash("Неверный debug пароль", "danger")
    return render_template("login.html", debug=True, title="Debug вход")

@app.route("/logout")
def logout():
    user = session.pop("user", None)
    session.pop("debug", None)
    log_action(user, "logout", "admin logout")
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM actions ORDER BY ts DESC LIMIT 30")
    actions = cur.fetchall()
    cur.execute("SELECT * FROM visits ORDER BY ts DESC LIMIT 40")
    visits = cur.fetchall()
    conn.close()

    # tracks from bot.storage (if available)
    tracks = []
    try:
        if bot_storage and hasattr(bot_storage, "list_all_tracks"):
            tracks = bot_storage.list_all_tracks()
        elif bot_storage and hasattr(bot_storage, "list_tracks"):
            tracks = bot_storage.list_tracks()
    except Exception:
        tracks = []

    # masked cookies
    cookies_masked = {}
    try:
        import config as cfg
        cookies_masked = {
            "xf_user": (getattr(cfg, "XF_USER","")[:8] + "...") if getattr(cfg, "XF_USER","") else "",
            "xf_session": (getattr(cfg, "XF_SESSION","")[:8] + "...") if getattr(cfg, "XF_SESSION","") else "",
            "xf_tfa_trust": (getattr(cfg, "XF_TFA_TRUST","")[:8] + "...") if getattr(cfg, "XF_TFA_TRUST","") else "",
        }
    except Exception:
        pass

    return render_template("dashboard.html",
                           actions=actions, visits=visits, tracks=tracks,
                           cookies=cookies_masked, forum_base=FORUM_BASE)

@app.route("/tracks/add", methods=["POST"])
@login_required
def add_track_route():
    url = request.form.get("url","").strip()
    peer_id = request.form.get("peer_id","").strip()
    actor = session.get("user")
    if not url:
        flash("URL обязателен", "warning")
        return redirect(url_for("index"))
    try:
        if bot_storage and hasattr(bot_storage, "add_track"):
            bot_storage.add_track(int(peer_id) if peer_id else 0, url, "forum")
            flash("Отслеживание добавлено (bot.storage)", "success")
            log_action(actor, "add_track", f"url={url} peer={peer_id}")
        else:
            # simulation
            flash("Отслеживание добавлено (симуляция)", "success")
            log_action(actor, "add_track_sim", f"url={url} peer={peer_id}")
    except Exception as e:
        flash(f"Ошибка: {e}", "danger")
        log_action(actor, "add_track_err", str(e))
    return redirect(url_for("index"))

@app.route("/tracks/remove", methods=["POST"])
@login_required
def remove_track_route():
    url = request.form.get("url","").strip()
    peer_id = request.form.get("peer_id","").strip()
    actor = session.get("user")
    try:
        if bot_storage and hasattr(bot_storage, "remove_track"):
            bot_storage.remove_track(int(peer_id) if peer_id else 0, url)
            flash("Отслеживание удалено", "success")
            log_action(actor, "remove_track", f"{url} peer={peer_id}")
        else:
            flash("Удалено (симуляция)", "success")
            log_action(actor, "remove_track_sim", f"{url} peer={peer_id}")
    except Exception as e:
        flash(f"Ошибка: {e}", "danger")
        log_action(actor, "remove_track_err", str(e))
    return redirect(url_for("index"))

@app.route("/debug")
@debug_required
def debug():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM actions ORDER BY ts DESC LIMIT 200")
    actions = cur.fetchall()
    cur.execute("SELECT * FROM visits ORDER BY ts DESC LIMIT 200")
    visits = cur.fetchall()
    conn.close()
    tracker_debug = None
    try:
        if ForumTracker:
            # quick debug on forum base
            tr = None
            try:
                tr = ForumTracker(None)
            except Exception:
                try:
                    import config as cfg
                    tr = ForumTracker(getattr(cfg,"XF_USER",""), getattr(cfg,"XF_TFA_TRUST",""), getattr(cfg,"XF_SESSION",""), None)
                except Exception:
                    tr = None
            if tr and hasattr(tr, "debug_reply_form"):
                tracker_debug = tr.debug_reply_form(FORUM_BASE or "/")
    except Exception as e:
        tracker_debug = f"tracker debug error: {e}"
    return render_template("debug.html", actions=actions, visits=visits, tracker_debug=tracker_debug)

@app.route("/logs/actions")
@login_required
def view_actions():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM actions ORDER BY ts DESC LIMIT 1000")
    rows = cur.fetchall()
    conn.close()
    return render_template("logs_actions.html", rows=rows)

@app.route("/logs/visits")
@login_required
def view_visits():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM visits ORDER BY ts DESC LIMIT 1000")
    rows = cur.fetchall()
    conn.close()
    return render_template("logs_visits.html", rows=rows)

# serve masked cookies via API
@app.route("/api/cookies")
@login_required
def api_cookies():
    try:
        import config as cfg
        cookies = {
            "xf_user": (getattr(cfg,"XF_USER","")[:8] + "...") if getattr(cfg,"XF_USER","") else "",
            "xf_session": (getattr(cfg,"XF_SESSION","")[:8] + "...") if getattr(cfg,"XF_SESSION","") else "",
            "xf_tfa_trust": (getattr(cfg,"XF_TFA_TRUST","")[:8] + "...") if getattr(cfg,"XF_TFA_TRUST","") else "",
        }
        return jsonify({"ok": True, "cookies": cookies})
    except Exception:
        return jsonify({"ok": False, "cookies": {}})

# WebSocket endpoint for live logs
@sock.route("/ws/logs")
def ws_logs(ws):
    # register
    with ws_lock:
        ws_clients.append(ws)
    try:
        # send a welcome message
        ws.send_json({"type":"info","payload":"connected"})
        # keep listening (client can send pings)
        while True:
            try:
                data = ws.receive(timeout=30)
                if data is None:
                    # timeout — continue to keep connection alive
                    continue
                # optionally handle messages from client
                # we'll ignore for now
            except Exception:
                # receive timeout or connection closed
                break
    finally:
        with ws_lock:
            try:
                ws_clients.remove(ws)
            except Exception:
                pass

# thread: broadcaster from queue -> all ws clients
def broadcaster_loop():
    while True:
        try:
            msg = broadcast_q.get(timeout=1)
        except Empty:
            continue
        with ws_lock:
            for c in list(ws_clients):
                try:
                    c.send_json(msg)
                except Exception:
                    try:
                        ws_clients.remove(c)
                    except Exception:
                        pass

# helper to broadcast simple text
def broadcast_text(txt):
    broadcast_q.put({"type":"info","payload": txt})

# start background broadcaster
threading.Thread(target=broadcaster_loop, daemon=True).start()

# try to start tracker if present (non-blocking)
if ForumTracker:
    try:
        # try to create with cookies from config if available
        try:
            tr = ForumTracker(None)
        except Exception:
            import config as cfg
            tr = ForumTracker(getattr(cfg,"XF_USER",""), getattr(cfg,"XF_TFA_TRUST",""), getattr(cfg,"XF_SESSION",""), None)
        # start it if has start()
        if hasattr(tr, "start"):
            try:
                tr.start()
                log_action("system","tracker_start","started by panel")
            except Exception:
                pass
    except Exception:
        pass

# init DB on startup
init_db()

if __name__ == "__main__":
    # ensure logs exist
    open(ACTIONS_LOG, "a", encoding="utf-8").close()
    open(VISITS_LOG, "a", encoding="utf-8").close()
    # run flask app
    app.run(host="0.0.0.0", port=8080, debug=False)
