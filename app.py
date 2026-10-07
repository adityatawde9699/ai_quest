from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

import click
from flask import Flask, jsonify, send_from_directory
from flask_login import current_user
from flask_socketio import join_room

from config import Config
from extensions import csrf, db, login_manager, migrate, socketio
from models import Admin, Event, Round, Team


def create_app(test_config=None):
    app = Flask(__name__)
    import logging
    app.logger.setLevel(logging.INFO)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    Config.validate_runtime()
    if app.config["APP_ENV"] == "production":
        from urllib.parse import urlsplit
        app.config["TRUSTED_HOSTS"] = [urlsplit(app.config["PUBLIC_BASE_URL"]).hostname]
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:"):
        options = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}))
        options.setdefault("connect_args", {}).setdefault("timeout", 30)
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = options

    if app.config["TRUSTED_PROXY_COUNT"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        hops = app.config["TRUSTED_PROXY_COUNT"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=0)
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    socketio.init_app(app)
    login_manager.login_view = "auth.admin_login"

    @login_manager.user_loader
    def load_user(identity):
        if not identity or ":" not in identity:
            return None
        kind, record_id = identity.split(":", 1)
        model = Admin if kind == "admin" else Team if kind == "team" else None
        if not record_id.isdigit():
            return None
        user = db.session.get(model, int(record_id)) if model else None
        if user:
            if kind == "admin" and not user.active:
                return None
            import hashlib
            from flask import session
            if session.get("credential_version") != hashlib.sha256((user.pin_hash if kind == "team" else user.password_hash).encode()).hexdigest():
                return None
        return user

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import redirect, request, url_for

        endpoint = "auth.team_login" if request.path.startswith("/team") else "auth.admin_login"
        return redirect(url_for(endpoint))

    @socketio.on("join_admin")
    def join_admin_room():
        if current_user.is_authenticated and getattr(current_user, "role", "") in (
            "admin", "super-admin"
        ):
            try:
                join_room("admins")
                join_room(f"admin:{current_user.id}")
            except KeyError:
                # A concurrent disconnect can remove the Socket.IO session between room joins.
                return

    @socketio.on("join_participant")
    def join_participant_room():
        if current_user.is_authenticated and getattr(current_user, "role", "") in (
            "team", "admin", "super-admin"
        ):
            try:
                join_room("participants")
            except KeyError:
                return

    from routes import register_routes

    register_routes(app)

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon")

    @app.get("/health/db")
    def database_health():
        """Check database connectivity without exposing connection details."""
        from sqlalchemy import text

        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok", database=db.engine.dialect.name)

    @app.cli.command("create-admin")
    @click.option("--role", type=click.Choice(["admin", "super-admin"]), default="super-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(username, password, role):
        """Create an administrator without placing credentials in the frontend."""
        username = username.strip()
        if not username or len(username) > 80:
            raise click.ClickException("Use a username of 1–80 characters.")
        if not 12 <= len(password) <= 300:
            raise click.ClickException("Use an admin password of at least 12 characters.")
        with app.app_context():
            if Admin.query.filter_by(username=username).first():
                raise click.ClickException("That username already exists.")
            admin = Admin(username=username, role=role)
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            click.echo(f"Administrator {username} created.")

    @app.cli.command("init-db")
    def init_db():
        """Seed configuration after applying reviewed migrations."""
        initialize_database(app)
        click.echo("Database initialized; rounds 1-3 are ready/locked.")

    if app.config.get("AUTO_INIT_DB", False):
        initialize_database(app)
    install_request_guards(app)
    return app


def initialize_database(app):
    with app.app_context():
        # Schema is exclusively managed by reviewed Alembic migrations.
        if not db.session.get(Event, 1):
            db.session.add(Event(id=1, mode=app.config["EVENT_MODE"]))
        event = db.session.get(Event, 1)
        if event and app.config["EVENT_MODE"] == "PRODUCTION":
            event.mode = "PRODUCTION"
        rounds = [
            (1, "QR Riddle", "READY"),
            (2, "Quiz Challenge", "LOCKED"),
            (3, "Desktop Final Challenge", "LOCKED"),
        ]
        for number, name, status in rounds:
            if not Round.query.filter_by(number=number).first():
                db.session.add(Round(number=number, name=name, status=status))
        db.session.commit()


def install_request_guards(app):
    import uuid
    import json
    from flask import g, request
    from sqlalchemy import update
    from sqlalchemy.exc import SQLAlchemyError
    from werkzeug.exceptions import HTTPException
    from services.event import EventError

    @app.before_request
    def guard_mutations():
        g.request_id = str(uuid.uuid4())
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            # PostgreSQL row write lock is held through the request transaction.
            # SQLite uses its writer lock, making functional race tests meaningful.
            if request.is_json and request.get_data(cache=True).strip():
                payload = request.get_json()
                if not isinstance(payload, dict):
                    raise EventError("Expected a JSON object.", 400)
                for key, value in payload.items():
                    if key.endswith("_id") and key != "qr_id" and value not in (None, ""):
                        try:
                            if int(value) < 1:
                                raise ValueError
                        except (ValueError, TypeError):
                            raise EventError("Record IDs must be positive whole numbers.", 400)
            elif request.is_json and request.method != "DELETE":
                raise EventError("Expected a JSON object.", 400)
            db.session.execute(update(Event).where(Event.id == 1).values(version=Event.version + 1))

    @app.after_request
    def response_headers(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(EventError)
    def event_error(error):
        db.session.rollback()
        return jsonify(error=error.message), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        db.session.rollback()
        return jsonify(error=error.description), error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        db.session.rollback()
        app.logger.error(json.dumps({"event": "REQUEST_FAILED", "request_id": getattr(g, "request_id", None), "type": type(error).__name__}))
        if app.testing:
            raise error
        return jsonify(error="The request could not be completed. Contact the coordinator."), 500


app = create_app({"AUTO_INIT_DB": False})


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
