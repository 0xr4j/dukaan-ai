"""PayPal actions, executed through PayPal's official Agent Toolkit.

LIVE mode: `paypal_agent_toolkit.shared.api.PayPalAPI` talks to the PayPal *sandbox*.
DEMO mode: the very same toolkit code path runs (parameter validation + payload
builders), but its HTTP client is swapped for an in-memory fake PayPal so the
app works with no credentials. The UI labels which mode is active.
"""
import json
import random
import string
from datetime import datetime, timedelta, timezone

from paypal_agent_toolkit.shared.api import PayPalAPI
from paypal_agent_toolkit.shared.configuration import Context

from . import config


def _rid(prefix: str, n: int = 4, groups: int = 4) -> str:
    chunk = lambda: "".join(random.choices(string.ascii_uppercase + string.digits, k=n))
    return prefix + "-".join(chunk() for _ in range(groups))


class FakePayPalClient:
    """Minimal in-memory stand-in for the PayPal REST API (sandbox-shaped responses)."""

    BASE = "https://api-m.sandbox.paypal.com"

    def __init__(self):
        self.products: dict[str, dict] = {}
        self.invoices: dict[str, dict] = {}
        self.disputes: dict[str, dict] = {}
        self._seed()

    # -- seed data so the demo has something to talk about -----------------
    def _seed(self):
        today = datetime.now(timezone.utc)
        k = 80 if config.CURRENCY == "INR" else 1  # keep demo prices realistic per currency
        f = lambda v: f"{float(v) * k:.2f}"
        paid = [("Priya", "Basmati rice 5kg", "2", "12.50"),
                ("Mehta Traders", "Sunflower oil 1L", "10", "3.20"),
                ("Sharma ji", "Masala chai 250g", "3", "2.75")]
        for i, (who, item, qty, price) in enumerate(paid):
            inv_id = _rid("INV2-")
            self.invoices[inv_id] = self._invoice_body(
                inv_id, who, item, qty, f(price), "PAID",
                (today - timedelta(hours=10 + i)).isoformat(timespec="seconds"))
        inv_id = _rid("INV2-")
        self.invoices[inv_id] = self._invoice_body(
            inv_id, "Sharma ji", "Steel tiffin box", "2", f("6.00"), "SENT",
            (today - timedelta(days=3)).isoformat(timespec="seconds"))
        d_id = "PP-D-" + "".join(random.choices(string.digits, k=5))
        self.disputes[d_id] = {
            "dispute_id": d_id,
            "create_time": (today - timedelta(days=1)).isoformat(timespec="seconds"),
            "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
            "status": "WAITING_FOR_SELLER_RESPONSE",
            "dispute_amount": {"currency_code": config.CURRENCY, "value": f("18.00")},
            "disputed_transactions": [{
                "seller_transaction_id": "3BC12345DE678901F",
                "buyer": {"name": "Anil Kumar"},
                "items": [{"item_name": "Pressure cooker 3L", "item_quantity": "1"}],
            }],
            "messages": [{"posted_by": "BUYER",
                          "content": "I paid 5 days ago but the cooker never arrived."}],
            "seller_response_due_date": (today + timedelta(days=9)).isoformat(timespec="seconds"),
            "offer": {"seller_tracking": {"carrier": "INDIA_POST", "tracking_number": "EK123456789IN",
                                          "status": "DELIVERED",
                                          "delivered_on": (today - timedelta(days=2)).date().isoformat()}},
        }

    def _invoice_body(self, inv_id, who, item, qty, price, status, created):
        total = f"{float(qty) * float(price):.2f}"
        return {
            "id": inv_id, "status": status,
            "detail": {"currency_code": config.CURRENCY, "invoice_number": str(1000 + len(self.invoices)),
                       "metadata": {"create_time": created,
                                    "recipient_view_url": f"https://www.sandbox.paypal.com/invoice/p/#{inv_id}"}},
            "primary_recipients": [{"billing_info": {"name": {"given_name": who}}}],
            "items": [{"name": item, "quantity": qty,
                       "unit_amount": {"currency_code": config.CURRENCY, "value": price}}],
            "amount": {"currency_code": config.CURRENCY, "value": total},
        }

    # -- REST verbs used by the toolkit handlers ---------------------------
    def post(self, uri, payload):
        if uri == "/v1/catalogs/products":
            pid = "PROD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=17))
            self.products[pid] = {"id": pid, **{k: v for k, v in payload.items() if v is not None},
                                  "create_time": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            return self.products[pid]
        if uri == "/v2/invoicing/invoices":
            inv_id = _rid("INV2-")
            items = payload.get("items", [])
            total = sum(float(i["quantity"]) * float(i["unit_amount"]["value"]) for i in items)
            body = {"id": inv_id, "status": "DRAFT", **payload,
                    "amount": {"currency_code": payload["detail"]["currency_code"], "value": f"{total:.2f}"}}
            body["detail"] = {**payload["detail"], "metadata": {
                "create_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "recipient_view_url": f"https://www.sandbox.paypal.com/invoice/p/#{inv_id}"}}
            self.invoices[inv_id] = body
            return {"rel": "self", "href": f"{self.BASE}/v2/invoicing/invoices/{inv_id}", "method": "GET"}
        if uri.startswith("/v2/invoicing/invoices/"):
            inv_id, action = uri.split("/")[4], uri.split("/")[5]
            inv = self.invoices[inv_id]
            if action == "send":
                inv["status"] = "SENT"
                return {"rel": "payer-view", "method": "GET",
                        "href": inv["detail"]["metadata"]["recipient_view_url"]}
            if action == "remind":
                return {}
            if action == "generate-qr-code":
                return {}
        if uri.startswith("/v1/customer/disputes/") and uri.endswith("/accept-claim"):
            d_id = uri.split("/")[4]
            self.disputes[d_id]["status"] = "RESOLVED"
            return {"links": [{"rel": "self", "href": f"{self.BASE}{uri.rsplit('/', 1)[0]}"}]}
        raise ValueError(f"Demo PayPal does not implement POST {uri}")

    def get(self, uri):
        path = uri.split("?")[0]
        if path == "/v1/catalogs/products":
            return {"products": list(self.products.values()), "total_items": len(self.products)}
        if path == "/v2/invoicing/invoices":
            items = sorted(self.invoices.values(), key=lambda i: i["detail"]["metadata"]["create_time"], reverse=True)
            return {"items": items, "total_items": len(items)}
        if path.startswith("/v2/invoicing/invoices/"):
            return self.invoices[path.split("/")[4]]
        if path == "/v1/customer/disputes":
            return {"items": [{k: d[k] for k in ("dispute_id", "create_time", "reason", "status", "dispute_amount")}
                              for d in self.disputes.values()]}
        if path.startswith("/v1/customer/disputes/"):
            return self.disputes[path.split("/")[4]]
        raise ValueError(f"Demo PayPal does not implement GET {uri}")

    def put(self, uri, payload, headers=None):
        raise ValueError("not used in demo")

    def delete(self, uri):
        raise ValueError("not used in demo")


class PayPal:
    """Thin wrapper: every call goes through PayPalAPI.run(<toolkit method>, params)."""

    def __init__(self):
        ctx = Context(sandbox=True, source="DUKAAN-AI")
        if config.PAYPAL_LIVE:
            self.api = PayPalAPI(config.PAYPAL_CLIENT_ID, config.PAYPAL_CLIENT_SECRET, ctx)
            self.mode = "SANDBOX"
        else:
            self.api = PayPalAPI("demo-client", "demo-secret", ctx)
            self.api._paypal_client = FakePayPalClient()
            self.mode = "DEMO"

    def run(self, method: str, params: dict) -> dict:
        out = self.api.run(method, params)
        if isinstance(out, (dict, list)):
            return out
        try:
            return json.loads(out) if out else {}
        except (TypeError, ValueError):
            return {"raw": str(out)}

    # ---- high level helpers used by the agent ----------------------------
    def create_product(self, name: str, category: str | None, description: str | None) -> dict:
        params = {"name": name[:127], "type": "PHYSICAL"}
        desc = " | ".join(x for x in (category, description) if x)
        if desc:
            params["description"] = desc[:256]
        return self.run("create_product", params)

    def create_and_send_invoice(self, customer: str, email: str, items: list[dict], note: str | None) -> dict:
        params = {
            "currency_code": config.CURRENCY,
            "invoicer_business_name": config.SHOP_NAME,
            "note": note or f"Thank you for shopping at {config.SHOP_NAME}!",
            "primary_recipients": [{"billing_info": {"name": {"given_name": customer}, "email_address": email}}],
            "items": [{"name": i["name"][:200], "quantity": str(i["quantity"]),
                       "unit_amount": {"currency_code": config.CURRENCY, "value": f"{float(i['unit_price']):.2f}"}}
                      for i in items],
        }
        if config.SHOP_EMAIL:
            params["invoicer_email_address"] = config.SHOP_EMAIL
        created = self.run("create_invoice", params)
        href = created.get("href") or next((l["href"] for l in created.get("links", []) if l.get("rel") == "self"), "")
        invoice_id = created.get("id") or href.rstrip("/").split("/")[-1]
        sent = self.run("send_invoice", {"invoice_id": invoice_id, "send_to_recipient": True})
        try:  # official QR endpoint (returns an image; we render our own QR from the pay link too)
            self.run("generate_invoice_qr_code", {"invoice_id": invoice_id, "width": 300, "height": 300})
        except Exception:
            pass
        detail = self.run("get_invoice", {"invoice_id": invoice_id})
        pay_url = (sent.get("href") if isinstance(sent, dict) else None) or \
            detail.get("detail", {}).get("metadata", {}).get("recipient_view_url", "")
        return {"invoice_id": invoice_id, "status": detail.get("status", "SENT"),
                "total": detail.get("amount", {}).get("value"), "pay_url": pay_url}

    def remind(self, invoice_id: str) -> dict:
        return self.run("send_invoice_reminder", {"invoice_id": invoice_id,
                                                  "note": f"Gentle reminder from {config.SHOP_NAME}. Thank you!"})

    def list_invoices(self) -> list[dict]:
        return self.run("list_invoices", {"page": 1, "page_size": 50, "total_required": True}).get("items", [])

    def list_disputes(self) -> list[dict]:
        return self.run("list_disputes", {"page_size": 10}).get("items", [])

    def get_dispute(self, dispute_id: str) -> dict:
        return self.run("get_dispute", {"dispute_id": dispute_id})

    def accept_dispute(self, dispute_id: str, note: str) -> dict:
        return self.run("accept_dispute_claim", {"dispute_id": dispute_id, "note": note})


_paypal: PayPal | None = None


def get() -> PayPal:
    global _paypal
    if _paypal is None:
        _paypal = PayPal()
    return _paypal
