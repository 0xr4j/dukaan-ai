"""The Dukaan agent: turns an understood command into a PayPal plan.

Read-only actions (briefing, unpaid list, disputes) run immediately.
Anything that writes to PayPal (catalog, invoice, reminder, accepting a dispute)
is returned as a *pending* plan with a spoken read-back, and only runs after the
shopkeeper confirms ("haan" / "yes").
"""
import uuid
from datetime import datetime, timedelta, timezone

from . import brain, channel3, config, paypal_tools, store

PENDING: dict[str, dict] = {}
PAID = {"PAID", "MARKED_AS_PAID"}
OPEN = {"SENT", "UNPAID", "PARTIALLY_PAID", "SCHEDULED"}


def money(v) -> str:
    return f"{config.CURRENCY_SYMBOL}{float(v or 0):,.2f}"


def t(lang: str, hi: str, en: str) -> str:
    return hi if lang == "hi" else en


def _who(inv: dict) -> str:
    try:
        bi = inv["primary_recipients"][0]["billing_info"]
        n = bi.get("name", {})
        return n.get("full_name") or " ".join(x for x in (n.get("given_name"), n.get("surname")) if x) \
            or bi.get("email_address", "customer")
    except (KeyError, IndexError):
        return "customer"


def _amount(inv: dict) -> float:
    a = inv.get("amount") or inv.get("due_amount") or {}
    return float(a.get("value") or 0)


def _when(inv: dict) -> datetime | None:
    meta = inv.get("detail", {}).get("metadata", {})
    ts = meta.get("last_update_time") or meta.get("create_time") or inv.get("detail", {}).get("invoice_date")
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _pending(kind: str, lang: str, heard: str, readback: str, data: dict, card: dict) -> dict:
    pid = uuid.uuid4().hex[:12]
    PENDING[pid] = {"kind": kind, "lang": lang, "heard": heard, "data": data}
    return {"type": "confirm", "pending_id": pid, "say": readback, "card": card}


# --------------------------------------------------------------------------
def handle(text: str) -> dict:
    pp = paypal_tools.get()
    u = brain.understand(text)
    lang = u.get("language") or "en"
    intent = u.get("intent", "chitchat")
    engine = u.get("_engine")
    res = _route(pp, u, intent, lang, text)
    res.update({"intent": intent, "engine": engine, "lang": lang})
    if res["type"] != "confirm":
        store.log(text, intent, res.get("paypal_tool", "-"), res.get("card", {}), pp.mode)
    return res


def _route(pp, u, intent, lang, text) -> dict:
    if intent == "create_invoice":
        return _plan_invoice(u, lang, text)
    if intent == "add_product":
        p = u.get("product") or {}
        return plan_product(p.get("name") or "New item", p.get("price"), p.get("category"), None, lang, text)
    if intent == "send_reminder":
        return _plan_reminder(pp, u, lang, text)
    if intent == "briefing":
        return briefing(lang)
    if intent == "unpaid":
        return _unpaid(pp, lang)
    if intent in {"disputes", "accept_dispute"}:
        return _disputes(pp, lang, text, accept=intent == "accept_dispute")
    return {"type": "info", "say": u.get("reply") or t(lang, "Ji, boliye?", "How can I help?"), "card": {}}


# ---- invoices --------------------------------------------------------------
def _plan_invoice(u, lang, text) -> dict:
    cust = store.find_or_create_customer(u.get("customer") or "Walk-in customer")
    catalog = {p["name"].lower(): p for p in store.rows("products")}
    items, missing = [], []
    for it in u.get("items") or []:
        qty = float(it.get("quantity") or 1)
        unit = it.get("unit_price")
        if unit is None and it.get("line_total"):
            unit = float(it["line_total"]) / qty
        if unit is None:
            match = next((p for n, p in catalog.items() if it.get("name", "").lower() in n or n in it.get("name", "").lower()), None)
            unit = match["price"] if match else None
        if unit is None:
            missing.append(it.get("name", "item"))
            continue
        items.append({"name": it.get("name") or "Item", "quantity": int(qty) if qty.is_integer() else qty,
                      "unit_price": round(float(unit), 2)})
    if missing or not items:
        return {"type": "info", "card": {},
                "say": t(lang, f"{', '.join(missing) or 'Saaman'} ka daam batayiye, phir bill bana doon.",
                         f"What's the price for {', '.join(missing) or 'the items'}? Then I'll make the bill.")}
    total = round(sum(i["quantity"] * i["unit_price"] for i in items), 2)  # math in code, not in the model
    lines = ", ".join(f"{i['quantity']} {i['name']}" for i in items)
    say = t(lang, f"{cust['name']} ko {lines} ka bill, total {money(total)}. Bhej doon?",
            f"Invoice {cust['name']} for {lines}, total {money(total)}. Shall I send it?")
    card = {"kind": "invoice_preview", "customer": cust["name"], "email": cust["email"], "items": items,
            "total": total, "currency": config.CURRENCY}
    return _pending("invoice", lang, text, say, {"customer": cust, "items": items, "total": total}, card)


def _exec_invoice(pp, d, lang) -> dict:
    out = pp.create_and_send_invoice(d["customer"]["name"], d["customer"]["email"], d["items"], None)
    store.insert("invoices", paypal_invoice_id=out["invoice_id"], customer=d["customer"]["name"],
                 email=d["customer"]["email"], items=", ".join(f"{i['quantity']} x {i['name']}" for i in d["items"]),
                 total=d["total"], currency=config.CURRENCY, status=out["status"], pay_url=out["pay_url"],
                 created_at=store.now())
    say = t(lang, f"Bill bhej diya! {d['customer']['name']} QR scan karke {money(d['total'])} de sakte hain.",
            f"Invoice sent! {d['customer']['name']} can scan the QR to pay {money(d['total'])}.")
    return {"type": "done", "say": say, "paypal_tool": "create_invoice → send_invoice → get_invoice",
            "card": {"kind": "invoice_sent", **out, "customer": d["customer"]["name"], "total": d["total"]}}


# ---- catalog ---------------------------------------------------------------
def plan_product(name, price, category, description, lang, heard, vision: dict | None = None) -> dict:
    market = channel3.market_prices(name)
    source = "spoken"
    if price is None and market.get("suggested"):
        price, source = market["suggested"], "Channel3 market median"
    if price is None and vision and vision.get("estimated_price"):
        price, source = float(vision["estimated_price"]), "AI estimate"
    if price is None:
        return {"type": "info", "card": {"kind": "market", "market": market},
                "say": t(lang, f"{name} ka daam kitna rakhein?", f"What price should {name} be?")}
    price = round(float(price), 2)
    say = t(lang, f"{name} ko {money(price)} mein catalog mein jod doon?",
            f"Add {name} to the catalog at {money(price)}?")
    card = {"kind": "product_preview", "name": name, "price": price, "category": category,
            "price_source": source, "market": market, "vision": vision}
    return _pending("product", lang, heard, say,
                    {"name": name, "price": price, "category": category, "description": description,
                     "source": source}, card)


def _exec_product(pp, d, lang) -> dict:
    out = pp.create_product(d["name"], d.get("category"), d.get("description"))
    store.insert("products", name=d["name"], category=d.get("category"), price=d["price"], currency=config.CURRENCY,
                 paypal_product_id=out.get("id"), price_source=d["source"], created_at=store.now())
    return {"type": "done", "paypal_tool": "create_product",
            "say": t(lang, f"{d['name']} catalog mein jud gaya.", f"{d['name']} is now in your PayPal catalog."),
            "card": {"kind": "product_added", "paypal_product_id": out.get("id"), **d}}


# ---- reminders / unpaid ----------------------------------------------------
def _open_invoices(pp) -> list[dict]:
    return [i for i in pp.list_invoices() if i.get("status") in OPEN]


def _plan_reminder(pp, u, lang, text) -> dict:
    who = (u.get("customer") or "").lower().replace(" ji", "").strip()
    cands = [i for i in _open_invoices(pp) if not who or who.split()[0] in _who(i).lower()]
    if not cands:
        return {"type": "info", "card": {},
                "say": t(lang, "Koi baaki bill nahi mila.", "I couldn't find an unpaid invoice for them.")}
    inv = cands[0]
    say = t(lang, f"{_who(inv)} ko {money(_amount(inv))} ke baaki bill ki yaad dila doon?",
            f"Send {_who(inv)} a reminder for {money(_amount(inv))}?")
    return _pending("reminder", lang, text, say, {"invoice_id": inv["id"], "who": _who(inv), "amount": _amount(inv)},
                    {"kind": "reminder_preview", "invoice_id": inv["id"], "customer": _who(inv), "amount": _amount(inv)})


def _exec_reminder(pp, d, lang) -> dict:
    pp.remind(d["invoice_id"])
    return {"type": "done", "paypal_tool": "send_invoice_reminder",
            "say": t(lang, f"{d['who']} ko yaad dila di.", f"Reminder sent to {d['who']}."),
            "card": {"kind": "reminder_sent", **d}}


def _unpaid(pp, lang) -> dict:
    rows = [{"invoice_id": i["id"], "customer": _who(i), "amount": _amount(i), "status": i.get("status")}
            for i in _open_invoices(pp)]
    total = sum(r["amount"] for r in rows)
    if not rows:
        say = t(lang, "Sab ne paise de diye hain!", "Everyone has paid. Nothing pending!")
    else:
        names = ", ".join(r["customer"] for r in rows[:3])
        say = t(lang, f"{len(rows)} bill baaki hain, kul {money(total)}: {names}.",
                f"{len(rows)} invoices unpaid, {money(total)} in total: {names}.")
    return {"type": "info", "say": say, "paypal_tool": "list_invoices",
            "card": {"kind": "unpaid", "rows": rows, "total": total}}


# ---- briefing --------------------------------------------------------------
def briefing(lang: str = "en") -> dict:
    pp = paypal_tools.get()
    invoices = pp.list_invoices()
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    paid = [i for i in invoices if i.get("status") in PAID and (_when(i) or since) >= since]
    unpaid = [i for i in invoices if i.get("status") in OPEN]
    try:
        disputes = [d for d in pp.list_disputes() if d.get("status") not in {"RESOLVED"}]
    except Exception:
        disputes = []
    for i in invoices:
        store.update_invoice_status(i.get("id"), i.get("status"))
    paid_total = sum(_amount(i) for i in paid)
    unpaid_total = sum(_amount(i) for i in unpaid)
    say = t(lang,
            f"Pichhle 24 ghante mein {money(paid_total)} aaye, {len(paid)} bill se. "
            f"{len(unpaid)} bill baaki hain, {money(unpaid_total)}. "
            + (f"{len(disputes)} shikayat aayi hai, dekh lijiye." if disputes else "Koi shikayat nahi."),
            f"In the last 24 hours you received {money(paid_total)} from {len(paid)} invoices. "
            f"{len(unpaid)} invoices are unpaid, {money(unpaid_total)}. "
            + (f"{len(disputes)} dispute needs your attention." if disputes else "No disputes."))
    return {"type": "info", "say": say, "paypal_tool": "list_invoices + list_disputes",
            "card": {"kind": "briefing", "paid_total": paid_total, "paid_count": len(paid),
                     "unpaid_total": unpaid_total, "unpaid_count": len(unpaid), "disputes": len(disputes)}}


# ---- disputes --------------------------------------------------------------
def _disputes(pp, lang, text, accept=False) -> dict:
    open_d = [d for d in pp.list_disputes() if d.get("status") != "RESOLVED"]
    if not open_d:
        return {"type": "info", "card": {}, "paypal_tool": "list_disputes",
                "say": t(lang, "Koi khuli shikayat nahi hai.", "No open disputes. 🎉")}
    d = pp.get_dispute(open_d[0]["dispute_id"])
    tx = (d.get("disputed_transactions") or [{}])[0]
    facts = {"reason": d.get("reason"), "amount": d.get("dispute_amount"),
             "buyer": (tx.get("buyer") or {}).get("name"),
             "items": [i.get("item_name") for i in tx.get("items", [])],
             "buyer_message": (d.get("messages") or [{}])[0].get("content"),
             "tracking": (d.get("offer") or {}).get("seller_tracking"),
             "respond_by": d.get("seller_response_due_date")}
    draft = brain.draft_dispute_reply(facts, lang)
    amt = money((d.get("dispute_amount") or {}).get("value"))
    card = {"kind": "dispute", "dispute_id": d.get("dispute_id"), "facts": facts, "draft": draft}
    if accept:
        say = t(lang, f"{facts['buyer']} ki {amt} ki shikayat maan kar refund kar doon?",
                f"Accept {facts['buyer']}'s {amt} claim and refund them?")
        return _pending("accept_dispute", lang, text, say, {"dispute_id": d.get("dispute_id"),
                                                             "note": draft.get("reply", "Accepting claim.")}, card)
    say = t(lang, f"{facts['buyer']} ne {amt} ki shikayat ki hai. {draft.get('advice', '')}",
            f"{facts['buyer']} opened a {amt} dispute. {draft.get('advice', '')}")
    return {"type": "info", "say": say, "paypal_tool": "list_disputes + get_dispute", "card": card}


def _exec_accept(pp, d, lang) -> dict:
    pp.accept_dispute(d["dispute_id"], d["note"][:2000])
    return {"type": "done", "paypal_tool": "accept_dispute_claim",
            "say": t(lang, "Shikayat maan li, refund ho jayega.", "Claim accepted. The buyer will be refunded."),
            "card": {"kind": "dispute_closed", **d}}


# --------------------------------------------------------------------------
EXEC = {"invoice": _exec_invoice, "product": _exec_product, "reminder": _exec_reminder,
        "accept_dispute": _exec_accept}


def confirm(pending_id: str, approve: bool) -> dict:
    plan = PENDING.pop(pending_id, None)
    if not plan:
        return {"type": "info", "say": "That request expired. Please say it again.", "card": {}}
    lang = plan["lang"]
    pp = paypal_tools.get()
    if not approve:
        store.log(plan["heard"], plan["kind"], "-", {"cancelled": True}, pp.mode)
        return {"type": "info", "say": t(lang, "Theek hai, cancel kar diya.", "Okay, cancelled."), "card": {}}
    try:
        res = EXEC[plan["kind"]](pp, plan["data"], lang)
    except Exception as e:
        res = {"type": "error", "card": {"error": str(e)[:300]},
               "say": t(lang, "PayPal se error aaya, dobara koshish kijiye.", "PayPal returned an error. Please try again.")}
    store.log(plan["heard"], plan["kind"], res.get("paypal_tool", "-"), res.get("card"), pp.mode)
    return res
