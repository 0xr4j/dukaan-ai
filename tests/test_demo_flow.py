"""End-to-end tests in DEMO mode: real PayPal Agent Toolkit code path, fake PayPal HTTP."""
import os
import tempfile

os.environ["DEMO_MODE"] = "1"
os.environ["DATA_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient  # noqa: E402

from app import brain  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def cmd(text):
    r = client.post("/api/command", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_status_reports_demo():
    s = client.get("/api/status").json()
    assert s["paypal"] == "DEMO" and s["ai"] == "DEMO"


def test_hinglish_numbers():
    assert brain._numbers("teen bag ka pandrah sau") == [3, 1500]
    assert brain._numbers("bill bhej do") == []
    assert brain._numbers("dhai sau") == [250]


def test_spoken_invoice_requires_confirmation_then_sends():
    res = cmd("Sharma ji ko teen bag ka pandrah sau ka bill bhej do")
    assert res["type"] == "confirm" and res["intent"] == "create_invoice"
    assert res["card"]["total"] == 1500 and res["card"]["customer"] == "Sharma ji"
    done = client.post("/api/confirm", json={"pending_id": res["pending_id"], "approve": True}).json()
    assert done["type"] == "done"
    assert done["card"]["invoice_id"].startswith("INV2-")
    assert done["card"]["pay_url"].startswith("https://")
    qr = client.get("/api/qr.svg", params={"url": done["card"]["pay_url"]})
    assert qr.status_code == 200 and b"<svg" in qr.content


def test_cancel_does_nothing():
    res = cmd("Invoice Priya for 2 rice bags at 120 each")
    assert res["card"]["total"] == 240
    out = client.post("/api/confirm", json={"pending_id": res["pending_id"], "approve": False}).json()
    assert out["type"] == "info"


def test_briefing_and_unpaid_are_computed_from_paypal_data():
    b = client.get("/api/briefing").json()
    assert b["card"]["paid_count"] >= 3 and b["card"]["disputes"] == 1
    u = cmd("who hasn't paid?")
    assert u["intent"] == "unpaid" and u["card"]["rows"]


def test_add_product_and_dispute_flow():
    p = cmd("add Parle G biscuit 10 to catalog")
    assert p["type"] == "confirm" and p["card"]["price"] == 10
    done = client.post("/api/confirm", json={"pending_id": p["pending_id"], "approve": True}).json()
    assert done["card"]["paypal_product_id"].startswith("PROD-")
    d = cmd("any disputes?")
    assert d["card"]["kind"] == "dispute" and d["card"]["draft"]["reply"]


def test_camera_demo_creates_pending_product():
    r = client.post("/api/vision", json={"image": "data:image/jpeg;base64,/9j/4AAQ", "lang": "en"}).json()
    assert r["type"] == "confirm" and r["card"]["price"] > 0


def test_ledger():
    data = client.get("/api/ledger").json()
    assert data["invoices"] and data["activity"]
