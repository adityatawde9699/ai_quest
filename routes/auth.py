from flask import session, Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from extensions import db
from models import Admin, Team, RateBucket
from routes.common import audit

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def index():
    if current_user.is_authenticated:
        if getattr(current_user, "role", "") == "team":
            return redirect(url_for("teams.team_dashboard"))
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("auth.admin_login"))


@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated and getattr(current_user, "role", "") in (
        "admin", "super-admin"
    ):
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        if not allow_login("admin", request.form.get("username", "")):
            return "Too many login attempts. Wait one minute.", 429
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.active and admin.check_password(password):
            session.clear()
            session.permanent = True
            login_user(admin)
            import hashlib
            session["credential_version"] = hashlib.sha256(admin.password_hash.encode()).hexdigest()
            audit("Admin login", admin.username)
            db.session.commit()
            return redirect(url_for("admin.dashboard"))
        db.session.commit()
        flash("Username or password is incorrect.", "error")
    return render_template("admin_login.html")


@auth_bp.route("/team/login", methods=["GET", "POST"])
def team_login():
    if current_user.is_authenticated and getattr(current_user, "role", "") == "team":
        return redirect(url_for("teams.team_dashboard"))
    if request.method == "POST":
        if not allow_login("team", request.form.get("team_id", "").upper()):
            return "Too many login attempts. Wait one minute.", 429
        team_id = request.form.get("team_id", "").strip().upper()
        pin = request.form.get("pin", "")
        team = Team.query.filter_by(team_id=team_id).first()
        if team and team.status not in ("DISABLED", "DISQUALIFIED") and team.check_pin(pin):
            session.clear()
            session.permanent = True
            login_user(team)
            import hashlib
            session["credential_version"] = hashlib.sha256(team.pin_hash.encode()).hexdigest()
            audit("TEAM_LOGIN", team.team_id)
            db.session.commit()
            scan_token = request.form.get("scan", "").strip()
            return redirect(url_for("teams.team_dashboard", scan=scan_token) if scan_token else url_for("teams.team_dashboard"))
        db.session.commit()
        flash("Team ID or PIN is incorrect, or this team is disabled.", "error")
    return render_template("team_login.html", scan_token=request.args.get("scan", ""))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    destination = "auth.team_login" if getattr(current_user, "role", "") == "team" else "auth.admin_login"
    if current_user.is_authenticated:
        if getattr(current_user, "role", "") in ("admin", "super-admin"):
            audit("Admin logout", current_user.username)
        else:
            audit("TEAM_LOGOUT", current_user.team_id)
        logout_user()
        session.clear()
        db.session.commit()
    return redirect(url_for(destination))


def allow_login(kind, identity):
    """Limit account guesses and total attempts from one source across workers."""
    import hashlib
    import time
    window = int(time.time()) // 60
    source = request.remote_addr or "unknown"
    limits = ((f"{kind}:{source}:{identity[:120]}", 10),
              (f"{kind}:{source}", 30))
    exceeded = False
    for name, limit in limits:
        key = hashlib.sha256(name.encode()).hexdigest()
        bucket = db.session.get(RateBucket, key)
        if not bucket:
            bucket = RateBucket(key=key, window=window, count=0)
            db.session.add(bucket)
        if bucket.window != window:
            bucket.window, bucket.count = window, 0
        bucket.count += 1
        exceeded |= bucket.count > limit
    if exceeded:
        db.session.commit()
        return False
    return True
