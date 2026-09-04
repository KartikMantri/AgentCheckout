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
