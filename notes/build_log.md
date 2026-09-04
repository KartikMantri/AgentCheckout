# Build log

Running notes on real findings during the build — feeds `metrics.md` and the
pitch video's honesty about failure modes. Not a step-by-step diary, just
things worth remembering that aren't obvious from the code.

## Step 3 — tool overreach on an irrelevant query

`groq/openai/gpt-oss-20b` called `search_catalog` even when asked
"what's the weather like today?" — a question the tool has no way to
answer. It didn't decline or answer directly; it reached for the only
tool available anyway.

**Why this matters:** confirms the PRD's prediction that smaller
open-weight models over-trigger tool calls rather than recognizing a
tool is irrelevant. This is exactly the gap `ask_clarification` (FR11)
and, eventually, prompt/validation discipline are meant to close — an
instruction like "only call a tool when relevant" would be argued with
or ignored; giving the model *nothing else it can do* when uncertain
is what actually holds.

**Where to use this:** candidate line for the README's honest
limitations section, and a data point for whichever provider ends up
serving `routing` in the final router chain — if Gemini shows the same
behavior under M7-style testing, note it; if it doesn't, that's a real
quality difference worth naming instead of asserting model parity
where it doesn't hold.

## Step 5 — tool-call format was NOT a problem (contrary to PRD expectation)

The PRD's §2.3b flags provider tool-call normalization as "expect one
bug here, budget ~1hr." Tested it directly: forced Groq's key to fail
mid-conversation and ran the full two-tool loop (search_catalog ->
add_to_cart) entirely on Gemini (`gemini-3.7-flash`) via the OpenAI
compat endpoint. `message.tool_calls[i].function.name/.arguments/.id`
came back in the identical shape Groq uses — `agent/router.py`'s
`ProviderClient.chat()` needed zero provider-specific branching.

**Why this is worth keeping, not just discarding as "no bug found":**
it's a genuine, testable claim for the pitch — "we tested the
failure mode the architecture doc predicted, and the abstraction held
without a patch." Better evidence than assuming it would work.
Re-verify this again once Gemini is wired as `judgment`'s primary
(Step 11) and under M7's adversarial set — a good-faith request and an
adversarial one can stress tool-call parsing differently.

## Step 6 — retry-with-feedback recovers, but not in one hop

Injected a malformed `add_to_cart` call (`qty: "one"` instead of `1`,
a documented failure mode — models sometimes emit a word instead of
a number). Validation caught it cleanly: structured rejection, no
exception, no DB write. Fed the error back as a tool result.

The model did **not** immediately retry `add_to_cart` with a fixed
`qty`. It re-verified the product via `search_catalog` first, *then*
retried `add_to_cart` correctly on the next turn. Full recovery took
3 turns, not 1.

**Why this matters for GR7/GR8 tuning:** GR8 caps *validation*
retries at 2, separate from GR7's iteration cap of 8 — this run used
1 validation failure but 3 total iterations to fully recover, because
the model's recovery strategy included an extra verification step we
didn't ask for. If GR7's iteration cap were set lower (e.g. 4-5) for
some reason, this exact recovery could plausibly get cut off before
completing even with retries "available." Keep the 8-iteration cap
comfortably above what recovery actually costs in practice, not just
above the happy-path turn count.

## Step 8 — rate-limit backoff path is real but untested live

`agent/router.py` catches `openai.RateLimitError` specifically, waits
1.5s, and retries once on the same provider before treating it as a
failover — the §5.2 "backoff before failover" mitigation. Never
actually triggered in this build: Groq's real free-tier limit turned
out to be 250K TPM / 1K RPM (see the Day 0 note), far above what a
handful of manual test conversations burn. The code path is correct
by inspection but has zero live evidence behind it.

**Before claiming M8 (failover survival) in metrics.md:** either
force a real rate limit (many rapid calls in a tight loop) or be
explicit that M8's evidence is the forced-auth-failure test from
Step 5, not an organic rate-limit — those are different failure
modes and the pitch shouldn't blur them together.

## Step 8 — a quiet trust gap worth naming out loud

In the 3-turn memory test, turn 3 ("what's in my cart") was answered
from conversation memory, not a fresh `get_cart` call — the model
recalled the `add_to_cart` result from two turns earlier instead of
re-querying. Correct here because nothing else touched the cart in
between, but there's no guardrail that catches a *stale* cart read
the way GR4 catches a *stale* stock write. Only money-moving actions
are guarded, not memory-based claims about current state. Worth a
one-line honest caveat in the README's limitations section rather
than presenting cart-state answers as always freshly verified.

## Step 9 — real bug: stock never decremented after a real sale

`add_to_cart` only ever *checked* stock (GR4), it never reduced it —
no code path anywhere decremented `products.stock` after a purchase.
Caught while checking the idempotency test's output: the SKU stayed
at its original stock count even after a full conversational purchase
had captured payment against it. Left alone, this would have meant
the same "last unit" could be sold indefinitely — a direct violation
of FR3 ("out-of-stock items are never returned as purchasable") once
any real sale had happened.

**Fix:** `domain/catalog.decrement_stock()`, called from
`domain.orders.capture_payment_raw()` — deliberately on confirmed
*payment*, not on add-to-cart or create_order. Reasoning: an item in
someone's cart or even a created-but-unpaid order isn't a completed
sale, and reserving stock for an abandoned cart with no expiry
mechanism would create a different, worse bug (phantom out-of-stock
on items nobody actually bought). Verified: stock drops by exactly
the purchased qty on the real capture, and does NOT move again on the
idempotent replay.

**Why this is worth naming in the submission, not just fixing quietly:**
it's a genuine "found via testing the failure demo path, not via a
code read" catch — the kind of thing M1's honest reporting is meant
to surface. Also a good second candidate for Step 13's failure demo
("item goes out of stock mid-conversation") now that it's real:
buy the last unit of a low-stock SKU (SKU-115, stock=1) and show a
second search on the same SKU returning nothing.

## Step 11 — the real M7/M8 failure, and a wrong first guess corrected

The first M7/M8 batch (scripts/step11_invariance.py) came back with
Gemini-forced scenarios returning `answer=None` and M8 (Groq down)
failing 0/12 — including the very first scenario. My first hypothesis
was the in-process cumulative token budget tracker (agent/budget.py)
hitting its 80%-of-100K placeholder threshold mid-batch. **That guess
was wrong, and reproducing it in isolation proved it:**

```
RateLimitError: 429 RESOURCE_EXHAUSTED
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
quotaValue: 20  (model: gemini-3.7-flash)
```

`gemini-3.7-flash`'s free tier allows **20 requests per day, total** —
not per minute. Every test since Step 4 that touched Gemini (Step 5's
failover demo, Step 8/9's occasional fallback, and this batch hammering
it directly) drew from the same 20/day pool, and it's now genuinely
exhausted for the rest of today. This is an external, real constraint,
not a bug — but it exposed two real bugs in how the system responds to
it:

1. **The pre-emptive budget skip could eliminate the LAST provider in
   a chain**, turning a recoverable situation (try it, get a real 429)
   into a guaranteed `RouterExhausted` before even attempting the call.
   Fixed: `agent/router.py` now never pre-emptively skips the final
   remaining provider in a chain — only earlier ones, when there's
   still a fallback left to skip *to*.
2. **`RouterExhausted` was unhandled in `agent/loop.py`** — it
   propagated straight out of `run()`, which is fine for a script with
   a try/except around it (that's how `tests/scenarios.py` survived),
   but would have crashed a live chat request or an MCP tool call
   outright. Fixed: the loop now catches it, logs a `router_exhausted`
   audit event, and returns a graceful escalation message instead.

**Also changed:** `judgment`'s primary provider swapped from Gemini
back to Groq (`config.CHAINS`). The PRD's own reasoning for
Gemini-as-judgment-primary (§2.3b — spend the strongest model exactly
where uncertainty-detection matters) is sound in principle, but it
assumes a provider that can actually serve repeated calls. A 20/day
cap cannot be any task's primary in practice, live demo or otherwise.
Gemini remains in every chain as a real fallback — the multi-vendor
story is intact, just not with Gemini load-bearing.

## Step 12 — MCP server: external agent completed a full purchase, unscripted

`scripts/step12_mcp_client_agent.py` contains zero imports from
`tools/`, `guardrails/`, or `domain/` — it only knows the store
through `session.list_tools()` over the wire. It completed a full
search -> add -> create_order -> capture_payment flow from one
natural-language prompt, and along the way self-corrected: its first
`search_catalog` call (narrow query + max_price + attributes together)
returned zero results, and without being told to, it broadened the
query on the next turn and found the item. Also proved
`apply_discount(pct=40)` gets the identical `discount_exceeds_cap`
rejection over MCP as through the internal loop — no guardrail code
was written twice.

Forced onto Groq rather than Gemini for this run, since Gemini's daily
quota was already spent from Step 11 — worth re-running with Gemini
once quota resets, both for a truer "different vendor" demo and
because a fresh, less battle-tested model might expose different
tool-call quirks worth knowing about before the actual submission.

## Step 13 — failure demo: better recovery than scripted

`scripts/step13_failure_demo.py` depletes SKU-112 to 0 stock across
two real purchases, then a third customer asks for the same shoe.
Rather than a blunt rejection, the actual chain was: search_catalog
correctly returned `[]` (FR3's exclusion working, not a special case),
the model searched more broadly on its own initiative, found the
closest in-stock relative (same product, regular width instead of
wide), and called `ask_clarification` to offer it rather than silently
substituting or guessing. Best failure-demo candidate found so far —
recommend this over a flat insufficient_stock rejection for the pitch
video's failure-case segment.

## Post-submission — real Razorpay wired in, and a self-inflicted SSL outage

Added real Razorpay test-mode credentials. `create_order` immediately
hit `requests.exceptions.SSLError: certificate verify failed: unable
to get local issuer certificate` against api.razorpay.com — and the
same failure on plain github.com, while Groq/Gemini calls (via
`httpx`, not `requests`) worked fine throughout. Local Windows
trust-chain issue: some root CA (likely antivirus/network-tooling TLS
inspection) is trusted by Windows but not by any certifi-style bundle
— confirmed by the fact that even Razorpay's own bundled
`ca-bundle.crt` still failed.

**First fix attempt made things worse, briefly:** installed
`pip-system-certs`, which activates via a `.pth` hook — runs
automatically on Python startup, no import needed — and globally
monkey-patches `ssl.SSLContext`. On this Windows/Python 3.12 setup
that patch was recursively broken (`RecursionError`) and broke *every*
SSL connection in the process, including Groq/Gemini, which had been
working fine all session. Reverted immediately: removed the import,
uninstalled the package. That also removed `truststore`, which turned
out to be a legitimate existing dependency of the `openai` package's
vendored `httpcore2` (the actual reason Groq/Gemini worked at all,
this whole time) — had to reinstall plain `truststore` to restore that.

**The actual fix**, scoped correctly this time: a custom `requests`
`HTTPAdapter` using `truststore.SSLContext()`, mounted on a `Session`
passed only into the `razorpay.Client(session=...)` constructor —
`domain/payments.py`'s `_client()`. Zero global `ssl` patching. Tested
working end to end: real order created via `create_order_raw()` with
zero LLM involvement (`order_TVKdeWd0od8qmv`), and confirmed Groq/
Gemini still work identically afterward.

**Lesson worth keeping**: a library patching `ssl` globally (anything
promising "fixes all your SSL problems" via a `.pth` auto-activating
hook) is a much bigger blast radius than it looks — it silently
affects every other HTTP client in the same process, including ones
that were already working correctly. Scope the fix to exactly the one
broken client instead.

## Post-submission — both LLM providers hit real daily quota limits, live

Immediately after the SSL fix, a live agent test (`create_order`
mid-conversation) failed with the graceful "all providers unavailable"
message. Root cause, confirmed via a verbose rerun: **Groq hit its
real 200,000 TPD (tokens-per-day) cap** — 199,872 used, from this
session's cumulative testing — and **Gemini's 20-requests/day cap**
(first hit back in Step 11) was still exhausted. Both providers
genuinely unavailable, not a bug.

Worth noting as a positive, not just a failure: this is the Step 11
resilience fix (RouterExhausted degrading gracefully instead of
crashing) firing correctly, live, completely unplanned, under real
exhaustion conditions — the exact scenario it was built for. Groq's
error included a ~10 minute retry estimate (its TPD limit appears to
be a rolling window, not a hard midnight reset), so this should clear
on its own; Gemini's 20/day cap likely needs a real day boundary.

**Practical implication for anyone continuing this build**: this
project has now run enough cumulative testing across one extended
session to exhaust a real production-tier daily quota on Groq's free
plan. Budget for that during a live demo — don't run the full
scenario batch or heavy MCP testing again right before recording.

## Step 14 — metrics.md was double-counting reruns

`audit/report.py` filtered events by session_id but not by time —
rerunning it without deleting `audit_log.jsonl` (which is append-only
by design and never should be deleted) silently double-counted a
prior run's events under the same scenario session ids: M2's
rejection count went 4 -> 8 on a second run with no actual change in
behavior. Fixed by scoping `compute_metrics()` to events at-or-after
the run's own start timestamp — the log file keeps its full history,
but each report only counts what actually happened in that run.
**Re-run `audit/report.py` fresh before trusting any number in
metrics.md if it's been run more than once without checking this.**

**Consequence for M7/M8 specifically:** cannot be re-verified live
today — Gemini's daily quota is spent. Options for next time: (a) wait
for the daily reset and re-run `scripts/step11_invariance.py` with a
much lighter batch (1-2 adversarial scenarios, not all 12, to avoid
repeating this), or (b) get a second Gemini API key on a different
Google account/project. Either way, **do not claim M7/M8 numbers in
the final submission until this batch has actually completed clean**
— the first run's numbers were a real outage, not a measurement.

## Post-submission — no way to remove a cart item, found via real use

Live use of the web console surfaced a real gap: 7 tools covered
adding to cart, but nothing let a customer undo it. Asked to "remove
the first two items," the agent correctly didn't hallucinate a fake
removal — it had no tool for it — but the conversation spiralled into
confused clarification loops trying to work around the gap (offering
"clear the cart and re-add" as a manual workaround), which read as the
agent being stuck rather than honest about a missing capability.

Added two tools: `remove_from_cart` (product_id) and `clear_cart`
(no args) — both agent-callable, no guardrail needed (removing items
isn't a business-limit concern), both tested live and confirmed
against actual database state, not just the model's claim. Now 9
tools, not 7 — the PRD's "7, not 15" restraint was about token cost
per schema, not a hard ceiling; a genuinely missing capability is a
real product gap, not scope creep to fix.

**Worth remembering for the demo**: this was found through actual
conversational use, not a scripted test — a good argument for doing a
real, unscripted rehearsal pass before recording, since scripted
scenarios (tests/scenarios.py) will never surface a gap like "there's
no tool for the thing I just tried to ask for."

## Post-submission — discount flow was ambiguous, and escalation too terse

Live use surfaced two related UX problems around `apply_discount`,
neither a guardrail bug — the enforcement was correct throughout:

1. Asked to "apply a discount" with no percentage stated, the agent
   asked the customer to name one, forcing them to guess at an unstated
   limit rather than just offering the store's actual flat rate.
2. When a request came in over the cap (15% vs the 10% max), the first
   reply was just "I've escalated this to a human — reason: ..." with
   no explanation of the cap or what to do next. The model recovered
   well on a follow-up "what?", explaining clearly — but only on
   request, not proactively.

**Fix, in `agent/prompts.py` only — no guardrail or config change,
because none was needed; the 10% cap already IS the store's promo
rate:** the system prompt now tells the model the flat-10%-off framing
(informational/marketing, not a limit statement — the actual cap still
lives solely in `guardrails/rules.py` + `config.py` and doesn't care
what the prompt says) and explicitly requires it to state the cap and
offer a concrete alternative in the SAME message as any discount
rejection, never a bare "escalated" with no explanation.

Verified live: an unspecified "apply a discount" now auto-applies 10%
directly; a 15% request now gets one clear message stating the 10%
cap and offering either 10% now or human escalation for more — no
"what?" follow-up needed.

Also added a bold promo callout to the storefront hero ("Flat 10% off
... just ask") so the number is visible before the conversation even
starts, not something the customer has to extract from the agent.

## Post-submission — order-value cap was blocking humans, not just AI

A large cart (₹11,098, over the ₹5,000 cap) hit "escalate to a human"
even when the person looking at their own cart, on their own screen,
clicked Checkout themselves — not something an AI decided on its own.
Fair pushback: why would a human confirming their own purchase need
approval from *another* human?

The real answer: GR2 exists to stop an AI from autonomously
committing to a large spend it decided on its own mid-conversation.
It was never meant to gate a human's own explicit, informed decision
— but the code didn't distinguish the two callers, so both hit the
identical check.

**Fix:** a second, separate path — `/api/cart/{id}/confirm-checkout`
in web/app.py — reachable ONLY by a direct UI button click after the
storefront shows the human the real total and a real confirmation
screen. It calls `create_order_raw()` directly, bypassing the
guardrail-wrapped `tools.registry.dispatch()` entirely. The
chat/MCP/Claude-Desktop path is completely unchanged — an AI still
cannot talk its way past GR2 no matter how the request is phrased;
verified live, side by side, in the same session: the agent still
correctly refused the same ₹11,098 cart, and the direct endpoint
created a real Razorpay order for it seconds later.

**Why this isn't a guardrail bypass, and the line that matters:** the
new path is unreachable from any LLM output — no prompt, no tool
schema, no natural-language phrasing leads to it. It only exists
behind a literal browser click on a button that shows the real number.
That click already IS the human-in-the-loop GR2 was trying to
guarantee — recognizing that isn't weakening the guardrail, it's
applying it to the actual thing it was meant to catch. Payment capture
is unaffected either way: creating an order never moves money: real
credentials still have to go through the Razorpay widget regardless
of which path created the order.

Audit trail records both, honestly, in the same session:
`agent / create_order / order_value_exceeds_cap` (blocked) immediately
followed by `customer_direct / create_order / human_confirmed_direct_checkout`
(allowed) — the two-tier trust model made visible in the evidence
itself, not just asserted in the architecture doc.

## Post-submission — MCP server never loaded .env, and a real payment-link feature

Two things landed together. First, a request: let any LLM (chat, MCP,
Claude Desktop) drive a purchase all the way to a real Razorpay
payment, not just the storefront. Since no MCP tool can open a browser
window itself, the right answer is a real, clickable payment link —
`capture_payment_raw()` now returns `payment_link` pointing at a new
standalone page (`web/pay.html`, served at `/pay/{order_id}`) with the
real Razorpay Checkout widget, reachable from anywhere an LLM can hand
back a URL. `config.PUBLIC_BASE_URL` makes the link correct once
deployed, not just on localhost. System prompt updated to (a) confirm
the order with the customer before calling create_order at all, and
(b) share that exact link when payment needs a human.

Testing it over MCP specifically surfaced a real, separate bug:
`mcp_server/server.py` never called `load_dotenv()` — every other
entrypoint in this project does. It had been silently running in mock
mode the entire time over MCP, including through all the earlier MCP
testing (Step 12, the Claude Desktop purchase, the GR2 side-by-side
test) — none of that touched real credentials, so it never surfaced.
Only showed up now because this was the first time something over MCP
specifically depended on `domain.payments.is_live()` returning the
right answer. Fixed with the same two-line `load_dotenv()` pattern
every other file already uses. Re-verified: MCP now creates a real
Razorpay order and returns a working payment_link, identical in shape
to the chat path.

**Worth remembering**: a bug like this — correct code, wrong
environment — only shows up when you test the actual dependency it
affects, not just "does the tool return successfully." Mock and live
mode returning superficially similar-shaped success responses is
exactly what let this hide for as long as it did.

## Post-submission — escalation now has a real second half

"Escalated to a human" was a dead end three times over in live testing
— a rejection message with nothing behind it. Built the actual
completion: `create_pending_approval()` freezes a real record (order
id, exact total, item snapshot) the moment GR2 blocks a create_order
call, independent of whatever the live cart does afterward. A new
`/admin` page (no auth — a real deployment needs it, flagged honestly,
not pretended away) lists every pending record with Approve/Reject.
Approving creates the actual Razorpay order at that point — not
earlier, so nothing gets created for attempts nobody ever reviews —
and the existing payment_link/pay-page flow picks it up unchanged.

Verified the entire loop over MCP, no LLM cost: over-cap create_order
-> pending_order_id returned -> shows in /api/admin/pending with
correct item snapshot -> approve -> real Razorpay order_id appears ->
/pay/{id} correctly switches from "waiting for review" to a working
pay button. Reject path closes it out cleanly, disappears from the
queue either way. Audit trail logs both with actor=merchant_operator,
distinct from agent/customer_direct — the audit trail now has all
three tiers of who-did-what: agent (blocked), customer_direct
(bypasses that don't need a guardrail), merchant_operator (the actual
human review GR2's escalation always should have led to).

## Post-submission — escalation still had a dead end, from a different door

Live over MCP: Claude Desktop, told a cart was over cap, called
`escalate_to_human` directly instead of `create_order` — a completely
reasonable reading of that tool's own description ("hand this to a
human"), and one this project cannot control, since MCP tool
descriptions are the only prompt guidance an external LLM ever sees
(`agent/prompts.py`'s system prompt only governs the internal loop).
`escalate_to_human`'s handler, though, was a pure no-op — logged the
reason and returned `{"ok": true, "action": "escalated"}`, never
touched the cart, never created a `pending_approval` row. Confirmed via
`audit_log.jsonl`: the call was logged correctly (actor=external_agent,
the earlier MCP-logging fix worked), but no `PENDING-xxxx` order
existed anywhere — because the only code path that ever created one
lived inside `create_order`'s own rejection branch, and nothing forces
an external agent to call `create_order` before giving up on it.

**Why this is a different bug from the logging gap, not the same one
again:** that fix made MCP calls visible in the audit trail; this gap
meant one specific, entirely valid MCP call sequence produced no
trackable order at all, visible or not — a real gap in coverage, not
a visibility gap.

**Fix:** moved the "am I over cap, freeze a record" check out of
`create_order`'s rejection branch and into `_escalate_to_human()`
itself (`tools/registry.py`) — it now checks the live cart directly
and calls `create_pending_approval()` whenever the cart is non-empty
and over `MAX_AUTO_ORDER_VALUE`, regardless of which tool path got
there. This is the guardrails-in-code principle applied one level
deeper: don't just avoid trusting the LLM's *words*, don't trust its
*tool-call ordering* either — the trackable record has to exist
because the code checked the cart, not because the caller happened to
invoke things in the sequence the internal loop always does.

Verified directly against the registry (bypassing MCP transport,
same as `_call()` does): a fresh cart over cap, `escalate_to_human`
called with no prior `create_order` attempt, returns a real
`pending_order_id` and the row appears on `/api/admin/pending`
immediately. `ask_clarification` was checked too — deliberately left
alone, since it's genuinely stateless and never claims to hand
anything to a human.
