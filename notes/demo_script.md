# AgentCheckout — pitch video script & demo runbook

Razorpay AI Buildathon, Track 01 (AI Growth & Agentic Commerce). Target
length: 3 minutes. Written to be read almost verbatim, timed to the
screen actions listed under each beat.

---

## 0. Before you hit record

- Kill and restart the web server fresh (`web/app.py`) so the audit
  trail and cart state are clean for the take — a half-finished cart
  from earlier testing will confuse the story.
- Fully quit and relaunch Claude Desktop if you're doing the MCP beat,
  and start a brand-new chat there (not a continued one).
- Have three browser tabs ready, in this order: Stridewell storefront
  (`/`), the merchant admin page (`/admin`), and nothing else — don't
  show the chat console (`/chat`) unless you want the internals; the
  storefront's own chat widget is the same underlying agent.
- Know your two demo carts in advance so you're not improvising sums
  live:
  - **Small/valid cart**: 1-2 items, total under ₹5,000 (e.g. one pair
    ~₹2,499) — this is the one that goes all the way to a real
    Razorpay payment.
  - **Large/escalated cart**: 2+ items totalling over ₹5,000 (e.g. two
    pairs of a ~₹5,500+ shoe) — this is the one that gets blocked and
    routed to `/admin`.
- Razorpay test-mode card for the live Checkout widget:
  card `4111 1111 1111 1111`, any future expiry, any CVV, any name —
  standard Razorpay test card, not a real charge.

---

## 1. Hook + problem (0:00–0:20)

**Screen:** Stridewell storefront, hero banner visible ("Flat 10% off
every pair — just ask the assistant").

**Script:**
> "Every merchant wants AI agents shopping on their behalf — Claude,
> ChatGPT, whatever a customer brings. But handing an LLM a checkout
> tool is handing it a blank check. It can be prompted, jailbroken, or
> just confidently wrong about a discount it isn't allowed to give.
> AgentCheckout is a merchant-side layer that exposes a real catalog to
> any AI as structured tools — where every limit is enforced in code,
> never in a prompt an attacker could argue with."

---

## 2. Architecture, fast (0:20–0:45)

**Screen:** the system-design diagram (Artifact) or just narrate over
the storefront — keep this beat short, it's the least visual part.

**Script:**
> "The model only ever sees ten tools — search, cart, discount, order,
> payment, status. It never touches the database, never sees a price
> it didn't just fetch. Every tool call runs through one dispatch
> function that checks a guardrail before anything happens: a ten
> percent discount cap, a five-thousand-rupee auto-approval cap, stock
> checks, idempotent payment capture. If you deleted the LLM
> entirely, the guardrails and the storefront still work — that's the
> point. The AI is a convenience layer on top of a system that doesn't
> trust it."

---

## 3. Live: normal purchase, storefront chat (0:45–1:30)

**Screen:** Stridewell storefront, open the chat widget.

**Actions + script:**
1. Type: *"I want a daily running shoe under 3000 rupees"* → agent
   calls `search_catalog`, shows real results.
   > "Everything it says comes from a live tool call — not memory, not
   > a guess."
2. *"Add that to my cart"* → cart badge updates.
3. *"Apply a discount"* (don't state a percentage) →
   > "Watch — I didn't say how much. It knows the store's real cap is
   > ten percent and applies it directly instead of making me guess."
4. *"I'm ready to check out"* → agent confirms the total, asks for a
   clear go-ahead → say *"yes, place the order"* → `create_order`
   fires.
5. Payment card appears inline → click **Pay with Razorpay** → use the
   test card → completes.
   > "That's a real Razorpay order, real signature verification, test
   > mode. No LLM ever touched a payment credential — it can only hand
   > the customer a real checkout widget that a human completes."

---

## 4. Live: the guardrail actually holding (1:30–2:10)

**Screen:** same chat, fresh cart or the large demo cart.

**Actions + script:**
1. Add the large cart (over ₹5,000).
2. *"Give me a 40% discount"* →
   > "Forty percent, rejected — it states the real cap, ten percent,
   > and offers the alternative in the same message. It can't be
   > talked into a bigger number no matter how I phrase it — that
   > logic isn't in the prompt, it's in code the model never sees."
3. *"Just place the order anyway"* → `create_order` blocked, cart
   over cap → response includes a `pending_order_id`.
   > "Above five thousand rupees, no AI — mine or anyone else's — can
   > approve this alone. It gets frozen as a real, trackable record
   > instead of just dying as a rejection message."
4. Switch to the **`/admin`** tab → the pending order appears with its
   exact frozen total and items.
   > "A human merchant reviews the actual snapshot and approves or
   > rejects it — this is the real second half of 'escalate to a
   > human,' not just a chatbot apology."
5. Click **Approve** → back in the chat, ask *"any update on my
   order?"* → agent calls `check_order_status`, reports it's approved,
   gives the payment link.
   > "The customer finds out because the agent actually checked — not
   > because it assumed."

---

## 5. Live: a completely independent AI, same rules (2:10–2:45)

**Screen:** Claude Desktop, fresh conversation, `agentcheckout`
connector already added.

**Actions + script:**
1. *"Search this store for a lightweight racing shoe"* → Claude calls
   the MCP tool, gets real results.
   > "This is Claude Desktop — code it's never seen, tools it
   > discovered over MCP just now. Same catalog, same guardrails."
2. *"Add it to my cart and apply a thirty percent discount"* → blocked
   at 10%, same as before.
   > "Identical enforcement. I didn't write a second set of rules for
   > MCP — it's the exact same guardrail code the storefront just hit."
3. If time allows: place a small order through Claude Desktop too,
   showing the same payment_link pattern since Claude can't open a
   browser checkout window itself.

---

## 6. Close (2:45–3:00)

**Screen:** storefront or the diagram, whichever reads best on a
static final frame.

**Script:**
> "One merchant, one set of guardrails, any AI a customer brings —
> Claude, MCP, a browser chat widget — all held to the same limits,
> enforced in code, not asked for in a prompt. That's AgentCheckout."

---

## Fallback lines if something breaks live

- If a provider (Groq/Gemini) is rate-limited mid-recording: don't
  panic-narrate the error — say *"and here's the resilience layer
  actually kicking in"* and let the graceful degradation message show;
  it's a real, honest feature, not a bug to hide.
- If Claude Desktop shows a stale tool count: this is a known caching
  quirk of the app itself, not the server — cut this beat rather than
  troubleshooting live on camera.

---

# Demo runbook (non-video, for a live walkthrough / judges' Q&A)

## Start everything

```bash
# from D:\Razorpay\agentcheckout
netstat -ano | grep ":8000" | grep LISTENING   # find any stale PID
taskkill //F //PID <pid>                        # only if one is running
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe web/app.py
```

Verify:
- `http://127.0.0.1:8000/` — Stridewell storefront (real shoe photos,
  3D-tilt cards, chat widget, cart drawer)
- `http://127.0.0.1:8000/chat` — full agent console (live cart +
  guardrail log sidebar) — use this if you want to show internals to
  judges, not for the recorded pitch
- `http://127.0.0.1:8000/admin` — merchant review page, no auth (flag
  this honestly if asked — a real deployment needs one)
- `http://127.0.0.1:8000/api/limits` — should return
  `{"max_auto_order_value":5000,"max_auto_discount_pct":10}`

## Reset a session mid-demo

```
POST /api/reset/{session_id}
```
Clears that session's cart/history without touching the DB globally —
use between takes so leftover cart items don't bleed into the next run.

## MCP / Claude Desktop

1. Fully quit Claude Desktop from the system tray (not just closing
   the window) before any code change to `mcp_server/server.py` takes
   effect — it reuses a long-running subprocess per app session.
2. Relaunch, open a **new** chat (old chats can keep a stale tool
   list).
3. Confirm 10 tools are visible in the connector's tool list before
   recording: search_catalog, add_to_cart, remove_from_cart,
   clear_cart, apply_discount, create_order, capture_payment,
   check_order_status, ask_clarification, escalate_to_human.
4. If the count is wrong after a genuine restart, the connector's
   cache is stuck — rename the `mcpServers` key in
   `claude_desktop_config.json` (e.g. `agentcheckout` →
   `agentcheckout_v2`) to force a fresh registration.

## Test payment credentials

- Razorpay test-mode card: `4111 1111 1111 1111`, any future expiry,
  any CVV/name.
- No SBI/other bank netbanking in test mode by design — Razorpay's
  test environment only lists test-mode instruments.

## Known, honestly-disclosed limitations (say these if asked, don't hide them)

- `/admin` has no authentication — demo scope only.
- No real email/SMS is sent on approval — `check_order_status` is the
  substitute; the system prompt says this explicitly rather than
  implying an email is coming.
- Gemini's free tier is 20 requests/day — if M7/M8 cross-provider
  numbers are asked about live, say the quota was the limiting factor
  during testing, not a code failure.
- `PUBLIC_BASE_URL` must be set to the real deployed URL (not
  `127.0.0.1`) before payment links are shared with anyone off this
  machine.
