# TedPro — Product Roadmap

Items that are deliberately deferred — not forgotten, just correctly timed.
Each has a trigger that tells you when to build it.

---

## 🔴 Build when: first client asks for it

### Multi-user / Team Access
**What:** One account, multiple logins. Owner can invite team members via email.
Each member gets their own password. Owner can remove access without affecting others.
**Why deferred:** First clients are likely 1-2 person SMEs who share one login fine.
**Scope:** 2-3 sessions. New `team_members` table, invite flow, Settings UI.
**Watch out for:** `admin_reverify` and password reset both need to check team_members table too.

---

## 🟠 Build when: 5+ active clients

### Supabase Row Level Security (RLS)
**What:** Database-level isolation as a second layer of protection. Even if the app
code has a bug, the database itself refuses cross-tenant queries.
**Why deferred:** App-layer isolation is solid and tested. RLS is a backstop,
not a fix for a current hole.
**Scope:** 1 session. Write RLS policies for all 6 tables in Supabase dashboard.
**No code changes needed** — purely a Supabase configuration task.

### Per-tenant Rate Limiting
**What:** Each client gets their own rate limit bucket instead of sharing one
IP-based limit. Prevents one high-traffic client from affecting others.
**Why deferred:** IP-based limiting works fine at low client count.
**Scope:** 1 session. Requires Redis or a DB-backed counter. Render Redis add-on
or Upstash (free tier available).

### Engine Cache TTL
**What:** The `_engines` dict grows indefinitely — one HybridEngine per client,
never evicted. At 50+ clients this becomes a memory leak.
**Why deferred:** Safe at current scale on Render's 512MB instance.
**Scope:** Half a session. Add a simple LRU cache or timestamp-based eviction.

---

## 🟡 Build when: moving to self-serve growth

### Stripe / Automated Billing
**What:** Clients sign up, enter card, get charged monthly automatically.
Usage-based tiers (messages sent, leads captured).
**Why deferred:** Manual invoicing works fine for first 10 clients. Don't build
billing infrastructure before you know what people will pay.
**Scope:** 3-4 sessions. Stripe integration, webhook for payment events,
plan enforcement in the app.

### Email Verification on Wizard
**What:** New clients verify their email before account is activated. Prevents
spam accounts and throwaway signups.
**Why deferred:** You're manually vetting first clients anyway.
**Scope:** 1 session. Send a verification email with a token, gate wizard completion.

### Widget Origin Validation
**What:** Check that the widget is being loaded from the client's registered
`shop_url` domain. Prevents someone embedding another client's widget on
their own site.
**Why deferred:** Low risk when clients are vetted manually.
**Scope:** 1 session. Check `Referer` header against `accounts.shop_url`.

---

## 🔵 Build when: technical debt becomes a real problem

### `main.py` Restructure
**What:** Split 3,974-line monolith into logical modules.
Suggested structure:
```
main.py          — app init, middleware, routing only
routes/
  admin.py       — all /admin/* routes
  widget.py      — widget chat, embed, lead capture
  setup.py       — onboarding wizard
  webhooks.py    — order webhooks
  auth.py        — login, logout, password reset
services/
  tenancy.py     — already exists
  orders.py      — already exists
  analytics.py   — already exists
  hybrid_engine.py — already exists
```
**Why deferred:** Nothing is broken. Refactoring introduces new bugs.
Do this as a standalone project with full test coverage, not mid-feature.
**Scope:** 3-4 sessions minimum.

### Multi-worker Support
**What:** Move `_response_store` (main-page chat polling handoff) from
in-process memory to Redis or the database. Allows `WEB_CONCURRENCY > 1`.
**Why deferred:** Pinned to 1 worker in render.yaml. Safe until you have
traffic that justifies scaling.
**Scope:** 1-2 sessions. Replace dict with Redis pub/sub or DB polling.

### Proper Email Infrastructure
**What:** Replace personal Gmail with a transactional email service
(Resend, SendGrid, Mailgun). Proper domain-based sending, delivery
tracking, unsubscribe handling.
**Why deferred:** Gmail works for low volume. Becomes unprofessional
and unreliable at scale (Gmail limits, spam risk).
**Trigger:** When any client complains about not receiving emails, or
when you hit ~100 emails/day.
**Scope:** 1 session. Resend has a generous free tier and clean API.

---

## ✅ Already done (for reference)

- PBKDF2 password hashing (backward-compatible)
- Timing-safe auth (admin + dev)
- CSRF protection on all write routes
- Prompt injection guard
- Widget rate limiting (30/min per IP)
- Per-client data isolation — all queries scoped + tested with real attack
- Cross-tenant `.match()` fix (confirmed working)
- Per-client webhook secrets
- Account suspension enforcement
- Usage tracking (buffered, flushes every 10 msgs)
- Per-client branding throughout (widget, email, handoff, AI identity)
- Password show/hide on all forms
- Password reset flow (email-based, token expiry 1hr)
- Admin email stored on account for password reset
- FAQ quick buttons from client's own FAQs
- 24-hour widget session expiry
- Leads export CSV
- Orders export CSV
- Conversations export CSV
- Enhanced leads panel (shows what customer first asked about)
- Honest Impact dashboard (no estimated pipeline)
- Cross-tenant isolation confirmed: real attack test passed
- Duplicate product cleanup (Supabase)
- Hallucination guard — generic, no false positives
- Row Level Security on all 6 tables (anon blocked, service role allowed, authenticated policies pre-written)
- Automatic Supabase views per client for clean data browsing

---

*Last updated: August 2026 — TedPro v2.1.1*
