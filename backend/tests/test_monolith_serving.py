"""The single process must serve the API and the SPA from one origin."""
from __future__ import annotations

import pytest

from app.config import settings

BUILT = (settings.frontend_dist / "index.html").is_file()
needs_build = pytest.mark.skipif(BUILT is False, reason="frontend/dist not built")


def test_api_and_ui_share_one_origin(client):
    """No CORS headers are needed because nothing is cross-origin."""
    assert client.get("/api/health").status_code == 200
    assert "access-control-allow-origin" not in client.get("/api/health").headers


def test_unknown_api_path_returns_json_not_html(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "Endpoint not found."


def test_health_endpoint_and_ready_probe_are_available(client):
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/health/ready").json()["status"] == "ok"


def test_openapi_docs_are_not_swallowed_by_the_spa_route(client):
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


@needs_build
def test_root_serves_the_application_shell(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<div id=\"root\">" in response.text
    assert response.headers["cache-control"] == "no-cache"


@needs_build
def test_client_side_routes_fall_back_to_the_shell(client):
    """/booking/manage/<token> is a React route, not a server route."""
    response = client.get("/booking/manage/some-opaque-token")
    assert response.status_code == 200
    assert "<div id=\"root\">" in response.text


@needs_build
def test_hashed_assets_are_served_and_cached_immutably(client):
    index = client.get("/").text
    asset = index.split('src="', 1)[1].split('"', 1)[0]
    assert asset.startswith("/assets/")

    response = client.get(asset)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@needs_build
@pytest.mark.parametrize(
    "path",
    [
        "/../.env",
        "/assets/../../.env",
        "/%2e%2e/.env",
        "/../backend/app/config.py",
    ],
)
def test_static_serving_cannot_escape_the_build_directory(client, path):
    """A traversal attempt must never return a file from outside dist."""
    response = client.get(path)
    # Either the shell (treated as an unknown SPA route) or a refusal — never
    # the contents of a file outside frontend/dist.
    assert response.status_code in (200, 400, 404)
    if response.status_code == 200:
        assert "JWT_SECRET" not in response.text
        assert "ADMIN_PASSWORD" not in response.text
        assert "class Settings" not in response.text


def test_security_headers_are_present_on_every_response(client):
    headers = client.get("/api/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
