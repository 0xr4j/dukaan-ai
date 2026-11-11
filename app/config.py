"""Runtime configuration, loaded from environment variables / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


PAYPAL_CLIENT_ID = _get("PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = _get("PAYPAL_CLIENT_SECRET")
GEMINI_API_KEY = _get("GEMINI_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.5-flash")
CHANNEL3_API_KEY = _get("CHANNEL3_API_KEY")

SHOP_NAME = _get("SHOP_NAME", "Raj General Store")
SHOP_EMAIL = _get("SHOP_EMAIL")  # optional: your sandbox business account email

# Force demo mode even if keys exist (useful for judges / offline video takes)
FORCE_DEMO = _get("DEMO_MODE").lower() in {"1", "true", "yes"}

DATA_DIR = Path(_get("DATA_DIR", str(ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "dukaan.db"

PAYPAL_LIVE = bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET) and not FORCE_DEMO
AI_LIVE = bool(GEMINI_API_KEY) and not FORCE_DEMO
CHANNEL3_LIVE = bool(CHANNEL3_API_KEY) and not FORCE_DEMO

# Demo defaults to rupees; with real sandbox keys default to USD (works on any sandbox business account)
CURRENCY = _get("CURRENCY", "USD" if PAYPAL_LIVE else "INR").upper()

CURRENCY_SYMBOL = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}.get(CURRENCY, CURRENCY + " ")


def modes() -> dict:
    return {
        "paypal": "SANDBOX" if PAYPAL_LIVE else "DEMO",
        "ai": "LIVE" if AI_LIVE else "DEMO",
        "channel3": "LIVE" if CHANNEL3_LIVE else "DEMO",
        "currency": CURRENCY,
        "symbol": CURRENCY_SYMBOL,
        "shop": SHOP_NAME,
    }
