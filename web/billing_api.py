"""Billing: a platform service fee per creator per campaign, + GST.

Rule: you pay only for creators who confirm. Each confirmed creator is billed once per campaign -
on launch for everyone already confirmed, then (on "Bill now" or when the campaign completes) for
creators confirmed later. Dropped-before-confirmation creators are never billed.
Payments run in TEST MODE here; plug a gateway (e.g. Razorpay) into pay_invoice().
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from auth import Ctx, require
from creator_pipeline.config import FEE_PER_CREATOR, GST_RATE
from platform_db import COMMITTED, db, dumps, loads, log, now_iso, rows

router = APIRouter()
DUE_DAYS = 7


def fee_for(conn, org_id: int) -> int:
    r = conn.execute("SELECT fee_per_creator FROM orgs WHERE id = ?", (org_id,)).fetchone()
    return int(r["fee_per_creator"] or FEE_PER_CREATOR)


def _next_number(conn, org_id: int) -> str:
    year = datetime.now(timezone.utc).year
    n = conn.execute("SELECT COUNT(*) FROM invoices WHERE org_id = ? AND number LIKE ?",
                     (org_id, f"CA-{year}-{org_id:03d}-%")).fetchone()[0]
    return f"CA-{year}-{org_id:03d}-{n + 1:04d}"


def unbilled(conn, campaign_id: int) -> list[dict]:
    marks = ",".join("?" * len(COMMITTED))
    return rows(conn.execute(f"""SELECT id, name, handle, platform FROM campaign_creators
                                 WHERE campaign_id = ? AND billed = 0 AND status IN ({marks})""",
                             (campaign_id, *COMMITTED)))


def bill_campaign(conn, campaign: dict, user_id: int | None = None) -> dict | None:
    """Invoice every confirmed-but-unbilled creator on the campaign. Returns the invoice or None."""
    todo = unbilled(conn, campaign["id"])
    if not todo:
        return None
    org = conn.execute("SELECT * FROM orgs WHERE id = ?", (campaign["org_id"],)).fetchone()
    fee = fee_for(conn, campaign["org_id"])
    subtotal = fee * len(todo)
    tax = round(subtotal * GST_RATE, 2)
    total = round(subtotal + tax, 2)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    number = _next_number(conn, campaign["org_id"])
    inv_id = conn.execute(
        "INSERT INTO invoices (org_id, campaign_id, number, status, issued_at, due_at, subtotal, tax_rate, tax, total,"
        " bill_to_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (campaign["org_id"], campaign["id"], number, "issued", now.isoformat(),
         (now + timedelta(days=DUE_DAYS)).isoformat(), subtotal, GST_RATE, tax, total,
         dumps({"name": org["name"], "email": org["billing_email"], "gstin": org["gstin"], "address": org["address"]})),
    ).lastrowid
    conn.execute(
        "INSERT INTO invoice_lines (invoice_id, description, qty, unit_price, amount, detail_json) VALUES (?,?,?,?,?,?)",
        (inv_id, f"Platform service fee — {campaign['name']} ({len(todo)} confirmed creator{'s' if len(todo) != 1 else ''})",
         len(todo), fee, subtotal, dumps([{"name": t["name"], "handle": t["handle"], "platform": t["platform"]} for t in todo])))
    conn.executemany("UPDATE campaign_creators SET billed = 1 WHERE id = ?", [(t["id"],) for t in todo])
    log(conn, campaign["org_id"], f"Invoice {number} issued: {len(todo)} creators × ₹{fee:,} + GST = ₹{total:,.0f}",
        user_id, campaign["id"])
    return {"id": inv_id, "number": number, "total": total, "creators": len(todo)}


def _invoice(conn, org_id: int, invoice_id: int) -> dict:
    inv = conn.execute("SELECT i.*, c.name AS campaign_name FROM invoices i LEFT JOIN campaigns c ON c.id = i.campaign_id"
                       " WHERE i.id = ? AND i.org_id = ?", (invoice_id, org_id)).fetchone()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    out = dict(inv)
    out["bill_to"] = loads(out.pop("bill_to_json"), {})
    out["lines"] = [dict(l, detail=loads(l["detail_json"], [])) for l in
                    rows(conn.execute("SELECT * FROM invoice_lines WHERE invoice_id = ?", (invoice_id,)))]
    out["payments"] = rows(conn.execute("SELECT * FROM payments WHERE invoice_id = ?", (invoice_id,)))
    return out


# ------------------------------------------------------------------ routes

@router.get("/api/billing")
def billing(ctx: Ctx = Depends(require)):
    with db() as conn:
        invoices = rows(conn.execute("""SELECT i.id, i.number, i.status, i.issued_at, i.due_at, i.paid_at, i.subtotal,
                                               i.tax, i.total, c.name AS campaign_name, c.id AS campaign_id,
                                               (SELECT SUM(qty) FROM invoice_lines l WHERE l.invoice_id = i.id) AS creators
                                        FROM invoices i LEFT JOIN campaigns c ON c.id = i.campaign_id
                                        WHERE i.org_id = ? ORDER BY i.id DESC""", (ctx.org_id,)))
        pending = []
        for c in rows(conn.execute("SELECT * FROM campaigns WHERE org_id = ? AND status = 'active'", (ctx.org_id,))):
            n = len(unbilled(conn, c["id"]))
            if n:
                pending.append({"campaign_id": c["id"], "campaign_name": c["name"], "creators": n})
        fee = fee_for(conn, ctx.org_id)
    now = now_iso()
    return {
        "fee_per_creator": fee, "gst_rate": GST_RATE, "test_mode": True,
        "invoices": invoices, "unbilled": pending,
        "outstanding": sum(i["total"] for i in invoices if i["status"] == "issued"),
        "overdue": sum(i["total"] for i in invoices if i["status"] == "issued" and (i["due_at"] or "") < now),
        "paid": sum(i["total"] for i in invoices if i["status"] == "paid"),
        "creators_billed": sum(i["creators"] or 0 for i in invoices if i["status"] != "void"),
    }


@router.get("/api/invoices/{invoice_id}")
def invoice(invoice_id: int, ctx: Ctx = Depends(require)):
    with db() as conn:
        return _invoice(conn, ctx.org_id, invoice_id)


@router.post("/api/invoices/{invoice_id}/pay")
def pay_invoice(invoice_id: int, ctx: Ctx = Depends(require)):
    """TEST MODE: records a successful payment. Swap in a Razorpay order + webhook for real payments."""
    with db() as conn:
        inv = _invoice(conn, ctx.org_id, invoice_id)
        if inv["status"] == "paid":
            return {"ok": True, "already_paid": True}
        if inv["status"] != "issued":
            raise HTTPException(400, f"Invoice is {inv['status']}")
        ref = f"TEST-{invoice_id:05d}-{int(datetime.now().timestamp())}"
        conn.execute("INSERT INTO payments (invoice_id, amount, method, reference, paid_at, paid_by) VALUES (?,?,?,?,?,?)",
                     (invoice_id, inv["total"], "test", ref, now_iso(), ctx.user_id))
        conn.execute("UPDATE invoices SET status = 'paid', paid_at = ? WHERE id = ?", (now_iso(), invoice_id))
        log(conn, ctx.org_id, f"{ctx.name} paid invoice {inv['number']} (₹{inv['total']:,.0f}, test mode)", ctx.user_id,
            inv["campaign_id"])
    return {"ok": True, "reference": ref}


@router.post("/api/campaigns/{campaign_id}/bill")
def bill_now(campaign_id: int, ctx: Ctx = Depends(require)):
    with db() as conn:
        c = conn.execute("SELECT * FROM campaigns WHERE id = ? AND org_id = ?", (campaign_id, ctx.org_id)).fetchone()
        if not c:
            raise HTTPException(404, "Campaign not found")
        if c["status"] not in ("active", "completed"):
            raise HTTPException(400, "Launch the campaign first")
        inv = bill_campaign(conn, dict(c), ctx.user_id)
    return {"invoice": inv}


@router.get("/invoice/{invoice_id}", response_class=HTMLResponse)
def invoice_page(invoice_id: int, ctx: Ctx = Depends(require)):
    """Printable invoice (browser 'Save as PDF')."""
    with db() as conn:
        inv = _invoice(conn, ctx.org_id, invoice_id)
    e = html.escape
    money = lambda x: f"₹{x:,.2f}"  # noqa: E731
    lines = "".join(
        f"<tr><td>{e(l['description'])}<div class='d'>{e(', '.join(d['name'] for d in l['detail']))}</div></td>"
        f"<td>{l['qty']}</td><td>{money(l['unit_price'])}</td><td>{money(l['amount'])}</td></tr>" for l in inv["lines"])
    b = inv["bill_to"]
    status = {"paid": "PAID", "issued": "DUE", "void": "VOID"}[inv["status"]]
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Invoice {e(inv['number'])}</title>
<style>body{{font:14px/1.5 Inter,system-ui,sans-serif;color:#1d1433;max-width:760px;margin:40px auto;padding:0 20px}}
h1{{font-size:28px;margin:0}}.top{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #ff3d8b;padding-bottom:16px}}
.brand{{font-weight:800;font-size:20px}}.muted{{color:#6b6285}}table{{width:100%;border-collapse:collapse;margin-top:24px}}
th,td{{text-align:left;padding:10px 8px;border-bottom:1px solid #eee;vertical-align:top}}th:nth-child(n+2),td:nth-child(n+2){{text-align:right}}
.d{{color:#6b6285;font-size:12px;margin-top:4px}}.tot td{{border:0;padding:4px 8px}}.grand td{{font-weight:800;font-size:18px;border-top:2px solid #1d1433}}
.stamp{{display:inline-block;padding:4px 12px;border:2px solid {'#1a9e5a' if inv['status'] == 'paid' else '#d97706'};color:{'#1a9e5a' if inv['status'] == 'paid' else '#d97706'};font-weight:800;border-radius:6px;letter-spacing:.1em}}
.note{{margin-top:30px;font-size:12px;color:#6b6285}}@media print{{button{{display:none}}}}</style></head><body>
<div class="top"><div><div class="brand">◉ Creator Atlas</div><div class="muted">Creator intelligence &amp; campaign platform</div></div>
<div style="text-align:right"><h1>Invoice</h1><div>{e(inv['number'])}</div><div class="stamp">{status}</div></div></div>
<p><b>Billed to</b><br>{e(b.get('name') or '')}<br>{e(b.get('address') or '')}<br>{e(b.get('email') or '')}
{('<br>GSTIN: ' + e(b['gstin'])) if b.get('gstin') else ''}</p>
<p class="muted">Issued {inv['issued_at'][:10]} · Due {(inv['due_at'] or '')[:10]}{(' · Paid ' + inv['paid_at'][:10]) if inv['paid_at'] else ''}
{(' · Campaign: ' + e(inv['campaign_name'])) if inv['campaign_name'] else ''}</p>
<table><tr><th>Description</th><th>Qty</th><th>Rate</th><th>Amount</th></tr>{lines}
<tr class="tot"><td></td><td></td><td>Subtotal</td><td>{money(inv['subtotal'])}</td></tr>
<tr class="tot"><td></td><td></td><td>GST {inv['tax_rate'] * 100:.0f}%</td><td>{money(inv['tax'])}</td></tr>
<tr class="grand"><td></td><td></td><td>Total</td><td>{money(inv['total'])}</td></tr></table>
<p class="note">Service fee is charged per creator who confirms on a campaign. Creator fees are paid by the brand directly
and are not part of this invoice.{' Payment recorded in TEST MODE (ref ' + e(inv['payments'][0]['reference']) + ').' if inv['payments'] else ''}</p>
<button onclick="print()">Print / save as PDF</button></body></html>"""
