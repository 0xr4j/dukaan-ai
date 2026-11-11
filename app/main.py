"""Dukaan AI web server."""
import io

import segno
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, brain, config, paypal_tools, store

app = FastAPI(title="Dukaan AI", version="1.0.0")
STATIC = config.ROOT / "static"
store.init()


class Say(BaseModel):
    text: str


class Confirm(BaseModel):
    pending_id: str
    approve: bool


class Photo(BaseModel):
    image: str  # data URL or base64 JPEG
    lang: str = "en"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    return config.modes()


@app.post("/api/command")
def command(body: Say):
    if not body.text.strip():
        raise HTTPException(400, "empty command")
    return agent.handle(body.text.strip()[:500])


@app.post("/api/confirm")
def confirm(body: Confirm):
    return agent.confirm(body.pending_id, body.approve)


@app.post("/api/vision")
def vision(body: Photo):
    if len(body.image) > 8_000_000:
        raise HTTPException(413, "image too large")
    try:
        seen = brain.recognise_product(body.image)
    except Exception as e:
        raise HTTPException(502, f"vision failed: {e}")
    res = agent.plan_product(seen.get("name", "New item"), None, seen.get("category"),
                             seen.get("description"), body.lang, "[camera]", vision=seen)
    res["engine"] = seen.get("_engine")
    return res


@app.get("/api/briefing")
def briefing(lang: str = "en"):
    return agent.briefing(lang)


@app.get("/api/ledger")
def ledger():
    # Invoices come straight from PayPal (source of truth); fall back to the local copy.
    try:
        invoices = [{"created_at": (i.get("detail", {}).get("metadata", {}).get("create_time") or ""),
                     "customer": agent._who(i),
                     "items": ", ".join(f"{x.get('quantity')} x {x.get('name')}" for x in i.get("items", [])) or "—",
                     "total": agent._amount(i), "status": i.get("status"), "paypal_invoice_id": i.get("id")}
                    for i in paypal_tools.get().list_invoices()]
    except Exception:
        invoices = store.rows("invoices")
    return {"products": store.rows("products"), "invoices": invoices,
            "activity": store.rows("activity")[:100], "customers": store.rows("customers")}


@app.get("/api/qr.svg")
def qr(url: str):
    if not url.startswith("https://"):
        raise HTTPException(400, "bad url")
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2, dark="#0b1f3a")
    return Response(buf.getvalue(), media_type="image/svg+xml")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
