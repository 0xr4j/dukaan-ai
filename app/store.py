"""Tiny SQLite ledger: products, customers, invoices and an activity log."""
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, category TEXT, price REAL, currency TEXT,
  paypal_product_id TEXT, price_source TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE, email TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paypal_invoice_id TEXT, customer TEXT, email TEXT, items TEXT,
  total REAL, currency TEXT, status TEXT, pay_url TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, heard TEXT, action TEXT, paypal_tool TEXT, result TEXT, mode TEXT
);
"""

SEED_CUSTOMERS = [
    ("Sharma ji", "sharma.ji@example.com"),
    ("Priya", "priya.customer@example.com"),
    ("Mehta Traders", "accounts@mehta-traders.example.com"),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.executescript(SCHEMA)
        for name, email in SEED_CUSTOMERS:
            c.execute("INSERT OR IGNORE INTO customers(name,email) VALUES(?,?)", (name, email))


def rows(table: str) -> list[dict]:
    assert table in {"products", "customers", "invoices", "activity"}
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY id DESC")]


def insert(table: str, **values) -> int:
    assert table in {"products", "customers", "invoices", "activity"}
    keys = ",".join(values)
    marks = ",".join("?" for _ in values)
    with _lock, _conn() as c:
        cur = c.execute(f"INSERT INTO {table}({keys}) VALUES({marks})", tuple(values.values()))
        return cur.lastrowid


def update_invoice_status(paypal_invoice_id: str, status: str) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE invoices SET status=? WHERE paypal_invoice_id=?", (status, paypal_invoice_id))


def log(heard: str, action: str, paypal_tool: str, result, mode: str) -> None:
    insert("activity", ts=now(), heard=heard, action=action, paypal_tool=paypal_tool,
           result=json.dumps(result, default=str)[:4000], mode=mode)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower().replace(" ji", ""))


def find_or_create_customer(name: str, email: str | None = None) -> dict:
    """Match a spoken customer name to the shop's customer book."""
    name = (name or "Walk-in customer").strip()
    target = _norm(name)
    for cust in rows("customers"):
        n = _norm(cust["name"])
        if n and (n == target or n in target or target in n):
            return cust
    email = email or f"{_norm(name) or 'customer'}@customers.example.com"
    insert("customers", name=name, email=email)
    return {"name": name, "email": email}
