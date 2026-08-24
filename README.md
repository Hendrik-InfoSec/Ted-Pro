# TedPro — AI Customer Engagement Platform

**A production-grade, multi-tenant SaaS platform** that embeds an AI sales assistant into any business website. Built from scratch by [Hendrik Selogilwe](https://github.com/Hendrik-InfoSec).

🔗 **Live:** https://ted-pro.onrender.com

---

## What it does

TedPro lets businesses embed an AI chat assistant on their website in one line of code. The assistant answers product questions, captures leads, sends branded welcome emails, and tracks which sales it influenced — all without the business owner writing any code.

Each client gets:
- Their own AI assistant branded to their business
- A self-serve admin dashboard (leads, products, FAQs, conversations, orders, analytics)
- An embeddable widget that works on any website
- Webhook integration with Shopify, WooCommerce, and any order management system

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Client's Website                   │
│         <script src="/embed.js?client=ID">           │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│                  TedPro (FastAPI)                    │
│                                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ HybridEngine│  │  Tenancy     │  │  Analytics │  │
│  │ (per-client)│  │  (isolation) │  │  (impact)  │  │
│  └──────┬──────┘  └──────┬───────┘  └─────┬──────┘  │
│         │                │                │          │
└─────────┼────────────────┼────────────────┼──────────┘
          │                │                │
┌─────────▼────────────────▼────────────────▼──────────┐
│              Supabase (PostgreSQL)                    │
│   accounts │ products │ faqs │ leads │ conversations  │
│   orders   — all scoped by client_id                  │
└──────────────────────────────────────────────────────┘
          │
┌─────────▼──────────┐
│  OpenRouter API    │
│  (LLM inference)   │
└────────────────────┘
```

**Stack:** Python, FastAPI, Supabase (PostgreSQL), HTMX, Tailwind CSS, OpenRouter (GPT-4o-mini), Render

---

## Key engineering decisions

### Multi-tenancy
One shared database, one deployed app, unlimited clients — all isolated by `client_id`. Every database query is scoped at the application layer. Cross-tenant isolation was attack-tested: a logged-in admin from Client A cannot read, modify, or delete Client B's data even with a known record ID.

Switched from chained `.eq()` calls to `.match()` after discovering that Supabase's Python client doesn't guarantee AND semantics with multiple `.eq()` — confirmed with a live attack simulation.

### HybridEngine — the AI answer layer
The engine doesn't send every question to the LLM. It runs a three-stage pipeline:
1. **Exact FAQ match** — if the question matches a stored FAQ, return it instantly (no API call)
2. **Fuzzy product match** — if the question is about a product, inject real prices from the database into the prompt (prevents hallucination)
3. **LLM fallback** — everything else goes to the model with full context

Each client gets their own engine instance with isolated QA cache. The system prompt is built dynamically from the client's account data so the AI represents the right business with the right identity.

### Hallucination guard
A post-generation filter checks the AI's response for Title Case phrases that don't exist in the real product catalog. If it finds one, it replaces the entire response with real product data. Generic across all business types — not keyed to any specific product category.

### Security
- **Passwords:** PBKDF2-HMAC-SHA256 with random per-password salt (200k iterations). Backward-compatible with legacy SHA-256 hashes.
- **Auth:** Timing-safe comparison (`hmac.compare_digest`) on all password checks to prevent timing attacks.
- **CSRF:** Token-based protection on all admin write routes. Auto-attached to both HTMX and `fetch()` requests via a global interceptor.
- **Prompt injection:** 17-pattern regex guard screens every user message before it reaches the LLM. Blocks jailbreaks, system prompt spoofing, and internal delimiter injection.
- **Rate limiting:** Per-IP rate limiting on the public widget endpoint (30/min) via slowapi.
- **Session security:** No hardcoded `SECRET_KEY` fallback — fails loudly if unset. `SameSite=None` required for cross-origin widget embedding.
- **Row Level Security:** RLS enabled on all 6 Supabase tables. Anon key access blocked entirely — all queries must go through the app. Service role explicitly allowed through. Authenticated role policies pre-written for future JWT-based auth.

### Per-client branding
The widget header, greeting, WhatsApp handoff, welcome email subject, body, voucher code, and shop URL all pull from the client's account row. The AI's system prompt uses the real business name and type from the database — not environment variables. A florist's assistant introduces itself as a florist, not a plushie brand.

---

## Project structure

```
├── main.py            # FastAPI app — routing, admin dashboard, widget (3,974 lines)
├── hybrid_engine.py   # Per-client AI engine — FAQ matching, product lookup, LLM
├── tenancy.py         # Account management, password hashing, multi-tenant helpers
├── orders.py          # Order tracking, attribution, status management
├── analytics.py       # Revenue dashboard, lead metrics, conversation analytics
├── wizard.py          # Self-serve onboarding wizard (5-step flow)
├── requirements.txt   # Python dependencies
├── render.yaml        # Render deployment config (WEB_CONCURRENCY=1, SECRET_KEY)
├── ROADMAP.md         # Deferred features with build triggers
└── README.md
```

---

## Features

**For businesses (clients):**
- Self-serve onboarding wizard — live in under 10 minutes
- Admin dashboard: leads, products, FAQs, conversations, orders, revenue impact
- Export CSV for leads, orders, and conversations
- Manual order status management
- Per-client webhook URL for Shopify/WooCommerce integration
- Password reset via email
- 1-line embed script

**For the platform:**
- True multi-tenancy — one deployment serves unlimited clients
- Per-client engine isolation — separate QA cache per account
- Usage tracking with buffered DB writes
- Account suspension enforcement
- Row Level Security on all tables — anon access blocked, service role allowed
- Automatic Supabase views per client for clean data browsing
- 24-hour widget session expiry

---

## Running locally

```bash
git clone https://github.com/Hendrik-InfoSec/Ted-Pro.git
cd Ted-Pro
pip install -r requirements.txt

# Required environment variables
export OPENROUTER_API_KEY=your_key
export SUPABASE_URL=your_url
export SUPABASE_KEY=your_key
export SECRET_KEY=any_random_string
export GMAIL_USER=your_gmail
export GMAIL_APP_PASSWORD=your_app_password

uvicorn main:app --reload
```

---

## What's deliberately not built yet

See [ROADMAP.md](./ROADMAP.md) for deferred items with build triggers — Stripe billing, multi-user access, email infrastructure, and the `main.py` restructure. Each is documented with the condition that makes it worth building rather than a timeline.

---

## Built by

**Hendrik Selogilwe** — South Africa  
GitHub: [@Hendrik-InfoSec](https://github.com/Hendrik-InfoSec)

---

*TedPro is a live, deployed product — not a tutorial project.*
