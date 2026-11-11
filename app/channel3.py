"""Price grounding with Channel3 product search (100M+ products, 25k+ retailers)."""
import statistics

import httpx

from . import config

URL = "https://api.trychannel3.com/v1/search"


def market_prices(query: str, limit: int = 8) -> dict:
    """Return comparable listings and a suggested price for `query`.

    Falls back to {"mode": "DEMO"} with no comparables when no key is configured;
    the caller then uses the AI's own estimate and labels it as such.
    """
    if not config.CHANNEL3_LIVE or not query:
        return {"mode": "DEMO", "comparables": [], "suggested": None}
    try:
        r = httpx.post(URL, headers={"x-api-key": config.CHANNEL3_API_KEY, "x-user-id": "dukaan-ai-shop"},
                       json={"query": query, "limit": limit}, timeout=15)
        r.raise_for_status()
        comps = []
        for p in r.json().get("products", []):
            offer = next((o for o in p.get("offers", []) if (o.get("price") or {}).get("price")), None)
            if not offer:
                continue
            img = next((i.get("cleaned_url") or i.get("url") for i in p.get("images", []) if i.get("is_main_image")), None)
            comps.append({"title": p.get("title"), "price": float(offer["price"]["price"]),
                          "currency": offer["price"].get("currency", "USD"),
                          "store": offer.get("domain"), "url": offer.get("url"), "image": img})
        same_ccy = [c["price"] for c in comps if c["currency"] == config.CURRENCY]
        suggested = round(statistics.median(same_ccy), 2) if same_ccy else None
        return {"mode": "LIVE", "comparables": comps[:5], "suggested": suggested}
    except Exception as e:  # never break the shop flow because of price lookup
        return {"mode": "ERROR", "error": str(e)[:200], "comparables": [], "suggested": None}
