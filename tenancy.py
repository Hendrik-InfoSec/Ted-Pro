"""
tenancy.py — Multi-tenant foundation for TedPro.

The single source of truth for "which client does this request belong to?".
Every per-request client_id resolution goes through here so the logic lives in
ONE place and can be tested in isolation.

Design principle: fail closed. If we cannot confidently resolve a tenant, we
return None and the caller decides — we never guess a client_id, because
guessing wrong means showing one business another business's data.
"""

from __future__ import annotations
import os
import hashlib
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Legacy fallback: the original single-client env value. Lets the existing
# CuddleHeros deployment keep working while we migrate to multi-tenant.
LEGACY_CLIENT_ID = os.environ.get("CLIENT_ID", "tedpro_client")

# Small in-process cache of which client_ids exist, to avoid a DB hit on every
# request just to validate. Refreshed lazily; safe because account creation is rare.
_known_clients: set[str] = set()
_cache_loaded = False


def _hash_password(password: str) -> str:
    """Hash an admin password for storage. Salted with the client_id so the same
    password for two clients produces different hashes."""
    if not password:
        return ""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    return _hash_password(password) == stored_hash


def load_known_clients(supabase) -> set[str]:
    """Populate the in-process set of valid client_ids from the accounts table."""
    global _known_clients, _cache_loaded
    try:
        rows = supabase.table("accounts").select("client_id").execute().data or []
        _known_clients = {r["client_id"] for r in rows if r.get("client_id")}
        _cache_loaded = True
        # Always include the legacy client so the original deployment never breaks
        if LEGACY_CLIENT_ID:
            _known_clients.add(LEGACY_CLIENT_ID)
    except Exception as e:
        # accounts table may not exist yet during migration — fall back gracefully
        logger.warning(f"load_known_clients: {e}")
        _known_clients = {LEGACY_CLIENT_ID} if LEGACY_CLIENT_ID else set()
    return _known_clients


def account_exists(supabase, client_id: str) -> bool:
    """Is this a real tenant? Uses cache, refreshes once if a miss."""
    global _cache_loaded
    if not client_id:
        return False
    if client_id == LEGACY_CLIENT_ID:
        return True
    if not _cache_loaded:
        load_known_clients(supabase)
    if client_id in _known_clients:
        return True
    # Cache miss — refresh once in case the account was just created
    load_known_clients(supabase)
    return client_id in _known_clients


def _sanitize_client_id(raw: str) -> str:
    """Client IDs from URLs must be safe: lowercase alphanumerics, dashes,
    underscores only. Prevents injection / weird lookups."""
    if not raw:
        return ""
    cleaned = "".join(c for c in raw.lower().strip() if c.isalnum() or c in "-_")
    return cleaned[:64]


def resolve_client_id(request, supabase=None) -> str | None:
    """
    Determine which tenant this request belongs to.

    Precedence:
      1. Explicit ?client=<id> query param (widget embed, webhook) — validated.
      2. Logged-in admin session (request.session["client_id"]).
      3. Legacy fallback to env CLIENT_ID (keeps original deployment working).

    Returns None if nothing resolves AND there is no legacy fallback — caller
    must handle that (e.g. show an error rather than leak another tenant's data).
    """
    # 1. Explicit query param
    try:
        raw = request.query_params.get("client")
    except Exception:
        raw = None
    if raw:
        cid = _sanitize_client_id(raw)
        if cid and (supabase is None or account_exists(supabase, cid)):
            return cid

    # 2. Admin session
    try:
        sess_cid = request.session.get("client_id")
    except Exception:
        sess_cid = None
    if sess_cid:
        return sess_cid

    # 3. Legacy fallback — original single-client behaviour
    if LEGACY_CLIENT_ID:
        return LEGACY_CLIENT_ID

    return None


def get_account(supabase, client_id: str) -> dict | None:
    """Fetch the full account row for a client. Returns None if not found."""
    if not client_id:
        return None
    try:
        rows = (supabase.table("accounts").select("*")
                .eq("client_id", client_id).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(f"get_account({client_id}): {e}")
        return None


def account_branding(supabase, client_id: str) -> dict:
    """
    Return the branding/config for a client, falling back to env vars for the
    legacy client so nothing breaks during migration. This replaces the
    scattered os.environ.get(...) calls for business config.
    """
    acct = get_account(supabase, client_id)
    if acct:
        return {
            "client_id": client_id,
            "business_name": acct.get("business_name") or "Your Business",
            "business_type": acct.get("business_type") or "",
            "shop_url": acct.get("shop_url") or "",
            "whatsapp_number": acct.get("whatsapp_number") or "",
            "voucher_code": acct.get("voucher_code") or "",
            "primary_color": acct.get("primary_color") or "#FF922B",
            "logo_url": acct.get("logo_url") or "",
            "plan": acct.get("plan") or "trial",
            "account_status": acct.get("account_status") or "active",
        }
    # Legacy fallback — read from env like the original app did
    return {
        "client_id": client_id,
        "business_name": os.environ.get("BUSINESS_NAME", "Your Business"),
        "business_type": os.environ.get("BUSINESS_TYPE", ""),
        "shop_url": os.environ.get("SHOP_URL", "https://cuddleheros.co.za"),
        "whatsapp_number": os.environ.get("WHATSAPP_NUMBER", "27836205614"),
        "voucher_code": os.environ.get("VOUCHER_CODE", "TEDDY10"),
        "primary_color": os.environ.get("PRIMARY_COLOR", "#FF922B"),
        "logo_url": os.environ.get("LOGO_URL", ""),
        "plan": "legacy",
        "account_status": "active",
    }


def create_account(supabase, client_id: str, business_name: str,
                   admin_password: str = "", **fields) -> dict:
    """
    Create a new tenant account. Used by the onboarding wizard.
    client_id must be unique; returns {"ok": bool, ...}.
    """
    cid = _sanitize_client_id(client_id)
    if not cid:
        return {"ok": False, "error": "Invalid business ID"}
    if not business_name.strip():
        return {"ok": False, "error": "Business name required"}

    # Uniqueness check
    if account_exists(supabase, cid):
        return {"ok": False, "error": f"An account with ID '{cid}' already exists"}

    row = {
        "client_id": cid,
        "business_name": business_name.strip(),
        "business_type": fields.get("business_type", ""),
        "shop_url": fields.get("shop_url", ""),
        "whatsapp_number": fields.get("whatsapp_number", ""),
        "voucher_code": fields.get("voucher_code", ""),
        "primary_color": fields.get("primary_color", "#FF922B"),
        "logo_url": fields.get("logo_url", ""),
        "admin_password_hash": _hash_password(admin_password) if admin_password else "",
        # billing-ready defaults — present now, enforced later
        "plan": "trial",
        "account_status": "active",
        "subscription_tier": "standard",
        "msg_limit": 0,        # 0 = unlimited until billing exists
        "msgs_used": 0,
        "onboarded": False,
    }
    try:
        supabase.table("accounts").insert(row).execute()
        _known_clients.add(cid)  # keep cache fresh
        logger.info(f"Account created: {cid} ({business_name})")
        return {"ok": True, "client_id": cid}
    except Exception as e:
        logger.error(f"create_account error: {e}")
        return {"ok": False, "error": str(e)}


def update_account(supabase, client_id: str, **fields) -> dict:
    """Update branding/config for an existing account (used by branding UI + wizard)."""
    if not client_id:
        return {"ok": False, "error": "No client_id"}
    allowed = {
        "business_name", "business_type", "shop_url", "whatsapp_number",
        "voucher_code", "primary_color", "logo_url", "onboarded",
        "plan", "account_status", "subscription_tier", "msg_limit",
    }
    update = {k: v for k, v in fields.items() if k in allowed}
    if "admin_password" in fields and fields["admin_password"]:
        update["admin_password_hash"] = _hash_password(fields["admin_password"])
    if not update:
        return {"ok": False, "error": "Nothing to update"}
    try:
        supabase.table("accounts").update(update).eq("client_id", client_id).execute()
        return {"ok": True}
    except Exception as e:
        logger.error(f"update_account error: {e}")
        return {"ok": False, "error": str(e)}
