from dataclasses import dataclass, field


@dataclass
class Verdict:
    """What every guardrail returns. Never a bare exception — the agent
    needs a readable reason to explain itself to the user."""
    allowed: bool
    reason: str = "ok"
    escalation_required: bool = False
    detail: dict = field(default_factory=dict)
