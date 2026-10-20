"""
EcoWise AI - Smart Energy Advisor
Flask application: authentication, SQLite history, and the /api/* endpoints.

Run:  python app.py      ->  http://127.0.0.1:5000
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime
from functools import wraps
from urllib.parse import urlparse

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import engine

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FAILED_LOGINS, LOCKOUT_SECONDS = 5, 300
_failed_logins: dict[str, list[float]] = {}      # key -> [count, first_attempt_ts]

DEMO_EMAIL, DEMO_PASSWORD = "demo@ecowise.ai", "Demo@1234"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    tariff_mode TEXT NOT NULL DEFAULT 'flat',
    tariff_rate REAL NOT NULL DEFAULT 8.0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    payload TEXT NOT NULL,
    kwh_month REAL NOT NULL,
    cost_before REAL NOT NULL,
    cost_after REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_user ON analyses(user_id, created_at);
"""


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------
def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_path=INSTANCE_DIR)
    app.config.update(
        DATABASE=os.path.join(INSTANCE_DIR, "ecowise.db"),
        SECRET_KEY=_load_secret_key(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=256 * 1024,
        SEED_DEMO=os.environ.get("ECOWISE_SEED_DEMO", "1") == "1",
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(_close_db)
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        if app.config["SEED_DEMO"] and not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            db.execute("INSERT INTO users (name, email, password_hash, created_at) VALUES (?,?,?,?)",
                       ("Demo User", DEMO_EMAIL, generate_password_hash(DEMO_PASSWORD), _now()))
            db.commit()

    register_hooks(app)
    register_routes(app)
    return app


def _load_secret_key() -> str:
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(INSTANCE_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    if "db" not in g:
        from flask import current_app
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def _close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# --------------------------------------------------------------------------
# Hooks: current user, CSRF, security headers
# --------------------------------------------------------------------------
def register_hooks(app: Flask) -> None:
    @app.before_request
    def load_user_and_check_csrf():
        session.setdefault("csrf", secrets.token_urlsafe(24))
        g.user = None
        uid = session.get("user_id")
        if uid:
            g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
            if g.user is None:
                session.pop("user_id", None)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            if not secrets.compare_digest(sent, session["csrf"]):
                if request.path.startswith("/api/"):
                    return jsonify(error="Invalid or missing CSRF token. Refresh the page."), 400
                abort(400, "Invalid or missing CSRF token. Refresh the page and try again.")

    @app.context_processor
    def inject_globals():
        return {"csrf_token": session.get("csrf", ""), "user": g.get("user")}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith("/api/") or g.get("user"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def handle_error(err):
        if request.path.startswith("/api/"):
            return jsonify(error=getattr(err, "description", "Bad request")), err.code
        return render_template("error.html", code=err.code, message=err.description), err.code


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify(error="Please sign in again."), 401
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def _safe_next(target: str | None) -> str:
    if target:
        p = urlparse(target)
        if not p.scheme and not p.netloc and target.startswith("/") and not target.startswith("//"):
            return target
    return url_for("dashboard")


def _password_problem(pw: str) -> str | None:
    if len(pw) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "Password must contain both letters and numbers."
    return None


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
def register_routes(app: Flask) -> None:

    # ---------------- pages ----------------
    @app.get("/")
    def index():
        return redirect(url_for("dashboard" if g.user else "login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if g.user:
            return redirect(url_for("dashboard"))
        form = {"name": "", "email": ""}
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            pw, confirm = request.form.get("password", ""), request.form.get("confirm", "")
            form = {"name": name, "email": email}
            problem = None
            if not 2 <= len(name) <= 60:
                problem = "Please enter your name (2-60 characters)."
            elif not EMAIL_RE.match(email) or len(email) > 120:
                problem = "Please enter a valid email address."
            elif _password_problem(pw):
                problem = _password_problem(pw)
            elif pw != confirm:
                problem = "Passwords do not match."
            elif get_db().execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                problem = "An account with this email already exists."
            if problem:
                flash(problem, "error")
            else:
                db = get_db()
                cur = db.execute("INSERT INTO users (name, email, password_hash, created_at) VALUES (?,?,?,?)",
                                 (name, email, generate_password_hash(pw), _now()))
                db.commit()
                session.clear()
                session["user_id"] = cur.lastrowid
                flash("Welcome to EcoWise AI! Your account is ready.", "success")
                return redirect(url_for("dashboard"))
        return render_template("register.html", form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("dashboard"))
        email = ""
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            pw = request.form.get("password", "")
            key = f"{request.remote_addr}|{email}"
            rec = _failed_logins.get(key)
            if rec and time.time() - rec[1] > LOCKOUT_SECONDS:
                _failed_logins.pop(key, None)
                rec = None
            if rec and rec[0] >= MAX_FAILED_LOGINS:
                flash("Too many failed attempts. Please wait a few minutes and try again.", "error")
            else:
                row = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if row and check_password_hash(row["password_hash"], pw):
                    _failed_logins.pop(key, None)
                    session.clear()
                    session["user_id"] = row["id"]
                    session.permanent = request.form.get("remember") == "on"
                    return redirect(_safe_next(request.args.get("next")))
                _failed_logins.setdefault(key, [0, time.time()])[0] += 1
                flash("Incorrect email or password.", "error")
        return render_template("login.html", email=email, demo_email=DEMO_EMAIL,
                               demo_password=DEMO_PASSWORD, show_demo=app.config["SEED_DEMO"])

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("login"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        cfg = {
            "presets": engine.PRESETS,
            "sample": engine.SAMPLE_HOME,
            "rules": engine.RULE_CATALOG,
            "slabs": [{"upto": (None if u == float("inf") else u), "rate": r} for u, r in engine.SAMPLE_SLABS],
            "defaults": {"tariff_mode": g.user["tariff_mode"], "tariff_rate": g.user["tariff_rate"]},
            "load_id": request.args.get("load", type=int),
        }
        return render_template("dashboard.html", cfg=cfg)

    @app.get("/history")
    @login_required
    def history():
        rows = get_db().execute(
            "SELECT id, title, kwh_month, cost_before, cost_after, created_at FROM analyses "
            "WHERE user_id = ? ORDER BY id DESC", (g.user["id"],)).fetchall()
        items = [dict(r) for r in rows]
        total_saved = sum((r["cost_before"] - r["cost_after"]) for r in items if r["cost_after"] is not None)
        return render_template("history.html", items=items, total_saved=total_saved)

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            mode = request.form.get("tariff_mode", "flat")
            try:
                rate = float(request.form.get("tariff_rate", "8"))
            except ValueError:
                rate = -1
            if not 2 <= len(name) <= 60:
                flash("Please enter your name (2-60 characters).", "error")
            elif mode not in ("flat", "slab") or not 0.5 <= rate <= 100:
                flash("Tariff rate must be between 0.5 and 100 Rs/kWh.", "error")
            else:
                db = get_db()
                db.execute("UPDATE users SET name=?, tariff_mode=?, tariff_rate=? WHERE id=?",
                           (name, mode, rate, g.user["id"]))
                db.commit()
                flash("Settings saved.", "success")
                return redirect(url_for("settings"))
        return render_template("settings.html")

    @app.post("/settings/password")
    @login_required
    def change_password():
        cur, new, confirm = (request.form.get(k, "") for k in ("current", "new", "confirm"))
        if not check_password_hash(g.user["password_hash"], cur):
            flash("Current password is incorrect.", "error")
        elif _password_problem(new):
            flash(_password_problem(new), "error")
        elif new != confirm:
            flash("New passwords do not match.", "error")
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), g.user["id"]))
            db.commit()
            flash("Password updated.", "success")
        return redirect(url_for("settings"))

    @app.post("/settings/delete")
    @login_required
    def delete_account():
        if not check_password_hash(g.user["password_hash"], request.form.get("password", "")):
            flash("Password is incorrect - account not deleted.", "error")
            return redirect(url_for("settings"))
        db = get_db()
        db.execute("DELETE FROM analyses WHERE user_id=?", (g.user["id"],))
        db.execute("DELETE FROM users WHERE id=?", (g.user["id"],))
        db.commit()
        session.clear()
        flash("Your account and data were deleted.", "success")
        return redirect(url_for("login"))

    # ---------------- JSON API ----------------
    def _parse_or_400():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return None, None, (jsonify(error="Invalid request body."), 400)
        apps, settings, errors = engine.parse_request(data)
        if errors:
            return None, None, (jsonify(error="Please fix the following:", details=errors[:8]), 400)
        return apps, settings, None

    @app.post("/api/optimize")
    @login_required
    def api_optimize():
        apps, settings, err = _parse_or_400()
        if err:
            return err
        return jsonify(engine.run_full(apps, settings))

    @app.post("/api/calculate")
    @login_required
    def api_calculate():
        apps, settings, err = _parse_or_400()
        if err:
            return err
        hours = (request.get_json(silent=True) or {}).get("hours")
        if (not isinstance(hours, list) or len(hours) != len(apps)
                or not all(isinstance(h, (int, float)) for h in hours)):
            return jsonify(error="Invalid what-if hours."), 400
        return jsonify(engine.what_if(apps, settings, hours))

    @app.post("/api/history")
    @login_required
    def api_history_save():
        apps, settings, err = _parse_or_400()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        title = str(body.get("title", "")).strip()[:80] or f"Analysis {datetime.now():%d %b %Y, %H:%M}"
        result = engine.run_full(apps, settings)      # recomputed server-side, never trusted from client
        opt = result["optimization"]
        before = result["analysis"]["before"]
        payload = json.dumps({"appliances": apps, "settings": settings})
        db = get_db()
        cur = db.execute(
            "INSERT INTO analyses (user_id, title, payload, kwh_month, cost_before, cost_after, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (g.user["id"], title, payload, before["kwh_month"], before["cost_month"],
             opt["after"]["cost_month"] if opt.get("feasible") else None, _now()))
        db.commit()
        return jsonify(id=cur.lastrowid, title=title), 201

    def _own_analysis(aid: int):
        row = get_db().execute("SELECT * FROM analyses WHERE id=? AND user_id=?", (aid, g.user["id"])).fetchone()
        if row is None:
            abort(404, "Analysis not found.")
        return row

    @app.get("/api/history/<int:aid>")
    @login_required
    def api_history_get(aid: int):
        row = _own_analysis(aid)
        data = json.loads(row["payload"])
        s = data["settings"]
        return jsonify(id=row["id"], title=row["title"], appliances=data["appliances"],
                       settings={"tariff_mode": s["tariff_mode"], "tariff_rate": s["tariff_rate"],
                                 "comfort_target": round(s["comfort_target"] * 100),
                                 "cap_kwh_day": s.get("cap_kwh_day"),
                                 "actual_kwh_month": s.get("actual_kwh_month")})

    @app.put("/api/history/<int:aid>")
    @login_required
    def api_history_rename(aid: int):
        _own_analysis(aid)
        title = str((request.get_json(silent=True) or {}).get("title", "")).strip()[:80]
        if not title:
            return jsonify(error="Please enter a name."), 400
        db = get_db()
        db.execute("UPDATE analyses SET title=? WHERE id=? AND user_id=?", (title, aid, g.user["id"]))
        db.commit()
        return jsonify(id=aid, title=title)

    @app.delete("/api/history/<int:aid>")
    @login_required
    def api_history_delete(aid: int):
        _own_analysis(aid)
        db = get_db()
        db.execute("DELETE FROM analyses WHERE id=? AND user_id=?", (aid, g.user["id"]))
        db.commit()
        return jsonify(ok=True)


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG", "1") == "1")
