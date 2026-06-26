"""
analytics.py — Revenue & engagement analytics for TedPro.

This is the module that turns "a chatbot" into "R8000/month software".
It computes business-value metrics from data the app already collects
(leads, conversations, products) and renders an owner-facing dashboard
that answers the only question that matters: "What did Teddy do for my
business this month?"

Designed as a standalone module so it stays decoupled from the main app —
import the two public functions and wire them to a route.
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta, date
from collections import defaultdict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signals that indicate a customer was close to buying.
# These are intentionally conservative — we'd rather under-count and have the
# number be defensible than inflate it and lose the owner's trust.
# ---------------------------------------------------------------------------
BUYING_INTENT_SIGNALS = [
    "how much", "price", "cost", "buy", "order", "purchase",
    "add to cart", "checkout", "want", "i'll take", "ill take",
    "available", "in stock", "deliver", "ship", "pay",
]

HOT_LEAD_SIGNALS = [
    "buy now", "order now", "i'll take", "ill take", "add to cart",
    "checkout", "how do i pay", "ready to order", "place an order",
]


def _parse_ts(value) -> datetime | None:
    """Parse a Supabase timestamp string into a datetime, tolerant of formats."""
    if not value:
        return None
    s = str(value).replace("Z", "").split("+")[0].strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def compute_metrics(supabase, client_id: str, days: int = 30) -> dict:
    """
    Compute the headline business metrics for the last `days` days.

    Returns a dict the dashboard renders. Every number is derived from data
    the app already stores — no new tracking required to start showing value.
    """
    since = datetime.now() - timedelta(days=days)
    metrics = {
        "days": days,
        "leads_total": 0,
        "leads_period": 0,
        "conversations_total": 0,
        "conversations_period": 0,
        "buying_moments": 0,
        "hot_leads": 0,
        "estimated_pipeline": 0.0,
        "currency": "ZAR",
        "avg_product_price": 0.0,
        "top_products": [],
        "daily_activity": [],
        "busiest_hour": None,
        "answer_rate": 0.0,
    }

    try:
        # ---- Products: average price anchors the pipeline estimate ----
        products = supabase.table("products").select(
            "name, price, currency, category"
        ).eq("client_id", client_id).execute().data or []
        prices = []
        for p in products:
            try:
                prices.append(float(p.get("price") or 0))
            except (ValueError, TypeError):
                pass
        if prices:
            metrics["avg_product_price"] = round(sum(prices) / len(prices), 2)
        if products and products[0].get("currency"):
            metrics["currency"] = products[0]["currency"]

        # ---- Leads ----
        leads = supabase.table("leads").select("*").execute().data or []
        metrics["leads_total"] = len(leads)
        period_leads = [l for l in leads
                        if (_parse_ts(l.get("timestamp")) or datetime.min) >= since]
        metrics["leads_period"] = len(period_leads)

        # ---- Conversations: the engagement + intent engine ----
        convs = supabase.table("conversations").select(
            "session_id, user_message, bot_response, created_at"
        ).eq("client_id", client_id).order("created_at", desc=True).limit(5000).execute().data or []
        metrics["conversations_total"] = len(convs)

        period_convs = [c for c in convs
                        if (_parse_ts(c.get("created_at")) or datetime.min) >= since]
        metrics["conversations_period"] = len(period_convs)

        # ---- Buying-intent + hot-lead detection ----
        product_mentions = defaultdict(int)
        hourly = defaultdict(int)
        daily = defaultdict(int)
        answered = 0
        product_names = [(p.get("name", "").lower(), p) for p in products]

        for c in period_convs:
            umsg = (c.get("user_message") or "").lower()
            bresp = (c.get("bot_response") or "")

            if any(sig in umsg for sig in BUYING_INTENT_SIGNALS):
                metrics["buying_moments"] += 1
            if any(sig in umsg for sig in HOT_LEAD_SIGNALS):
                metrics["hot_leads"] += 1

            # Did Teddy give a real answer (not a fallback)?
            if bresp and "didn't quite catch" not in bresp and len(bresp) > 10:
                answered += 1

            # Which products are customers asking about?
            for name_lower, prod in product_names:
                if name_lower and name_lower in umsg:
                    product_mentions[prod.get("name")] += 1

            ts = _parse_ts(c.get("created_at"))
            if ts:
                hourly[ts.hour] += 1
                daily[ts.date().isoformat()] += 1

        # Answer rate — a quality/reliability signal owners care about
        if period_convs:
            metrics["answer_rate"] = round(100 * answered / len(period_convs), 1)

        # Estimated pipeline: buying moments × average order value.
        # Conservative and clearly labelled as an estimate in the UI.
        metrics["estimated_pipeline"] = round(
            metrics["buying_moments"] * metrics["avg_product_price"], 2
        )

        # Top products by interest
        metrics["top_products"] = sorted(
            ({"name": k, "mentions": v} for k, v in product_mentions.items()),
            key=lambda x: x["mentions"], reverse=True
        )[:5]

        # Busiest hour — tells the owner when to have humans ready
        if hourly:
            metrics["busiest_hour"] = max(hourly.items(), key=lambda x: x[1])[0]

        # Daily activity series for the last 14 days (for the sparkline/bars)
        series = []
        for i in range(13, -1, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            series.append({"date": d, "count": daily.get(d, 0)})
        metrics["daily_activity"] = series

    except Exception as e:
        logger.error(f"compute_metrics error: {e}")

    return metrics


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_dashboard(metrics: dict, business_name: str = "Your Business", order_metrics: dict | None = None) -> str:
    """
    Render the owner-facing revenue dashboard as an HTML fragment.
    Self-contained inline styles so it drops into the existing admin shell.
    """
    cur = metrics.get("currency", "ZAR")
    pipeline = metrics.get("estimated_pipeline", 0)
    days = metrics.get("days", 30)

    def stat_card(label, value, sub, accent="#FF922B"):
        return (
            f"<div style='background:white;border:1px solid #FFE4CC;border-radius:16px;"
            f"padding:20px;flex:1;min-width:160px'>"
            f"<div style='font-size:11px;text-transform:uppercase;letter-spacing:.05em;"
            f"color:#8B6914;font-weight:600'>{label}</div>"
            f"<div style='font-size:30px;font-weight:700;color:{accent};margin-top:6px'>{value}</div>"
            f"<div style='font-size:12px;color:#8B6914;margin-top:2px'>{sub}</div></div>"
        )

    # Confirmed revenue hero — shown when real orders are connected.
    # This is the number that turns a demo into a signed contract.
    confirmed_hero = ""
    if order_metrics and order_metrics.get("orders_period", 0) > 0:
        rev_attr = order_metrics.get("revenue_attributed", 0)
        rev_total = order_metrics.get("revenue_total", 0)
        ocur = order_metrics.get("currency", cur)
        confirmed_hero = (
            f"<div style='background:linear-gradient(135deg,#16a34a,#15803d);color:white;"
            f"border-radius:20px;padding:28px;margin-bottom:16px'>"
            f"<div style='font-size:13px;text-transform:uppercase;letter-spacing:.08em;opacity:.9'>"
            f"Revenue Teddy is credited with · last {days} days</div>"
            f"<div style='font-size:44px;font-weight:800;margin-top:8px'>{ocur} {rev_attr:,.0f}</div>"
            f"<div style='font-size:13px;opacity:.9;margin-top:6px'>"
            f"From {order_metrics.get('attributed_orders',0)} attributed orders · "
            f"{ocur} {rev_total:,.0f} total store revenue tracked · "
            f"{order_metrics.get('attribution_rate',0)}% attribution rate</div></div>"
        )

    # Headline ROI card — the number that sells the product
    hero = (
        f"<div style='background:linear-gradient(135deg,#FF922B,#FF8C42);color:white;"
        f"border-radius:20px;padding:28px;margin-bottom:20px'>"
        f"<div style='font-size:13px;text-transform:uppercase;letter-spacing:.08em;opacity:.9'>"
        f"Estimated pipeline Teddy influenced \u00b7 last {days} days</div>"
        f"<div style='font-size:44px;font-weight:800;margin-top:8px'>{cur} {pipeline:,.0f}</div>"
        f"<div style='font-size:13px;opacity:.9;margin-top:6px'>"
        f"From {metrics.get('buying_moments',0)} buying-intent conversations "
        f"\u00d7 {cur} {metrics.get('avg_product_price',0):,.0f} average order value</div></div>"
    )

    cards = (
        "<div style='display:flex;gap:14px;flex-wrap:wrap;margin-bottom:20px'>"
        + stat_card("Leads captured", metrics.get("leads_period", 0),
                    f"{metrics.get('leads_total',0)} all-time", "#16a34a")
        + stat_card("Conversations", metrics.get("conversations_period", 0),
                    f"last {days} days", "#2563eb")
        + stat_card("Hot leads", metrics.get("hot_leads", 0),
                    "ready-to-buy signals", "#dc2626")
        + stat_card("Answer rate", f"{metrics.get('answer_rate',0)}%",
                    "questions resolved", "#7c3aed")
        + "</div>"
    )

    # Daily activity bars
    series = metrics.get("daily_activity", [])
    max_count = max([d["count"] for d in series], default=1) or 1
    bars = ""
    for d in series:
        h = int(6 + (d["count"] / max_count) * 60)
        day_label = d["date"][-2:]
        bars += (
            f"<div style='flex:1;display:flex;flex-direction:column;align-items:center;gap:4px'>"
            f"<div style='width:100%;max-width:22px;height:{h}px;background:#FF922B;"
            f"border-radius:4px 4px 0 0;opacity:.85' title='{d['count']} on {d['date']}'></div>"
            f"<div style='font-size:9px;color:#8B6914'>{day_label}</div></div>"
        )
    activity = (
        "<div style='background:white;border:1px solid #FFE4CC;border-radius:16px;"
        "padding:20px;margin-bottom:20px'>"
        "<div style='font-size:13px;font-weight:700;color:#2D1B00;margin-bottom:14px'>"
        "Conversations per day \u00b7 last 14 days</div>"
        "<div style='display:flex;align-items:flex-end;gap:4px;height:80px'>" + bars + "</div></div>"
    )

    # Top products
    tp = metrics.get("top_products", [])
    if tp:
        rows = "".join(
            f"<div style='display:flex;justify-content:space-between;padding:8px 0;"
            f"border-bottom:1px solid #FFF0DB'>"
            f"<span style='font-size:13px;color:#2D1B00'>{_esc(p['name'])}</span>"
            f"<span style='font-size:13px;color:#8B6914;font-weight:600'>{p['mentions']} asks</span></div>"
            for p in tp
        )
    else:
        rows = "<div style='font-size:13px;color:#8B6914;padding:8px 0'>No product questions yet in this period.</div>"
    busiest = metrics.get("busiest_hour")
    busiest_txt = (f"Busiest around {busiest:02d}:00 \u2014 make sure someone's reachable then."
                   if busiest is not None else "Not enough data yet.")
    insights = (
        "<div style='display:flex;gap:14px;flex-wrap:wrap'>"
        "<div style='flex:1;min-width:240px;background:white;border:1px solid #FFE4CC;"
        "border-radius:16px;padding:20px'>"
        "<div style='font-size:13px;font-weight:700;color:#2D1B00;margin-bottom:10px'>"
        "Most-asked-about products</div>" + rows + "</div>"
        "<div style='flex:1;min-width:240px;background:white;border:1px solid #FFE4CC;"
        "border-radius:16px;padding:20px'>"
        "<div style='font-size:13px;font-weight:700;color:#2D1B00;margin-bottom:10px'>"
        "Insight</div>"
        f"<div style='font-size:13px;color:#5A3A1B;line-height:1.5'>{busiest_txt}</div></div>"
        "</div>"
    )

    note = (
        "<p style='font-size:11px;color:#8B6914;margin-top:16px;line-height:1.5'>"
        "Pipeline is a conservative estimate: buying-intent conversations \u00d7 your average "
        "order value. It reflects demand Teddy engaged with, not guaranteed sales. "
        "As order tracking is connected, this becomes actual attributed revenue.</p>"
    )

    return (
        f"<div style='max-width:900px'>"
        f"<h2 style='font-size:18px;font-weight:700;color:#2D1B00;margin-bottom:4px'>"
        f"{_esc(business_name)} \u2014 Teddy's Impact</h2>"
        f"<p style='font-size:13px;color:#8B6914;margin-bottom:20px'>"
        f"What your assistant did over the last {days} days.</p>"
        + confirmed_hero + hero + cards + activity + insights + note + "</div>"
    )
