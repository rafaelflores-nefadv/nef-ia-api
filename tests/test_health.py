from fastapi.testclient import TestClient

from app.main import app


def test_liveness_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"

