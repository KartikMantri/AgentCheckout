"""
Pydantic schemas — the actual enforced contract behind each OpenAI tool
schema in definitions.py. The JSON schema we send the model is a
description; this is what we hold it to.
"""

from pydantic import BaseModel, Field, ValidationError

SCHEMA_ERRORS = ValidationError  # re-exported for callers that need to catch it


class SearchCatalogArgs(BaseModel):
    query: str
    max_price: int | None = None
    attributes: dict | None = None
    limit: int = 5


class AddToCartArgs(BaseModel):
    product_id: str
    qty: int = Field(gt=0)


class ApplyDiscountArgs(BaseModel):
    pct: float = Field(gt=0, le=100)


class CreateOrderArgs(BaseModel):
    pass


class CapturePaymentArgs(BaseModel):
    order_id: str


class AskClarificationArgs(BaseModel):
    question: str
    options: list[str] | None = None


class EscalateToHumanArgs(BaseModel):
    reason: str
    context: dict | None = None


SCHEMAS = {
    "search_catalog": SearchCatalogArgs,
    "add_to_cart": AddToCartArgs,
    "apply_discount": ApplyDiscountArgs,
    "create_order": CreateOrderArgs,
    "capture_payment": CapturePaymentArgs,
    "ask_clarification": AskClarificationArgs,
    "escalate_to_human": EscalateToHumanArgs,
}


def validate_args(tool_name: str, raw_args: dict) -> tuple[dict | None, str | None]:
    """(parsed_args, None) on success, or (None, human-readable error) on failure."""
    schema = SCHEMAS.get(tool_name)
    if schema is None:
        return None, f"unknown tool: {tool_name!r}"

    try:
        parsed = schema(**raw_args)
    except ValidationError as exc:
        messages = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return None, "; ".join(messages)

    return parsed.model_dump(), None
