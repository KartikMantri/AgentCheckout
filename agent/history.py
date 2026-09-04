"""
Trim the middle, never the system prompt (§5.2). Trims by whole turns —
a "turn" is a user message plus everything that followed it up to the
next user message — never mid-turn, because splitting an assistant's
tool_calls from its tool results produces a request the API will
reject outright, not just a confused model.
"""


def _group_into_turns(messages: list[dict]) -> list[list[dict]]:
    turns = []
    current: list[dict] = []
    for m in messages:
        if m["role"] == "user":
            if current:
                turns.append(current)
            current = [m]
        else:
            current.append(m)
    if current:
        turns.append(current)
    return turns


def trim_history(messages: list[dict], max_turns: int) -> list[dict]:
    if not messages or messages[0]["role"] != "system":
        return messages

    system = messages[0]
    turns = _group_into_turns(messages[1:])

    if len(turns) <= max_turns:
        return messages

    kept = turns[-max_turns:]
    trimmed = [system]
    for turn in kept:
        trimmed.extend(turn)
    return trimmed
