"""End-to-end API test (SQLite + in-memory store). Chalane ke liye:
pip install -r requirements.txt && SQL_URL=sqlite:///./test.db MONGO_URI=mongodb://127.0.0.1:1 pytest -q
(galat Mongo URI se app in-memory store par fallback karta hai)"""
import os

os.environ.setdefault("SQL_URL", "sqlite:///./test.db")
os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
os.environ.setdefault("MONGO_TIMEOUT_MS", "200")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.sample_data import generate_lines  # noqa: E402


def test_full_flow():
    raw = ("\n".join(generate_lines(hours=6, seed=11)) + "\n").encode()
    with TestClient(app) as c:
        assert c.get("/health").json()["log_store"] == "memory"

        r = c.post("/logs/upload", files={"file": ("sample.log", raw)})
        assert r.status_code == 200, r.text
        body = r.json()
        uid = body["upload"]["id"]
        kinds = sorted(a["alert_type"] for a in body["alerts"])
        assert kinds == ["brute_force", "spike"]

        # same file dobara -> duplicate
        assert c.post("/logs/upload", files={"file": ("sample.log", raw)}).json()["duplicate"] is True

        s = c.get("/logs/search", params={"upload_id": uid, "level": "error", "q": "timeout", "limit": 5}).json()
        assert s["total"] > 0 and len(s["items"]) <= 5

        alert_id = c.get("/alerts", params={"severity": "critical"}).json()[0]["id"]
        assert c.patch(f"/alerts/{alert_id}", json={"status": "acknowledged"}).json()["status"] == "acknowledged"

        assert c.get("/stats/summary").json()["level_counts"]["ERROR"] > 0
        assert len(c.get("/stats/error-trend", params={"freq": "1h"}).json()["points"]) >= 6
        assert c.get("/stats/top-errors").json()["items"]
        assert c.get("/charts/error-trend.png").headers["content-type"] == "image/png"

        # acknowledged alert re-analyze mein safe rehta hai
        c.post(f"/uploads/{uid}/analyze", params={"z_threshold": 5})
        assert any(a["id"] == alert_id for a in c.get("/alerts", params={"status": "acknowledged"}).json())

        assert c.post("/logs/upload", files={"file": ("bad.log", b"garbage only\n")}).status_code == 422
        assert c.delete(f"/uploads/{uid}").status_code == 204
