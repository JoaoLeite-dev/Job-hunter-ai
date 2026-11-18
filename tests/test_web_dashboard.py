from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from job_hunter import create_app
from job_hunter.application.demo import run_demo
from job_hunter.application.resumes import import_template
from job_hunter.infrastructure.db import Profile
from tests.resume_fake import make_resume


def login(client):
    anonymous = client.get("/ui/session").json
    response = client.post(
        "/ui/login", json={"token": "test-token"}, headers={"X-CSRF-Token": anonymous["csrf_token"]}
    )
    assert response.status_code == 200
    return response.json


def test_browser_login_private_cookie_and_no_token_exposure(app):
    client = app.test_client()
    anonymous = client.get("/ui/session")
    assert anonymous.json["authenticated"] is False
    assert "test-token" not in anonymous.text
    assert client.get("/api/v1/dashboard").status_code == 401
    assert client.post("/ui/login", json={"token": "test-token"}).status_code == 403
    assert (
        client.post(
            "/ui/login",
            json={"token": "wrong"},
            headers={"X-CSRF-Token": anonymous.json["csrf_token"]},
        ).status_code
        == 401
    )
    state = login(client)
    assert state["authenticated"] is True
    assert state["csrf_token"] != anonymous.json["csrf_token"]
    assert client.get("/api/v1/dashboard").status_code == 200
    cookie = client.get_cookie("session")
    assert cookie.http_only and cookie.same_site == "Strict"
    with client.session_transaction() as browser:
        assert "test-token" not in str(dict(browser))
    assert client.get("/api/v1/dashboard").headers["Cache-Control"] == "private, no-store"


def test_session_mutations_need_csrf_but_bearer_scripts_still_work(app):
    configured = create_app(replace(app.extensions["settings"], discovery_mode="fixture"))
    client = configured.test_client()
    state = login(client)
    assert client.post("/api/v1/discovery/run").status_code == 403
    assert (
        client.post("/api/v1/discovery/run", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    )
    result = client.post("/api/v1/discovery/run", headers={"X-CSRF-Token": state["csrf_token"]})
    assert result.status_code == 200 and result.json["created"] == 3
    bearer = configured.test_client().post(
        "/api/v1/discovery/run", headers={"Authorization": "Bearer test-token"}
    )
    assert bearer.status_code == 200 and bearer.json["duplicates"] == 3
    configured.extensions["db_engine"].dispose()


def test_logout_blocks_private_api_and_requires_csrf(app):
    client = app.test_client()
    state = login(client)
    assert client.post("/ui/logout").status_code == 403
    response = client.post("/ui/logout", headers={"X-CSRF-Token": state["csrf_token"]})
    assert response.json["authenticated"] is False
    assert client.get("/api/v1/dashboard").status_code == 401


def test_api_rotation_invalidates_existing_browser_session(app):
    client = app.test_client()
    login(client)
    rotated = create_app(replace(app.extensions["settings"], api_token="rotated-token"))
    rotated.secret_key = app.secret_key
    other = rotated.test_client()
    other.set_cookie("session", client.get_cookie("session").value)
    assert other.get("/api/v1/dashboard").status_code == 401
    assert other.get("/ui/session").json["authenticated"] is False
    rotated.extensions["db_engine"].dispose()


def test_dashboard_has_actual_fixture_scores_and_synthetic_provenance(app):
    with app.extensions["session_factory"].begin() as db:
        run_demo(db)
    response = app.test_client().get(
        "/api/v1/dashboard", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
    assert response.json["stats"] == {"jobs": 3, "eligible": 1, "applications": 0, "templates": 0}
    jobs = response.json["jobs"]
    assert [j["company"] for j in jobs] == ["Demo BR", "Demo US", "Demo Unknown"]
    assert [j["score"] for j in jobs] == [35, 0, 40]
    assert all(j["is_demo"] and "sintético" in j["match_profile"] for j in jobs)
    assert response.json["integrations"]["email_enabled"] is False
    assert "test-token" not in response.text
    assert response.json["activity"]


def test_ui_build_serves_public_shell_without_credentials(app, tmp_path):
    package = tmp_path / "package"
    (package / "web" / "assets").mkdir(parents=True)
    (package / "web" / "index.html").write_text("<html>Public app shell</html>")
    (package / "web" / "assets" / "test.js").write_text("export const ready=true;")
    app.root_path = str(package)
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert "test-token" not in response.text
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert client.get("/assets/test.js").status_code == 200
    assert client.get("/assets/../index.html").status_code == 404


def test_pdf_master_preview_is_private_and_keeps_original(app):
    root = Path(app.extensions["settings"].resume_storage_root)
    source = make_resume(root / "master.docx")
    before = source.read_bytes()
    with app.extensions["session_factory"].begin() as db:
        db.add(Profile(id="preview", name="Synthetic preview"))
        db.flush()
        template, _ = import_template(db, root, source, "preview")
        template_id = template.id
    path = f"/api/v1/resume-templates/{template_id}/master.pdf"
    assert app.test_client().get(path).status_code == 401
    assert (
        app.test_client().get(path, headers={"Authorization": "Bearer test-token"}).status_code
        == 409
    )
    configured = create_app(replace(app.extensions["settings"], resume_render_enabled=True))
    renderer = Mock()
    renderer.render.return_value = b"%PDF-1.7 synthetic preview"
    configured.extensions["document_renderer_factory"] = lambda: renderer
    client = configured.test_client()
    login(client)
    result = client.get(path)
    assert result.status_code == 200 and result.data.startswith(b"%PDF")
    assert result.headers["Cache-Control"] == "private, no-store"
    assert source.read_bytes() == before
    configured.extensions["db_engine"].dispose()
