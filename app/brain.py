"""The AI side: understand Hinglish commands, recognise products from a photo,
draft dispute replies. Uses Google Gemini when a key is set; otherwise a small
rule-based parser keeps the demo working (and the UI says so).

Trust rule: the model only *extracts* intent and values. All money math,
totals and briefings are computed in code from PayPal data.
"""
import base64
import json
import re

import httpx

from . import config

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

INTENT_PROMPT = """You are the brain of "Dukaan AI", a voice assistant for a small shopkeeper.
The shopkeeper speaks Hindi, English or Hinglish (romanised or Devanagari). Extract ONE intent.

Intents:
- create_invoice: bill / invoice / "bill bhejo" a customer for items.
- add_product: add a new item to the shop catalog.
- send_reminder: remind a customer to pay.
- briefing: how did business go / aaj ka hisaab / sales report.
- unpaid: who has not paid / baaki / udhaar list.
- disputes: complaints / disputes / shikayat.
- accept_dispute: accept / refund a dispute claim.
- chitchat: anything else (greeting, question about the app).

Return ONLY JSON:
{{"intent": "...",
 "customer": "name as spoken, keep honorifics like 'Sharma ji'" or null,
 "items": [{{"name": "item in English", "quantity": number, "unit_price": number or null, "line_total": number or null}}],
 "product": {{"name": "...", "price": number or null, "category": "..."}} or null,
 "dispute_id": "..." or null,
 "language": "hi" if the user mostly spoke Hindi/Hinglish else "en",
 "reply": "short friendly reply for chitchat, in the user's language" or null}}

Rules: numbers spoken as words ("pandrah sau" = 1500, "teen" = 3, "dhai sau" = 250) must become digits.
If only a total amount is given for an item, put it in line_total and leave unit_price null.
Never invent prices that were not said. Currency is {currency}.

Shopkeeper said: "{text}"
"""

VISION_PROMPT = """You are helping a small shopkeeper add an item to their catalog.
Look at the photo and identify the main retail product.
Return ONLY JSON: {{"name": "short product name a shop would use", "category": "e.g. Groceries, Kitchen, Stationery",
"description": "one short line", "search_query": "query to find this product online",
"estimated_price": typical retail price as a number in {currency}, "confidence": 0-1}}"""

DISPUTE_PROMPT = """You help a small shopkeeper reply to a PayPal dispute. Facts (from PayPal, do not invent others):
{facts}
Write a short, polite, factual reply to the buyer/PayPal (max 70 words) in English, using only these facts.
Then a one-line advice to the shopkeeper in {lang_name} on whether to contest or accept.
Return ONLY JSON: {{"reply": "...", "advice": "..."}}"""


class AIError(RuntimeError):
    pass


def _gemini(parts: list, temperature: float = 0.1) -> dict:
    r = httpx.post(GEMINI_URL.format(model=config.GEMINI_MODEL),
                   params={"key": config.GEMINI_API_KEY},
                   json={"contents": [{"role": "user", "parts": parts}],
                         "generationConfig": {"temperature": temperature,
                                              "responseMimeType": "application/json"}},
                   timeout=45)
    if r.status_code != 200:
        raise AIError(f"Gemini error {r.status_code}: {r.text[:300]}")
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(re.sub(r"^```(json)?|```$", "", text.strip()).strip())


# --------------------------------------------------------------------------
# Intent understanding
# --------------------------------------------------------------------------
def understand(text: str) -> dict:
    if config.AI_LIVE:
        try:
            out = _gemini([{"text": INTENT_PROMPT.format(text=text.replace('"', "'"), currency=config.CURRENCY)}])
            out["_engine"] = "gemini"
            return out
        except Exception as e:
            fallback = rule_parse(text)
            fallback["_engine"] = f"rules (Gemini failed: {str(e)[:80]})"
            return fallback
    out = rule_parse(text)
    out["_engine"] = "rules (demo)"
    return out


_UNITS = {
    "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4,
    "paanch": 5, "panch": 5, "five": 5, "chhe": 6, "che": 6, "six": 6, "saat": 7, "seven": 7,
    "aath": 8, "eight": 8, "nau": 9, "nine": 9, "das": 10, "ten": 10, "gyarah": 11, "eleven": 11,
    "barah": 12, "twelve": 12, "pandrah": 15, "fifteen": 15, "bees": 20, "twenty": 20,
    "pachas": 50, "pachaas": 50, "fifty": 50, "dhai": 2.5, "dedh": 1.5,
    "thirty": 30, "forty": 40, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_MULT = {"sau": 100, "hundred": 100, "hazaar": 1000, "hazar": 1000, "thousand": 1000}
_HINDI_WORDS = {"ka", "ki", "ke", "ko", "bhejo", "bhej", "do", "hai", "aaj", "kal", "kitna", "baaki", "jodo", "naya"}


def _numbers(text: str) -> list[float]:
    """Pull numbers from digits and spoken number words (Hindi + English)."""
    tokens = re.findall(r"\d+(?:\.\d+)?|[a-z]+", text.lower().replace(",", ""))
    nums, cur = [], None
    for idx, t in enumerate(tokens):
        prev = tokens[idx - 1] if idx else ""
        is_last = idx == len(tokens) - 1
        # "do" is both the number two and the verb "give" ("bhej do")
        verb_do = t == "do" and (is_last or prev in {"bhej", "de", "kar", "bata", "dikha", "jod", "bol"})
        if re.fullmatch(r"\d+(?:\.\d+)?", t):
            if cur is not None:
                nums.append(cur)
            cur = float(t)
        elif t in _UNITS and not verb_do:
            if cur is not None:
                nums.append(cur)
            cur = float(_UNITS[t])
        elif t in _MULT:
            cur = (cur or 1) * _MULT[t]
        else:
            if cur is not None:
                nums.append(cur)
                cur = None
    if cur is not None:
        nums.append(cur)
    return nums


def _known_customer(text: str) -> str | None:
    from . import store
    low = text.lower()
    for c in store.rows("customers"):
        first = c["name"].lower().replace(" ji", "").split()[0]
        if first in low:
            return c["name"]
    m = re.search(r"([A-Z][a-z]+(?: ji)?)\s+(?:ko|ka|for)\b", text) or re.search(r"\bto ([A-Z][a-z]+)", text)
    return m.group(1) if m else None


def _item_name(text: str) -> str:
    low = text.lower()
    m = re.search(r"(?:\d+|\b(?:ek|do|teen|char|chaar|paanch|one|two|three|four|five|six|ten))\s+([a-z][a-z ]{1,30}?)\s+(?:ka|ki|ke|for|at|worth|rs|₹|\$|\d)", low)
    if m:
        words = [w for w in m.group(1).split() if w not in _HINDI_WORDS]
        if words:
            return " ".join(words).title()
    return "Items"


def rule_parse(text: str) -> dict:
    low = text.lower()
    lang = "hi" if re.search(r"\b(ka|ko|bhejo|hai|kitna|baaki|aaj|jodo|kya|kaun|shikayat|kar|karo|batao|dilao|bhej)\b", low) else "en"
    base = {"customer": None, "items": [], "product": None, "dispute_id": None, "language": lang, "reply": None}
    if re.search(r"dispute|shikayat|complaint|claim", low):
        return {**base, "intent": "accept_dispute" if re.search(r"accept|refund|maan", low) else "disputes"}
    if re.search(r"remind|reminder|yaad", low):
        return {**base, "intent": "send_reminder", "customer": _known_customer(text)}
    if re.search(r"baaki|unpaid|pending|udhaar|not paid|n't paid|owes|kisne nahi", low):
        return {**base, "intent": "unpaid"}
    if re.search(r"hisaab|briefing|report|sales|kitna aaya|kaisa raha|summary|business", low):
        return {**base, "intent": "briefing"}
    nums = _numbers(text)
    if re.search(r"add|jodo|naya item|catalog|new product", low):
        name = re.sub(r"\d+(?:\.\d+)?|[^\w\s]", " ", low)
        name = re.sub(r"\b(add|jodo|naya item|new product|to catalog|catalog me|catalog mein|price|at|for|rs|to|in|mein|me)\b", " ", name)
        name = " ".join(w for w in name.split() if w not in _HINDI_WORDS and w not in _UNITS and w not in _MULT)
        return {**base, "intent": "add_product",
                "product": {"name": name.title() or "New item", "price": max(nums) if nums else None, "category": None}}
    if re.search(r"invoice|bill|bhejo|charge|bhej", low):
        qty, total = 1.0, None
        if len(nums) >= 2:
            qty, total = min(nums), max(nums)
        elif len(nums) == 1:
            total = nums[0]
        per_unit = bool(re.search(r"\beach\b|\bper\b|har ek|ek ka|wala", low))
        return {**base, "intent": "create_invoice", "customer": _known_customer(text),
                "items": [{"name": _item_name(text), "quantity": qty,
                           "unit_price": total if per_unit else None, "line_total": None if per_unit else total}]}
    reply = ("Namaste! Bolkar bill bhejiye, saaman jodiye, ya aaj ka hisaab poochiye."
             if lang == "hi" else "Hi! Ask me to send a bill, add a product, or tell you today's sales.")
    return {**base, "intent": "chitchat", "reply": reply}


# --------------------------------------------------------------------------
# Vision: recognise a product from a camera frame
# --------------------------------------------------------------------------
def recognise_product(image_b64: str, mime: str = "image/jpeg") -> dict:
    if not config.AI_LIVE:
        return {"name": "Stainless Steel Water Bottle 1L", "category": "Kitchen",
                "description": "Sample recognition (demo mode: add GEMINI_API_KEY for real vision)",
                "search_query": "stainless steel water bottle 1 litre", "estimated_price": 699.0 if config.CURRENCY == "INR" else 8.99,
                "confidence": 0.0, "_engine": "demo sample"}
    if "," in image_b64[:100]:
        image_b64 = image_b64.split(",", 1)[1]
    base64.b64decode(image_b64[:100] + "==", validate=False)
    out = _gemini([{"text": VISION_PROMPT.format(currency=config.CURRENCY)},
                   {"inline_data": {"mime_type": mime, "data": image_b64}}])
    out["_engine"] = "gemini-vision"
    return out


# --------------------------------------------------------------------------
# Disputes
# --------------------------------------------------------------------------
def draft_dispute_reply(facts: dict, lang: str) -> dict:
    lang_name = "Hindi (romanised)" if lang == "hi" else "English"
    if config.AI_LIVE:
        try:
            return _gemini([{"text": DISPUTE_PROMPT.format(facts=json.dumps(facts, indent=1), lang_name=lang_name)}], 0.3)
        except Exception:
            pass
    track = facts.get("tracking") or {}
    if track.get("status") == "DELIVERED":
        reply = (f"Hello {facts.get('buyer', '')}, our records show your order was shipped via {track.get('carrier')} "
                 f"(tracking {track.get('tracking_number')}) and marked delivered on {track.get('delivered_on')}. "
                 "Please check with your neighbours or the post office. We are happy to help further.")
        advice = ("Tracking delivered dikha raha hai, contest karna theek rahega."
                  if lang == "hi" else "Tracking shows delivered, so contesting looks reasonable.")
    else:
        reply = "We are sorry for the trouble. We will issue a full refund."
        advice = "Saboot nahi hai, refund dena behtar hai." if lang == "hi" else "No proof of delivery; accepting is safer."
    return {"reply": reply, "advice": advice}
