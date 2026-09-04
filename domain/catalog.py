"""
The catalog, and nothing else. No LLM import anywhere in this file —
if that ever changes, the domain layer has stopped being a plain API
and the trust boundary is no longer real.
"""

import json
from pathlib import Path

from domain.db import connect as _connect

SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "seed_catalog.json"


def init_db(force_reseed: bool = False) -> None:
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            stock INTEGER NOT NULL,
            category TEXT NOT NULL,
            attributes_json TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    if force_reseed:
        conn.execute("DELETE FROM products")

    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if count == 0:
        with open(SEED_PATH, encoding="utf-8") as f:
            catalog = json.load(f)
        conn.executemany(
            "INSERT OR REPLACE INTO products (id, name, price, stock, category, attributes_json, active) "
            "VALUES (:id, :name, :price, :stock, :category, :attributes_json, 1)",
            [
                {**p, "attributes_json": json.dumps(p["attributes"])}
                for p in catalog
            ],
        )
        conn.commit()

    conn.close()


def search(query: str = "", max_price: int | None = None, attributes: dict | None = None, limit: int = 5) -> list[dict]:
    """Ranked, in-stock-only results. Never returns a product with stock <= 0 (FR3)."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM products WHERE active = 1 AND stock > 0").fetchall()
    conn.close()

    query_terms = query.lower().split() if query else []
    results = []

    for row in rows:
        attrs = json.loads(row["attributes_json"])

        if max_price is not None and row["price"] > max_price:
            continue

        if attributes:
            mismatch = any(
                str(attrs.get(key, "")).lower() != str(value).lower()
                for key, value in attributes.items()
            )
            if mismatch:
                continue

        haystack = f"{row['name']} {row['category']} {' '.join(str(v) for v in attrs.values())}".lower()
        if query_terms and not all(term in haystack for term in query_terms):
            continue

        results.append({
            "id": row["id"],
            "name": row["name"],
            "price": row["price"],
            "stock": row["stock"],
            "category": row["category"],
            "attributes": attrs,
        })

    results.sort(key=lambda r: r["price"])
    return results[:limit]


def list_all() -> list[dict]:
    """Every active product, in or out of stock — for the storefront's
    browse view. Deliberately separate from search(): a human browsing
    a merchant's site legitimately sees a 'sold out' item; the agent's
    search_catalog tool never does (FR3). Same underlying truth, two
    honest views of it."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM products WHERE active = 1 ORDER BY price ASC").fetchall()
    conn.close()
    return [
        {
            "id": r["id"], "name": r["name"], "price": r["price"], "stock": r["stock"],
            "category": r["category"], "attributes": json.loads(r["attributes_json"]),
        }
        for r in rows
    ]


def get_by_id(product_id: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM products WHERE id = ? AND active = 1", (product_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "price": row["price"],
        "stock": row["stock"],
        "category": row["category"],
        "attributes": json.loads(row["attributes_json"]),
    }


def decrement_stock(product_id: str, qty: int) -> None:
    """Called on a confirmed payment capture, not on add-to-cart — an
    item sits reserved-in-appearance-only while just in a cart; stock
    only actually moves once money has moved."""
    conn = _connect()
    conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (qty, product_id))
    conn.commit()
    conn.close()
