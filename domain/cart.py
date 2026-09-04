"""
Cart state. Like catalog.py, no LLM import — a cart is just rows in
SQLite that any caller (agent loop, MCP server, a future admin panel)
can read and write the same way.
"""

import uuid
from datetime import datetime, timezone

from domain.catalog import get_by_id
from domain.db import connect


def init_cart_tables() -> None:
    conn = connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS carts (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cart_items (
            cart_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            qty INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            PRIMARY KEY (cart_id, product_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS discounts (
            cart_id TEXT PRIMARY KEY,
            pct REAL NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def create_cart(session_id: str = "default") -> str:
    cart_id = "CART-" + uuid.uuid4().hex[:8]
    conn = connect()
    conn.execute(
        "INSERT INTO carts (id, session_id, created_at, status) VALUES (?, ?, ?, 'open')",
        (cart_id, session_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return cart_id


def add_item(cart_id: str, product_id: str, qty: int) -> dict:
    """Structured result either way — no bare exception. See §3.7."""
    product = get_by_id(product_id)
    if product is None:
        return {"ok": False, "reason": "product_not_found", "product_id": product_id}

    if product["stock"] < qty:
        return {
            "ok": False,
            "reason": "insufficient_stock",
            "requested": qty,
            "available": product["stock"],
        }

    conn = connect()
    existing = conn.execute(
        "SELECT qty FROM cart_items WHERE cart_id = ? AND product_id = ?",
        (cart_id, product_id),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE cart_items SET qty = qty + ? WHERE cart_id = ? AND product_id = ?",
            (qty, cart_id, product_id),
        )
    else:
        conn.execute(
            "INSERT INTO cart_items (cart_id, product_id, qty, unit_price) VALUES (?, ?, ?, ?)",
            (cart_id, product_id, qty, product["price"]),
        )
    conn.commit()
    conn.close()

    return {"ok": True, "cart": get_cart(cart_id)}


def get_cart(cart_id: str) -> dict:
    conn = connect()
    rows = conn.execute(
        "SELECT product_id, qty, unit_price FROM cart_items WHERE cart_id = ?",
        (cart_id,),
    ).fetchall()
    discount_row = conn.execute(
        "SELECT pct FROM discounts WHERE cart_id = ?", (cart_id,)
    ).fetchone()
    conn.close()

    items = [
        {
            "product_id": r["product_id"],
            "qty": r["qty"],
            "unit_price": r["unit_price"],
            "line_total": r["qty"] * r["unit_price"],
        }
        for r in rows
    ]
    subtotal = sum(i["line_total"] for i in items)
    discount_pct = discount_row["pct"] if discount_row else 0
    total = round(subtotal * (1 - discount_pct / 100))

    return {
        "cart_id": cart_id,
        "items": items,
        "subtotal": subtotal,
        "discount_pct": discount_pct,
        "total": total,
    }


def discount_count(cart_id: str) -> int:
    conn = connect()
    row = conn.execute("SELECT COUNT(*) AS c FROM discounts WHERE cart_id = ?", (cart_id,)).fetchone()
    conn.close()
    return row["c"]


def apply_discount_raw(cart_id: str, pct: float) -> dict:
    """No guardrail check here — that already happened in the registry
    before this was ever called. This function trusts its caller."""
    conn = connect()
    conn.execute(
        "INSERT INTO discounts (cart_id, pct, applied_at) VALUES (?, ?, ?)",
        (cart_id, pct, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "cart": get_cart(cart_id)}
