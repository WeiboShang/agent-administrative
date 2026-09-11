import asyncio
from pathlib import Path

from backend.main import app, serve_frontend
from backend.testing import ASGITestClient as TestClient


def test_health_reports_the_only_frontend():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["frontend"] == "spa"


def test_removed_legacy_expense_routes_are_not_reachable():
    paths = set(app.openapi()["paths"])
    assert not paths.intersection({
        "/api/expense/extract", "/api/expense/submit",
        "/api/expense/decide", "/api/expense/queue",
    })


def test_only_v5_human_evaluation_router_is_mounted():
    paths = set(app.openapi()["paths"])
    assert "/api/eval/v5/human/protocol" in paths
    assert "/api/eval/human/protocol" not in paths


def test_part_a_final_api_is_the_stable_evaluation_route():
    paths = set(app.openapi()["paths"])
    assert "/api/eval/part-a/final/latest" in paths
    assert "/api/eval/part-a/final/replay" in paths


def test_removed_legacy_static_mount_serves_only_the_spa_shell():
    response = asyncio.run(serve_frontend("static/app.js"))
    path = Path(response.path)
    assert path.name == "index.html"
    assert '<script type="module"' in path.read_text(encoding="utf-8")
