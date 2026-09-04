# AgentCheckout

**Razorpay AI Buildathon — Track 01: AI Growth & Agentic Commerce**

An agent-readable commerce layer for merchants. Not a shopping bot — the thing shopping bots (and shopping humans) plug into.

## The problem

E-commerce infrastructure is built for one buyer type: a human clicking through a UI. Two others are emerging that most merchants can't serve: a conversational shopper who wants to describe intent in plain language, and an autonomous AI agent acting on a human's behalf. Both need a catalog they can query structurally, stock they can trust in real time, and a checkout path that doesn't assume a human hand on the mouse.

**The core design decision, and everything else follows from it:** the LLM serving any given turn is treated as an untrusted, possibly-incompetent, possibly-adversarial caller. Every money-affecting action is validated and guarded in code — never in a prompt — so the system's safety properties don't depend on which model, or how clever a user's phrasing is.

## Architecture

```
[Human via chat]   [External AI agent via MCP]
        |                    |
   Internal loop        MCP server (no LLM)
        |                    |
     LLM router (Groq <-> Gemini, task-typed, fails over)
        |____________________|
                 |
     ==== TRUST BOUNDARY ====
                 |
         Tool layer (schema validation)
                 |
       Guardrail layer (pure functions, no LLM, ever)
                 |
          Domain layer (catalog/cart/orders/payments)
                 |
        SQLite  +  Razorpay (mocked)
                 |
       Audit log (JSONL, append-only)
```

Both entry points converge on the identical tool → guardrail → domain path. Proven directly (Step 12): the same `apply_discount(pct=40)` guardrail rejection fires identically whether the caller is the internal loop or an external MCP client that has never seen this codebase — no guardrail logic was written twice.

## Tools (10)

| Tool | Guardrails | Notes |
|---|---|---|
| `search_catalog` | — | Read-only, live stock only, bounded to 5 results by default |
| `add_to_cart` | GR4 (stock) | Structured rejection if insufficient stock |
| `remove_from_cart` | — | Added after live testing surfaced there was no way to undo an add — see notes/build_log.md |
| `clear_cart` | — | Empties items and any applied discount |
| `apply_discount` | GR1 (cap), GR3 (one per order) | Escalates above cap |
| `create_order` | GR2 (order value) | Freezes the total permanently |
| `capture_payment` | GR2, GR6 (confirmed order), idempotency | Real Razorpay test mode when credentials are set (falls back to mock); in live mode, correctly refuses to charge without a human-completed Checkout widget rather than crashing or faking it |
| `check_order_status` | — | Reads the real order record — lets the agent answer "any update?" on an escalated order instead of guessing from stale conversation memory |
| `ask_clarification` | — | Uncertainty as a callable action, not a hoped-for behavior |
| `escalate_to_human` | — | Terminal — out-of-bounds requests land here, not in an argument; also the second place (besides `create_order`) that can freeze a pending-approval record, since an external agent may reach it directly |

## Guardrails

All limits live in `config.py`. All enforcement logic lives in `guardrails/rules.py`. Neither file imports an LLM client — that's not a style choice, it's the entire trust boundary.

| # | Guardrail | Default | Proven |
|---|---|---|---|
| GR1 | Max auto-approved discount | 10% | 4 different social-engineering framings (plain ask, emotional appeal, false authority claim, prompt injection) — identical rejection every time |
| GR2 | Max auto-approved order value | ₹5,000 | Blocked a >₹5,000 order, escalated cleanly |
| GR3 | Discount applications per order | 1 | — |
| GR4 | Stock check before cart add | Always | — |
| GR6 | Payment capture on unconfirmed order | Forbidden | Idempotent replay allowed through by design; a genuinely invalid order is not |
| GR7 | Max agent loop iterations | 8 | — |
| GR8 | Max tool-call retries on malformed args | 2 | Recovered a real malformed call (`qty: "one"`) in 3 turns |

**A guardrail catches an unsupervised AI, not a supervised human — and the code now actually knows the difference.** GR2 blocks `create_order` when the *agent* (chat, MCP, Claude Desktop) decides on a large order — proven, still fully enforced. But a human looking at their own real cart total in the storefront and clicking a real "Confirm & place order" button *is* the human-in-the-loop GR2 exists to guarantee, so `web/app.py`'s `/api/cart/{id}/confirm-checkout` calls order creation directly, bypassing the guardrail-wrapped path entirely — reachable only by that literal button click, never by anything an LLM can output. Verified side by side in one session: the agent still refused an ₹11,098 cart exactly as before; the same cart, confirmed directly by a human, created a real order seconds later. Payment is unaffected either way — creating an order never moves money, and capture still requires the real Razorpay widget regardless of which path created it.

## Providers

Two, not three. Cerebras was dropped after its free-tier account required billing verification we don't have (a real, documented instance of the exact risk §1.12/§5.4 warn about — free-tier catalogs are gated or pruned without notice).

| task_type | primary | fallback |
|---|---|---|
| routing | Groq `gpt-oss-20b` | Gemini `flash-lite` |
| extraction | Groq `gpt-oss-120b` | Gemini `flash` |
| judgment | Groq `gpt-oss-120b` | Gemini `flash` |
| summarise | Groq `gpt-oss-20b` | Gemini `flash-lite` |

`judgment` was originally planned Gemini-primary (spend the strongest model where uncertainty-detection matters most). Swapped to Groq-primary after live testing showed **`gemini-3.7-flash`'s free tier allows only 20 requests/day, total** — nowhere near enough to be any task's primary. Gemini remains a real fallback in every chain; the multi-vendor claim is intact, just not load-bearing on the tightest quota. Groq's actual free tier turned out far more generous than the PRD's planning assumption (250K TPM / 1K RPM, not 6K TPM) — quota pressure is much lower in practice than expected going in.

## Running it

```
cd agentcheckout
.venv\Scripts\python.exe -m pip install -r requirements.txt   # already set up if you're continuing this build
copy .env.example .env    # fill in GROQ_API_KEY and GEMINI_API_KEY
.venv\Scripts\python.exe scripts\healthcheck.py               # confirm both providers respond
```

**Try the agent directly:**
```python
from dotenv import load_dotenv; load_dotenv()
from domain.catalog import init_db; from domain.cart import init_cart_tables; from domain.orders import init_order_tables
init_db(); init_cart_tables(); init_order_tables()
from agent.loop import run
print(run("Find me flat-foot running shoes under 3000 and add the best one to my cart.")[0])
```

**Run the full scripted build, in order:** `scripts/step1_*` through `scripts/step13_*` — each is self-contained and runnable, and together they're the fastest way to see every layer working (see `notes/build_log.md` for what each one proved, and what it broke along the way).

**Run the 12 scripted scenarios + generate real metrics:**
```
.venv\Scripts\python.exe audit\report.py
```

**Talk to it as an MCP server** (e.g. from Claude Desktop's config, or `scripts/step12_mcp_client_agent.py` for a scripted external-agent demo):
```
.venv\Scripts\python.exe mcp_server\server.py
```

## Known limitations — stated honestly, not hidden

- **Razorpay test-mode credentials are wired in and confirmed working.** `create_order` hits the real Razorpay Orders API (`domain/payments.py`) whenever `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` are set, falling back to a mock automatically otherwise — same pattern as the LLM router degrading when a provider key is missing. One real constraint worth stating plainly: **capturing an actual payment always needs a human to complete Razorpay's Checkout widget once** — no payment gateway anywhere lets a server charge a card that was never provided through an audited surface. `create_order` and everything before it is fully agent-callable, autonomous, no human needed; final payment capture via the real widget is a one-time human click, exposed in the web storefront (`web/store.html`) as a payment card that appears the moment an order is created. The agent/MCP-driven `capture_payment` tool still uses the mock gateway by design — see the README's Architecture section and `notes/build_log.md` for the reasoning.
- **M7 (provider-invariance) and M8 (failover survival) have working code and test harnesses (`scripts/step11_invariance.py`) but no clean live numbers yet** — the first run exhausted Gemini's 20/day free quota mid-batch. See `notes/build_log.md` for the two real bugs that outage exposed and fixed (pre-emptive budget skip could eliminate the last fallback provider; a fully-exhausted router used to crash the whole request instead of degrading gracefully).
- **No web UI.** Deliberately deferred — the PRD's own prioritization lists UI polish as the first thing to cut, and every scripted step here is directly runnable and inspectable, which mattered more under the time budget.
- **Cart-state answers can trust conversation memory over a fresh database read** — seen once in Step 8 (a "what's in my cart" question answered from memory rather than a fresh `get_cart` call). Correct in that instance, but there's no guardrail catching a stale *read* the way GR4 catches a stale *write*.
- **The budget tracker (`agent/budget.py`) is a simplified cumulative-since-process-start counter, not a real per-minute sliding window** — good enough to catch the Gemini quota issue, not a production-grade rate limiter.

See `notes/build_log.md` for the full, dated account of what was found and fixed along the way — including two real bugs (stock never decremented after a sale; a metrics double-counting bug) caught by testing, not by code review.

## Repo structure

```
agentcheckout/
├── config.py              # every limit, every provider, every chain — nowhere else
├── data/seed_catalog.json # 18 running-shoe SKUs
├── domain/                # catalog, cart, orders, payments — no LLM import, ever
├── guardrails/             # pure verdict functions — no LLM import, ever
├── tools/                 # schemas (OpenAI + Pydantic) + the registry that ties it together
├── agent/                 # router, loop, session memory, history trimming, budget
├── mcp_server/             # same tool registry, exposed to any MCP client
├── audit/                  # JSONL logger + report.py (generates metrics.md)
├── tests/scenarios.py      # 12 scripted conversations, 8 happy / 4 adversarial
├── scripts/                # step1-13, each independently runnable
└── notes/build_log.md      # dated, honest account of what broke and why
```
