# Deployment guide — Render

AgentCheckout ships as a single Docker container running the FastAPI
storefront (`web/app.py`). This guide covers deploying that container
to Render. The MCP server (`mcp_server/server.py`) is **not** part of
this deployment — see the note at the bottom for why.

---

## 0. What actually gets deployed

- The Stridewell storefront, chat console, admin panel, and pay page —
  all served by `web/app.py` via `uvicorn`.
- A SQLite database (`data/app.db`) seeded from `data/seed_catalog.json`
  on first boot, and an append-only audit log (`data/audit_log.jsonl`).
- Both LLM providers (Groq, Gemini) and Razorpay, called server-side —
  none of their keys ever reach the browser.

## 1. Pre-flight checklist (done as of this guide)

- [x] `.dockerignore` added — without it, `.env` (real API keys),
      `.venv`, and the local SQLite DB would get baked into the image
      layer via `COPY . .`, even though `.gitignore` keeps them out of
      git. `.gitignore` and `.dockerignore` are separate mechanisms;
      only the latter protects a Docker build.
- [x] `Dockerfile` already reads `$PORT` at runtime (`CMD uvicorn
      web.app:app --host 0.0.0.0 --port ${PORT:-8000}`) — required
      because Render assigns the port dynamically, never 8000 by
      default.
- [x] `data/seed_catalog.json` is tracked in git (so a fresh container
      has a catalog to seed from); `data/app.db` and
      `data/audit_log.jsonl` are gitignored (so a stale local DB never
      gets deployed by accident — the container always starts with a
      clean, freshly-seeded catalog).
- [ ] **Local Docker build could not be verified on this machine** — a
      completely stock `python:3.12-slim` container can't reach PyPI
      here at all (`SSLCertVerificationError` even installing plain
      `requests`, no project code involved). This is the same
      TLS-inspection issue that blocked the local Razorpay API call
      earlier in the build (see `notes/build_log.md`) — some
      network/AV tooling's root CA is trusted by Windows but not by
      Docker Desktop's Linux build VM. **This does not affect
      Render** — Render builds in its own cloud infrastructure, not
      through this network. But it does mean the Dockerfile has only
      been reviewed statically here, not built-and-run end to end
      before the real deploy. Build it on Render first and check logs
      immediately (Section 3) rather than assuming success.

## 2. Environment variables to set on Render

| Variable | Required? | Notes |
|---|---|---|
| `GROQ_API_KEY` | Yes | Primary LLM provider for all chains |
| `GEMINI_API_KEY` | Yes | Fallback provider — 20 requests/day free tier, expect it to exhaust under load; this is documented, expected behavior, not a bug (`notes/build_log.md`) |
| `RAZORPAY_KEY_ID` | Optional | Omit to run in mock-payment mode. Set to a **test-mode** key (`rzp_test_...`) — this is a buildathon demo, never use live Razorpay credentials here |
| `RAZORPAY_KEY_SECRET` | Optional | Paired with the key id above |
| `PUBLIC_BASE_URL` | Yes, once deployed | Set to the real Render URL (e.g. `https://agentcheckout.onrender.com`) **after** the first deploy gives you that URL. Used to build `payment_link`s handed to any LLM (chat, MCP) — if left at the `127.0.0.1` default, every payment link generated in production will be unreachable off this machine |

None of these are baked into the image — Render injects them as real
environment variables at container start, same as `.env` does locally
via `python-dotenv`.

## 3. Render setup steps

1. Push the current `master` branch to GitHub (already done —
   `github.com/KartikMantri/AgentCheckout`).
2. On Render: **New +** → **Web Service** → connect the
   `KartikMantri/AgentCheckout` repo.
3. Runtime: **Docker** (Render will detect the `Dockerfile`
   automatically — don't pick "Python" or it'll ignore the Dockerfile
   and guess a start command).
4. Instance type: the free tier is fine for a demo — one instance,
   no autoscaling needed (SQLite wouldn't be safely shared across
   multiple instances anyway; see the persistence caveat below).
5. Add the environment variables from Section 2 (leave
   `PUBLIC_BASE_URL` unset or pointed at a placeholder for this first
   deploy — you don't have the real URL yet).
6. Deploy. Watch the build logs specifically for the `pip install`
   step — if there's any SSL/network hiccup on Render's side (there
   shouldn't be, per Section 1, but verify rather than assume), it'll
   show here first.
7. Once live, copy the assigned URL (`https://<service-name
   >.onrender.com`), go back into the environment variables, set
   `PUBLIC_BASE_URL` to that exact URL, and trigger a redeploy (or a
   manual "Restart" if Render doesn't auto-restart on an env var
   change — check its dashboard).

## 4. Post-deploy verification

Run these against the real URL, not localhost:

```bash
curl -s https://<your-app>.onrender.com/api/limits
# expect: {"max_auto_order_value":5000,"max_auto_discount_pct":10}

curl -s -o /dev/null -w "%{http_code}\n" https://<your-app>.onrender.com/
# expect: 200 — storefront

curl -s -o /dev/null -w "%{http_code}\n" https://<your-app>.onrender.com/admin
# expect: 200 — admin panel (no auth, as documented)

curl -s https://<your-app>.onrender.com/api/catalog | python -c "import json,sys; print(len(json.load(sys.stdin)))"
# expect: 18 — confirms the seed catalog loaded on first boot
```

Then do one real walkthrough by hand: search a product in the chat
widget, add to cart, and confirm the payment card (if Razorpay
credentials are set) actually points at your real deployed domain in
the payment link, not `127.0.0.1`.

## 5. Persistence caveat — be honest about this if asked

`data/app.db` and `data/audit_log.jsonl` live on the container's local
filesystem. On Render's free/standard tiers **without an attached
persistent disk**, that filesystem is ephemeral: a redeploy, a crash
restart, or scaling to zero-and-back wipes it, and the app reseeds a
fresh, empty catalog and audit log from `seed_catalog.json` on next
boot. For a buildathon demo that's running continuously during
judging, this is fine — it only becomes a real problem across a
redeploy. If persistence across redeploys ever matters, Render offers
a paid "Disk" add-on mounted at a path you'd point `domain/db.py` and
`audit/logger.py` at — not needed for this submission, but worth
naming as a known limitation rather than a surprise.

## 6. Why the MCP server is not part of this deployment

`mcp_server/server.py` talks to Claude Desktop over **stdio** — it's
launched as a local subprocess by Claude Desktop itself
(`claude_desktop_config.json`'s `mcpServers` entry points at a local
Python path), not as a network service. Deploying the storefront to
Render doesn't change how Claude Desktop reaches this project's tools:
that connection is always local-machine-to-local-subprocess.

Making the MCP tools reachable by a Claude Desktop running on a
*different* machine than the deployed store would require switching
the MCP transport from stdio to a network transport (SSE/HTTP,
supported by the `mcp` package but not wired up here) and exposing
that as its own endpoint on the deployed service. That's a real,
separate piece of work — correctly out of scope for this submission,
and better to state that plainly than to imply MCP "just works"
against the deployed URL when it doesn't.

## 7. Rollback

Render keeps prior deploys — if a deploy breaks, use **Rollback** to
the last known-good one from the dashboard rather than force-pushing
git history around; nothing about this deployment needs a git revert
to recover from a bad container.
