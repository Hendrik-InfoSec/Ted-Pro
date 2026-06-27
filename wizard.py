"""
wizard.py — Self-serve onboarding wizard for TedPro.

The flow that turns TedPro from "a chatbot I set up by hand for each client"
into "software a business signs up for and configures itself in minutes".

Steps a new business goes through:
  1. Business basics  → creates the account row + a unique client_id + password
  2. Branding         → shop URL, WhatsApp, voucher code, colour
  3. Products         → reuses the existing CSV upload (scoped to new client)
  4. FAQs             → reuses the existing FAQ flow (scoped to new client)
  5. Embed code       → their unique one-line script to paste on their site

This module renders the wizard HTML and provides helpers. The actual account
writes go through tenancy.create_account / tenancy.update_account so all the
tenant logic stays in one place.
"""

from __future__ import annotations
import re
import logging

logger = logging.getLogger(__name__)


def suggest_client_id(business_name: str) -> str:
    """Turn 'Acme Plush Toys!' into 'acmeplushtoys' — a clean URL-safe id."""
    base = re.sub(r"[^a-z0-9]+", "", (business_name or "").lower())
    return base[:32] or "business"


def render_wizard(base_url: str, step: int = 1, account: dict | None = None,
                  error: str = "") -> str:
    """
    Render the wizard as a full standalone page. `step` controls which panel
    shows. `account` carries the in-progress account (after step 1) so later
    steps know the client_id.
    """
    account = account or {}
    cid = account.get("client_id", "")
    biz = account.get("business_name", "")
    primary = account.get("primary_color", "#FF922B")

    err_html = (
        f"<div style='background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;"
        f"padding:10px 14px;margin-bottom:14px;font-size:13px;color:#991b1b'>{error}</div>"
        if error else ""
    )

    # Progress bar
    steps = ["Business", "Branding", "Products", "FAQs", "Go Live"]
    dots = ""
    for i, label in enumerate(steps, 1):
        done = i < step
        active = i == step
        bg = "#16a34a" if done else ("#FF922B" if active else "#FFE4CC")
        color = "white" if (done or active) else "#8B6914"
        check = "\u2713" if done else str(i)
        dots += (
            f"<div style='display:flex;flex-direction:column;align-items:center;flex:1'>"
            f"<div style='width:30px;height:30px;border-radius:50%;background:{bg};color:{color};"
            f"display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px'>{check}</div>"
            f"<div style='font-size:10px;color:#8B6914;margin-top:4px;text-align:center'>{label}</div></div>"
        )
        if i < len(steps):
            line_bg = "#16a34a" if done else "#FFE4CC"
            dots += f"<div style='flex:1;height:2px;background:{line_bg};margin-top:15px'></div>"
    progress = f"<div style='display:flex;align-items:flex-start;margin-bottom:28px'>{dots}</div>"

    body = _step_body(step, base_url, cid, biz, primary)

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Set up your TedPro assistant</title>
<link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Quicksand',sans-serif;background:#FFF9F4;min-height:100vh;padding:24px}}
.card{{max-width:560px;margin:0 auto;background:white;border:1px solid #FFE4CC;border-radius:20px;padding:32px;box-shadow:0 4px 24px rgba(255,146,43,0.08)}}
input,select,textarea{{width:100%;padding:11px 14px;border:1px solid #FFD5A5;border-radius:10px;font-size:14px;font-family:inherit;margin-bottom:14px;outline:none;background:#FFFDFB}}
input:focus,textarea:focus{{border-color:#FF922B}}
label{{display:block;font-size:12px;font-weight:600;color:#8B6914;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px}}
.btn{{padding:12px 24px;background:#FF922B;color:white;border:none;border-radius:10px;font-weight:700;font-size:14px;cursor:pointer;font-family:inherit}}
.btn:hover{{background:#FF8419}}
.btn-ghost{{background:white;color:#8B6914;border:1px solid #FFD5A5}}
h1{{font-size:22px;color:#2D1B00;margin-bottom:6px}}
.sub{{font-size:13px;color:#8B6914;margin-bottom:24px}}
.hint{{font-size:11px;color:#8B6914;margin-top:-8px;margin-bottom:14px}}
code{{background:#FFF0DB;padding:2px 6px;border-radius:5px;font-size:12px;color:#c7440a}}
</style></head><body>
<div class="card">
<div style="text-align:center;margin-bottom:20px"><div style="font-size:40px">\U0001f9f8</div>
<div style="font-size:13px;font-weight:700;color:#FF922B;letter-spacing:.05em">TEDPRO SETUP</div></div>
{progress}
{err_html}
{body}
</div></body></html>"""


def _step_body(step: int, base_url: str, cid: str, biz: str, primary: str) -> str:
    if step == 1:
        return f"""
<h1>Let's set up your assistant</h1>
<p class="sub">Tell us about your business. This takes about 3 minutes.</p>
<form method="post" action="/setup/step1">
<label>Business name</label>
<input name="business_name" placeholder="e.g. Acme Plush Toys" value="{biz}" required>
<label>Business type (optional)</label>
<input name="business_type" placeholder="e.g. Online toy store">
<label>Admin password</label>
<input name="admin_password" type="password" placeholder="Choose a password to manage your assistant" required>
<p class="hint">You'll use this to log into your dashboard.</p>
<button class="btn" type="submit" style="width:100%">Continue &rarr;</button>
</form>"""

    if step == 2:
        return f"""
<h1>Brand your assistant</h1>
<p class="sub">How should Teddy represent <strong>{biz}</strong>?</p>
<form method="post" action="/setup/step2">
<input type="hidden" name="client_id" value="{cid}">
<label>Your shop / website URL</label>
<input name="shop_url" placeholder="https://yourstore.com">
<label>WhatsApp number (for handoffs)</label>
<input name="whatsapp_number" placeholder="27821234567">
<p class="hint">Country code, no + or spaces. Leave blank to skip WhatsApp handoff.</p>
<label>Welcome voucher code (optional)</label>
<input name="voucher_code" placeholder="e.g. WELCOME10">
<p class="hint">Offered to capture customer emails. Leave blank for none.</p>
<label>Brand colour</label>
<input name="primary_color" type="color" value="{primary}" style="height:48px;padding:4px">
<div style="display:flex;gap:10px;margin-top:8px">
<button class="btn" type="submit" style="flex:1">Continue &rarr;</button>
</div>
</form>"""

    if step == 3:
        return f"""
<h1>Add your products</h1>
<p class="sub">Upload your catalog so Teddy can answer pricing and stock questions accurately.</p>
<div style="background:#FFF9F4;border:1px dashed #FFD5A5;border-radius:12px;padding:20px;margin-bottom:16px">
<p style="font-size:13px;color:#5A3A1B;margin-bottom:12px">Upload a CSV with columns: <code>name</code>, <code>price</code>, and optionally category, currency, in_stock, description, size_cm, material, sku.</p>
<input type="file" id="prodcsv" accept=".csv" style="margin-bottom:10px">
<button class="btn" onclick="uploadProducts()" style="width:100%">Upload products</button>
<div id="prod-result" style="font-size:13px;margin-top:10px"></div>
</div>
<a href="/setup?step=4&client={cid}" style="display:block;text-align:center;font-size:13px;color:#8B6914;margin-bottom:8px">Skip for now &mdash; I'll add products later</a>
<form method="get" action="/setup"><input type="hidden" name="step" value="4"><input type="hidden" name="client" value="{cid}">
<button class="btn" type="submit" style="width:100%">Continue &rarr;</button></form>
<script>
function uploadProducts(){{
  var f=document.getElementById('prodcsv').files[0];
  if(!f){{document.getElementById('prod-result').innerHTML='<span style=color:#991b1b>Choose a CSV file first.</span>';return;}}
  var r=new FileReader();
  r.onload=function(e){{
    var fd=new FormData();fd.append('csv_data',e.target.result);fd.append('client_id','{cid}');
    document.getElementById('prod-result').textContent='Uploading...';
    fetch('/setup/upload-products',{{method:'POST',body:fd,credentials:'same-origin'}})
    .then(function(r){{return r.text();}}).then(function(h){{document.getElementById('prod-result').innerHTML=h;}})
    .catch(function(e){{document.getElementById('prod-result').innerHTML='<span style=color:#991b1b>'+e.message+'</span>';}});
  }};r.readAsText(f);
}}
</script>"""

    if step == 4:
        return f"""
<h1>Add a few FAQs</h1>
<p class="sub">Teach Teddy your common answers &mdash; shipping, returns, hours. You can add more later.</p>
<div id="faq-list"></div>
<div style="background:#FFF9F4;border:1px solid #FFE4CC;border-radius:12px;padding:16px;margin-bottom:16px">
<label>Question</label>
<input id="faq-q" placeholder="e.g. How long does delivery take?">
<label>Answer</label>
<textarea id="faq-a" rows="2" placeholder="e.g. We deliver in 3-5 business days nationwide."></textarea>
<button class="btn" onclick="addFaq()" style="width:100%">Add this FAQ</button>
<div id="faq-result" style="font-size:13px;margin-top:8px"></div>
</div>
<form method="get" action="/setup"><input type="hidden" name="step" value="5"><input type="hidden" name="client" value="{cid}">
<button class="btn" type="submit" style="width:100%">Finish &rarr;</button></form>
<script>
var faqCount=0;
function addFaq(){{
  var q=document.getElementById('faq-q').value.trim();
  var a=document.getElementById('faq-a').value.trim();
  var res=document.getElementById('faq-result');
  if(!q||!a){{res.innerHTML='<span style=color:#991b1b>Both question and answer are needed.</span>';return;}}
  var fd=new FormData();fd.append('question',q);fd.append('answer',a);fd.append('client_id','{cid}');
  fetch('/setup/add-faq',{{method:'POST',body:fd,credentials:'same-origin'}})
  .then(function(r){{return r.json();}}).then(function(d){{
    if(d.ok){{faqCount++;
      document.getElementById('faq-list').innerHTML+='<div style="background:#F0FFF4;border:1px solid #86EFAC;border-radius:8px;padding:8px 12px;margin-bottom:8px;font-size:13px;color:#166534">\u2713 '+q+'</div>';
      document.getElementById('faq-q').value='';document.getElementById('faq-a').value='';
      res.innerHTML='<span style=color:#166534>Added! ('+faqCount+' so far)</span>';
    }} else {{res.innerHTML='<span style=color:#991b1b>'+(d.error||'Failed')+'</span>';}}
  }}).catch(function(e){{res.innerHTML='<span style=color:#991b1b>'+e.message+'</span>';}});
}}
</script>"""

    # step 5 — go live: the embed code
    embed = f'<script src="{base_url}/embed.js?client={cid}"></script>'
    embed_esc = embed.replace("<", "&lt;").replace(">", "&gt;")
    return f"""
<h1>\U0001f389 You're live!</h1>
<p class="sub">Teddy is ready for <strong>{biz}</strong>. Add him to your website with this one line.</p>
<label>Your embed code</label>
<div style="position:relative">
<textarea id="embed" readonly rows="2" style="background:#2D1B00;color:#FFE4CC;font-family:monospace;font-size:12px;padding:14px">{embed_esc}</textarea>
<button class="btn" onclick="copyEmbed()" style="position:absolute;top:8px;right:8px;padding:6px 12px;font-size:12px">Copy</button>
</div>
<p class="hint">Paste this just before the closing &lt;/body&gt; tag on any page of your website.</p>
<div style="background:#FFF9F4;border:1px solid #FFE4CC;border-radius:12px;padding:16px;margin:16px 0">
<p style="font-size:13px;font-weight:700;color:#2D1B00;margin-bottom:8px">What's next?</p>
<p style="font-size:13px;color:#5A3A1B;line-height:1.6">
&bull; <a href="/admin?client={cid}" style="color:#FF922B">Open your dashboard</a> to see leads &amp; conversations<br>
&bull; <a href="/chat-widget?client={cid}" style="color:#FF922B" target="_blank">Test your assistant</a> right now<br>
&bull; Add more products or FAQs anytime from your dashboard</p>
</div>
<a href="/admin?client={cid}"><button class="btn" style="width:100%">Go to my dashboard &rarr;</button></a>
<script>
function copyEmbed(){{
  var t=document.getElementById('embed');t.select();
  document.execCommand('copy');
  event.target.textContent='Copied!';
  setTimeout(function(){{event.target.textContent='Copy';}},1500);
}}
</script>"""
