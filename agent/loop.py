"""
The agent loop. Not "call model, run tool, print result" (§2.5) — a
tool's result goes back into the conversation as a message, and the
model is called again with that new information.

tools.registry.dispatch() owns validation, guardrails, and execution
end to end. Session state (agent.session) persists conversation and
cart across calls. Every dispatched tool call gets one audit log line
(audit.logger) — this is the project's evidence, not a debugging aid.
"""

import json

import config
from agent.history import trim_history
from agent.router import RouterExhausted
from agent.router import call as router_call
from audit.logger import log_event
from tools.registry import ALL_SCHEMAS, dispatch, is_terminal


def run(user_message: str, session_id: str = "default", verbose: bool = True) -> tuple[str, str]:
    from agent.session import get_session  # local import avoids a circular import with agent.session

    session = get_session(session_id)
    messages = session["messages"]
    cart_id = session["cart_id"]

    messages.append({"role": "user", "content": user_message})

    def log(**kw):
        if verbose:
            print(f"  [router] {kw}")

    validation_failures = 0

    for iteration in range(1, config.MAX_LOOP_ITERATIONS + 1):
        session["messages"] = trim_history(messages, config.MAX_HISTORY_TURNS)
        messages = session["messages"]

        task_type = "judgment" if validation_failures > 0 else "extraction"
        try:
            message, provider, meta = router_call(task_type, messages, tools=ALL_SCHEMAS, log=log)
        except RouterExhausted as exc:
            log_event(
                session_id=session_id, actor="agent", iteration=iteration,
                tool="_router", args_json="{}",
                verdict_json={"allowed": False, "reason": "router_exhausted", "escalation_required": True},
                outcome_json=json.dumps({"error": str(exc)}),
                provider=None, model=None, is_failover=None, tokens=None, latency_ms=None,
            )
            reply = "All configured AI providers are currently unavailable — escalating to a human rather than guessing."
            messages.append({"role": "assistant", "content": reply})
            return reply, cart_id

        if not message.tool_calls:
            if verbose:
                print(f"[iteration {iteration}] served by {provider} — final answer, no further tool calls")
            messages.append({"role": "assistant", "content": message.content})
            return message.content, cart_id

        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [tc.model_dump() for tc in message.tool_calls],
        })

        for tc in message.tool_calls:
            result = dispatch(tc.function.name, tc.function.arguments, cart_id)
            verdict = _verdict_from_result(result)

            log_event(
                session_id=session_id,
                actor="agent",
                iteration=iteration,
                tool=tc.function.name,
                args_json=tc.function.arguments,
                verdict_json=verdict,
                outcome_json=json.dumps(result),
                provider=meta["provider"],
                model=meta["model"],
                is_failover=meta["is_failover"],
                tokens=meta["total_tokens"],
                latency_ms=meta["latency_ms"],
            )

            if isinstance(result, dict) and result.get("ok") is False and result.get("reason") in ("invalid_arguments", "malformed_json"):
                validation_failures += 1
                if verbose:
                    print(f"[iteration {iteration}] VALIDATION FAILED ({validation_failures}/{config.MAX_VALIDATION_RETRIES}): "
                          f"{tc.function.name}({tc.function.arguments}) -> {result['detail']}")
                if validation_failures > config.MAX_VALIDATION_RETRIES:
                    reply = "I'm having trouble formatting that request correctly — escalating to a human to take over from here."
                    messages.append({"role": "assistant", "content": reply})
                    return reply, cart_id

            elif isinstance(result, dict) and result.get("ok") is False:
                if verbose:
                    print(f"[iteration {iteration}] GUARDRAIL REJECTED: {tc.function.name}({tc.function.arguments}) "
                          f"-> reason={result.get('reason')} escalate={result.get('escalation_required')} "
                          f"detail={result.get('detail')}")

            elif verbose:
                print(f"[iteration {iteration}] served by {provider} — tool call: "
                      f"{tc.function.name}({json.loads(tc.function.arguments)})")
                print(f"[iteration {iteration}] tool result: {result}")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

            if is_terminal(tc.function.name) and isinstance(result, dict) and result.get("ok"):
                if verbose:
                    print(f"[iteration {iteration}] terminal action: {tc.function.name}")
                reply = _terminal_message(tc.function.name, result)
                messages.append({"role": "assistant", "content": reply})
                return reply, cart_id

    reply = "I wasn't able to finish that within my iteration limit — could you narrow the request?"
    messages.append({"role": "assistant", "content": reply})
    return reply, cart_id


def _verdict_from_result(result) -> dict:
    """Not every tool has a formal guardrail (search_catalog doesn't),
    but every dispatch has *some* outcome worth recording as a verdict
    shape — this normalizes that for the audit row."""
    if isinstance(result, dict) and result.get("ok") is False:
        return {
            "allowed": False,
            "reason": result.get("reason"),
            "escalation_required": result.get("escalation_required", False),
        }
    return {"allowed": True, "reason": "ok", "escalation_required": False}


def _terminal_message(tool_name: str, result: dict) -> str:
    if tool_name == "ask_clarification":
        return result.get("question", "Could you clarify what you'd like?")
    if tool_name == "escalate_to_human":
        return f"I've escalated this to a human — reason: {result.get('reason')}"
    return "Handled."
