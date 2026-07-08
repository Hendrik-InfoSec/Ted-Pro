"""
orders.py — Order tracking & revenue attribution for TedPro.

Turns the Impact Dashboard's *estimated* pipeline into *confirmed attributed
revenue* — the number that closes R8000/month deals.

Two capabilities:
  1. ATTRIBUTION — when an order's email matches a lead Teddy captured, the
     order is credited as "Teddy-influenced". Conservative, email-based,
     defensible.
  2. ORDER LOOKUP — a customer asking "where's my order #1234?" gets a real
     answer from the orders table (self-serve support, no login).

Platform-agnostic: orders arrive via a single webhook endpoint in a normalised
shape, so the same code works whether the client runs Shopify, WooCommerce,
a custom store, or pushes orders manually for testing.

Expected Supabase `orders` table schema (create once — SQL provided in the
deploy notes):
    id              uuid primary key default gen_random_uuid()
    client_id       text not null
    order_number    text not null
    email           text
    customer_name   text
    amount          numeric
    currency        text default 'ZAR'
    items           jsonb
    status          text default 'processing'
    attributed      boolean default false
    source          text
    created_at      timestamptz default now()
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

VALID_STATUSES = {"processing", "paid", "packed", "shipped", "delivered", "cancelled", "refunded"}


def _norm_email(e) -> str:
    return str(e or "").strip().lower()


def normalise_order(payload: dict, client_id: str) -> dict | None:
    """
    Convert an incoming webhook payload (from any platform or a manual push)
    into our normalised order shape. Tolerant of Shopify/WooCommerce field
    names so one endpoint handles them all.

    Returns the normalised dict, or None if the payload lacks the essentials.
    """
    if not isinstance(payload, dict):
        return None

    # Order number — many platforms use different keys
    order_number = (
        payload.get("order_number")
        or payload.get("order_id")
        or payload.get("number")
        or payload.get("name")        # Shopify uses "name" like "#1001"
        or payload.get("id")
    )
    if order_number is None:
        return None
    order_number = str(order_number).lstrip("#").strip()

    # Email — Shopify nests under "email" or customer.email
    email = payload.get("email")
    if not email and isinstance(payload.get("customer"), dict):
        email = payload["customer"].get("email")
    email = _norm_email(email)

    # Customer name
    name = payload.get("customer_name") or payload.get("name")
    if not name and isinstance(payload.get("customer"), dict):
        c = payload["customer"]
        name = " ".join(filter(None, [c.get("first_name"), c.get("last_name")])).strip()

    # Amount — total_price (Shopify), total (Woo), or amount
    amount_raw = (
        payload.get("amount")
        or payload.get("total_price")
        or payload.get("total")
        or payload.get("total_amount")
        or 0
    )
    try:
        amount = float(amount_raw)
    except (ValueError, TypeError):
        amount = 0.0

    currency = payload.get("currency") or "ZAR"

    # Items — accept a list of {name, qty, price} or platform line_items
    items = payload.get("items") or payload.get("line_items") or []
    clean_items = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                clean_items.append({
                    "name": it.get("name") or it.get("title") or "Item",
                    "qty": it.get("qty") or it.get("quantity") or 1,
                    "price": it.get("price") or 0,
                })

    status = str(payload.get("status") or "processing").lower()
    if status not in VALID_STATUSES:
        status = "processing"

    return {
        "client_id": client_id,
        "order_number": order_number,
        "email": email,
        "customer_name": name or "",
        "amount": amount,
        "currency": currency,
        "items": clean_items,
        "status": status,
        "source": payload.get("source") or "webhook",
    }


def record_order(supabase, payload: dict, client_id: str) -> dict:
    """
    Store an incoming order and attempt attribution against captured leads.
    Idempotent: re-sending the same order_number updates rather than duplicates.

    Returns {"ok": bool, "attributed": bool, "order_number": str, ...}.
    """
    order = normalise_order(payload, client_id)
    if not order:
        return {"ok": False, "error": "Invalid order payload — missing order number"}

    try:
        # Attribution: does this order's email match a lead Teddy captured?
        attributed = False
        if order["email"]:
            leads = supabase.table("leads").select("email").execute().data or []
            lead_emails = {_norm_email(l.get("email")) for l in leads}
            attributed = order["email"] in lead_emails
        order["attributed"] = attributed

        # Idempotent upsert by (client_id, order_number)
        existing = (supabase.table("orders")
                    .select("id")
                    .eq("client_id", client_id)
                    .eq("order_number", order["order_number"])
                    .execute().data)
        if existing:
            supabase.table("orders").update({
                "email": order["email"],
                "customer_name": order["customer_name"],
                "amount": order["amount"],
                "currency": order["currency"],
                "items": order["items"],
                "status": order["status"],
                "attributed": order["attributed"],
                "source": order["source"],
            }).eq("id", existing[0]["id"]).execute()
            action = "updated"
        else:
            supabase.table("orders").insert(order).execute()
            action = "created"

        logger.info(f"Order {order['order_number']} {action} "
                    f"(attributed={attributed}, {order['currency']} {order['amount']})")
        return {
            "ok": True,
            "action": action,
            "order_number": order["order_number"],
            "attributed": attributed,
            "amount": order["amount"],
            "currency": order["currency"],
        }
    except Exception as e:
        logger.error(f"record_order error: {e}")
        return {"ok": False, "error": str(e)}


def lookup_order(supabase, query: str, client_id: str, email: str | None = None) -> str | None:
    """
    Answer a customer's order-status question from real data — no AI, no login.
    Matches an order number found in the query, or the most recent order for a
    known email. Returns a friendly status string, or None if nothing matches.
    """
    import re
    try:
        # Pull an order-number-looking token out of the message
        m = re.search(r"#?\b(\d{3,})\b", query)
        order = None

        if m:
            num = m.group(1)
            rows = (supabase.table("orders").select("*")
                    .eq("client_id", client_id)
                    .eq("order_number", num)
                    .limit(1).execute().data)
            order = rows[0] if rows else None

        if not order and email:
            rows = (supabase.table("orders").select("*")
                    .eq("client_id", client_id)
                    .eq("email", _norm_email(email))
                    .order("created_at", desc=True)
                    .limit(1).execute().data)
            order = rows[0] if rows else None

        if not order:
            return None

        status = order.get("status", "processing")
        num = order.get("order_number", "")
        friendly = {
            "processing": "is being processed \U0001f504",
            "paid": "is paid and being prepared \U0001f4b3",
            "packed": "is packed and ready to ship \U0001f4e6",
            "shipped": "is on its way to you \U0001f69a",
            "delivered": "has been delivered \u2705",
            "cancelled": "was cancelled \u274c",
            "refunded": "has been refunded \U0001f4b8",
        }.get(status, f"is currently: {status}")

        return f"Your order #{num} {friendly}. Let me know if you need anything else!"
    except Exception as e:
        logger.error(f"lookup_order error: {e}")
        return None


def update_order_status(supabase, client_id: str, order_number: str, new_status: str) -> dict:
    """
    Manually update an order's status — for clients whose platform doesn't
    auto-fire status webhooks. Used by the admin Orders screen.
    """
    status = (new_status or "").strip().lower()
    if status not in VALID_STATUSES:
        return {"ok": False, "error": f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}"}
    try:
        existing = (supabase.table("orders").select("id")
                    .eq("client_id", client_id).eq("order_number", order_number)
                    .limit(1).execute().data)
        if not existing:
            return {"ok": False, "error": f"Order {order_number} not found"}
        supabase.table("orders").update({"status": status}).eq("id", existing[0]["id"]).execute()
        logger.info(f"Order {order_number} manually set to {status} for {client_id}")
        return {"ok": True, "order_number": order_number, "status": status}
    except Exception as e:
        logger.error(f"update_order_status error: {e}")
        return {"ok": False, "error": str(e)}


def list_orders(supabase, client_id: str, limit: int = 100) -> list:
    """Fetch recent orders for the admin Orders screen, newest first."""
    try:
        return (supabase.table("orders").select("*")
                .eq("client_id", client_id)
                .order("created_at", desc=True)
                .limit(limit).execute().data or [])
    except Exception as e:
        logger.error(f"list_orders error: {e}")
        return []


def order_metrics(supabase, client_id: str, days: int = 30) -> dict:
    """
    Confirmed-revenue metrics for the Impact Dashboard.
    Distinguishes total store revenue from Teddy-attributed revenue.
    """
    since = datetime.now() - timedelta(days=days)
    out = {
        "orders_total": 0,
        "orders_period": 0,
        "revenue_total": 0.0,
        "revenue_attributed": 0.0,
        "attributed_orders": 0,
        "currency": "ZAR",
        "attribution_rate": 0.0,
    }
    try:
        rows = (supabase.table("orders").select("*")
                .eq("client_id", client_id)
                .order("created_at", desc=True)
                .limit(5000).execute().data or [])
        out["orders_total"] = len(rows)
        if rows and rows[0].get("currency"):
            out["currency"] = rows[0]["currency"]

        def _ts(v):
            s = str(v or "").replace("Z", "").split("+")[0].strip()
            for f in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                      "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(s, f)
                except ValueError:
                    continue
            return None

        period = [r for r in rows if (_ts(r.get("created_at")) or datetime.min) >= since]
        out["orders_period"] = len(period)

        for r in period:
            if r.get("status") in ("cancelled", "refunded"):
                continue
            try:
                amt = float(r.get("amount") or 0)
            except (ValueError, TypeError):
                amt = 0.0
            out["revenue_total"] += amt
            if r.get("attributed"):
                out["revenue_attributed"] += amt
                out["attributed_orders"] += 1

        out["revenue_total"] = round(out["revenue_total"], 2)
        out["revenue_attributed"] = round(out["revenue_attributed"], 2)
        if out["orders_period"]:
            out["attribution_rate"] = round(
                100 * out["attributed_orders"] / out["orders_period"], 1)
    except Exception as e:
        logger.error(f"order_metrics error: {e}")
    return out
