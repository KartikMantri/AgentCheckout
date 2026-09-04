"""
OpenAI tool-call format schemas. This is the *only* description of the
catalog the model ever receives — it never sees the database directly.
Every schema here is re-sent on every single request, so keep descriptions
terse: this is tokens, spent repeatedly, not documentation.
"""

SEARCH_CATALOG = {
    "type": "function",
    "function": {
        "name": "search_catalog",
        "description": "Search the live running-shoe catalog. Returns in-stock items only, ranked by price.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text search terms, e.g. product name or category.",
                },
                "max_price": {
                    "type": "integer",
                    "description": "Maximum price in rupees. Omit if no budget was stated.",
                },
                "attributes": {
                    "type": "object",
                    "description": "Exact-match filters. Known keys: arch_support (flat/neutral/high), use_case (daily/racing/trail/half-marathon/marathon), width (narrow/regular/wide), terrain (road/trail).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return. Defaults to 5.",
                },
            },
            "required": ["query"],
        },
    },
}

ADD_TO_CART = {
    "type": "function",
    "function": {
        "name": "add_to_cart",
        "description": "Add a product to the customer's cart. The cart is tracked automatically — never ask the customer for a cart id.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product's id, e.g. SKU-101. Must come from a prior search_catalog result.",
                },
                "qty": {
                    "type": "integer",
                    "description": "Quantity to add. Defaults to 1 if not stated.",
                },
            },
            "required": ["product_id", "qty"],
        },
    },
}

REMOVE_FROM_CART = {
    "type": "function",
    "function": {
        "name": "remove_from_cart",
        "description": "Remove a product entirely from the customer's cart, regardless of quantity.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product's id to remove, e.g. SKU-101.",
                },
            },
            "required": ["product_id"],
        },
    },
}

CLEAR_CART = {
    "type": "function",
    "function": {
        "name": "clear_cart",
        "description": "Empty the customer's entire cart, removing every item and any applied discount. Use when the customer wants to start over.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

APPLY_DISCOUNT = {
    "type": "function",
    "function": {
        "name": "apply_discount",
        "description": "Apply a percentage discount to the customer's cart. Discounts above the auto-approval cap are rejected and must be escalated — never argue the cap, call escalate_to_human instead.",
        "parameters": {
            "type": "object",
            "properties": {
                "pct": {
                    "type": "number",
                    "description": "Discount percentage, e.g. 10 for 10%.",
                },
            },
            "required": ["pct"],
        },
    },
}

CREATE_ORDER = {
    "type": "function",
    "function": {
        "name": "create_order",
        "description": "Freeze the customer's current cart into an order with an immutable total. Call this once the customer confirms they're ready to check out — the total cannot change after this.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

CAPTURE_PAYMENT = {
    "type": "function",
    "function": {
        "name": "capture_payment",
        "description": "Capture payment for a created order via Razorpay test mode. Safe to call again for an order that's already paid — it will not charge twice.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order id returned by create_order."},
            },
            "required": ["order_id"],
        },
    },
}

ASK_CLARIFICATION = {
    "type": "function",
    "function": {
        "name": "ask_clarification",
        "description": "Ask the customer a clarifying question when the request is genuinely ambiguous, instead of guessing.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask the customer."},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional short list of choices to offer.",
                },
            },
            "required": ["question"],
        },
    },
}

CHECK_ORDER_STATUS = {
    "type": "function",
    "function": {
        "name": "check_order_status",
        "description": "Check whether a pending or created order has been reviewed yet. Use this when the customer asks for an update on an order you previously gave them an id for (a create_order rejection's pending_order_id, or create_order's own order id).",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order id to check, e.g. PENDING-xxxx or ORDER-xxxx."},
            },
            "required": ["order_id"],
        },
    },
}

ESCALATE_TO_HUMAN = {
    "type": "function",
    "function": {
        "name": "escalate_to_human",
        "description": "Hand this request to a human when it exceeds what you're allowed to approve automatically, or is out of bounds regardless of how it's phrased.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why this needs a human."},
                "context": {"type": "object", "description": "Relevant details, e.g. the requested discount and the cap."},
            },
            "required": ["reason"],
        },
    },
}
