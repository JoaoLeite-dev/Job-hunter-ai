"""Local browser sessions. API credentials never enter HTML or browser storage."""

import hashlib
import hmac
import secrets
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_from_directory, session

blueprint = Blueprint("web", __name__)


def auth_tag() -> str:
    key = current_app.secret_key
    key = key.encode() if isinstance(key, str) else key
    token = current_app.extensions["settings"].api_token
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def browser_authenticated() -> bool:
    actual = session.get("auth_tag", "")
    return bool(
        current_app.extensions["settings"].api_token
        and isinstance(actual, str)
        and hmac.compare_digest(actual, auth_tag())
    )


def csrf_valid() -> bool:
    expected = session.get("csrf_token")
    actual = request.headers.get("X-CSRF-Token", "")
    return (
        isinstance(expected, str)
        and bool(expected)
        and hmac.compare_digest(actual.encode(), expected.encode())
    )


def browser_session() -> dict:
    token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return {"authenticated": browser_authenticated(), "csrf_token": token}


@blueprint.get("/ui/session")
def get_session():
    return jsonify(browser_session())


@blueprint.post("/ui/login")
def login():
    if not csrf_valid():
        return jsonify(error="csrf_required"), 403
    body = request.get_json(silent=True)
    token = body.get("token") if isinstance(body, dict) else None
    expected = current_app.extensions["settings"].api_token
    if (
        not isinstance(token, str)
        or len(token) > 4096
        or not expected
        or not hmac.compare_digest(token.encode(), expected.encode())
    ):
        return jsonify(error="invalid_credentials"), 401
    session.clear()
    session["auth_tag"] = auth_tag()
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True
    return jsonify(browser_session())


@blueprint.post("/ui/logout")
def logout():
    if not csrf_valid():
        return jsonify(error="csrf_required"), 403
    session.clear()
    return jsonify(browser_session())


@blueprint.get("/")
def index():
    root = Path(current_app.root_path) / "web"
    if not (root / "index.html").is_file():
        return "A interface ainda precisa ser compilada. Execute npm run build em frontend/.", 503
    return send_from_directory(root, "index.html")


@blueprint.get("/assets/<path:filename>")
def assets(filename):
    root = Path(current_app.root_path) / "web" / "assets"
    return send_from_directory(root, filename, max_age=31536000)
