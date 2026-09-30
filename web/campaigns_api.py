"""Campaigns: create from a matched pool, run the creator pipeline, track live posts, dashboard."""
from __future__ import annotations

import re

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import Ctx, require
from billing_api import bill_campaign, fee_for, unbilled
from creator_pipeline.config import YOUTUBE_API_KEY
from creators_api import clean, org_conn, run_match
from platform_db import COMMITTED, PIPELINE, STATUS_LABEL, db, dumps, loads, log, now_iso, rows

router = APIRouter(prefix="/api")


def _campaign(conn, ctx: Ctx, campaign_id: int) -> dict:
    c = conn.execute("SELECT * FROM campaigns WHERE id = ? AND org_id = ?", (campaign_id, ctx.org_id)).fetchone()
    if not c:
        raise HTTPException(404, "Campaign not found")
    return dict(c)


def _cc(conn, ctx: Ctx, cc_id: int) -> tuple[dict, dict]:
    r = conn.execute("""SELECT cc.*, c.org_id, c.name AS campaign_name, c.status AS campaign_status FROM campaign_creators cc
                        JOIN campaigns c ON c.id = cc.campaign_id WHERE cc.id = ?""", (cc_id,)).fetchone()
    if not r or r["org_id"] != ctx.org_id:
        raise HTTPException(404, "Not found")
    return dict(r), _campaign(conn, ctx, r["campaign_id"])


def _latest_metrics(conn, cc_ids: list[int]) -> dict[int, dict]:
    if not cc_ids:
        return {}
    marks = ",".join("?" * len(cc_ids))
    out = {}
    for r in conn.execute(f"""SELECT * FROM post_metrics WHERE id IN (
                                SELECT MAX(id) FROM post_metrics WHERE cc_id IN ({marks}) GROUP BY cc_id)""", cc_ids):
        out[r["cc_id"]] = dict(r)
    return out


def _kpis(creators: list[dict], campaign: dict) -> dict:
    active = [c for c in creators if c["status"] != "dropped"]
    committed = [c for c in active if c["status"] in COMMITTED]
    live = [c for c in active if c["status"] in ("live", "completed")]
    views = sum((c["metrics"] or {}).get("views") or 0 for c in live)
    eng = sum(((c["metrics"] or {}).get("likes") or 0) + ((c["metrics"] or {}).get("comments") or 0)
              + ((c["metrics"] or {}).get("shares") or 0) + ((c["metrics"] or {}).get("saves") or 0) for c in live)
    spend = sum((c["agreed_fee"] if c["agreed_fee"] is not None else c["quoted_fee"] or 0) for c in committed)
    live_spend = sum((c["agreed_fee"] if c["agreed_fee"] is not None else c["quoted_fee"] or 0)
                     for c in live if (c["metrics"] or {}).get("views"))
    est_views = sum(c["est_views"] or 0 for c in committed)
    est_spend = sum((c["agreed_fee"] if c["agreed_fee"] is not None else c["quoted_fee"] or 0) for c in committed)
    return {
        "creators": len(active), "committed": len(committed), "live": len(live),
        "by_status": {s: sum(1 for c in creators if c["status"] == s) for s in PIPELINE + ["dropped"]},
        "budget": campaign["budget"], "committed_spend": spend,
        "views": views, "engagements": eng, "er": round(100 * eng / views, 2) if views else None,
        "actual_cpv": round(live_spend / views, 2) if views else None,
        "est_views": est_views, "est_cpv": round(est_spend / est_views, 2) if est_views else None,
    }


def _campaign_summary(conn, c: dict) -> dict:
    creators = rows(conn.execute("SELECT * FROM campaign_creators WHERE campaign_id = ?", (c["id"],)))
    latest = _latest_metrics(conn, [x["id"] for x in creators])
    for x in creators:
        x["metrics"] = latest.get(x["id"])
    return dict(c, kpis=_kpis(creators, c), brief=loads(c["brief_json"], {}))


def _creator_row(p: dict, now: str, campaign_id: int) -> tuple:
    return (campaign_id, p["creator_id"], p.get("name"), p.get("handle"), p.get("primary_platform"), p.get("profile_url"),
            p.get("city"), p.get("niche"), p.get("followers"), p.get("er"), p.get("est_views"), p.get("fit"),
            dumps(p.get("reasons") or []), p.get("cost"), None, "shortlisted", now, now)


INSERT_CC = """INSERT INTO campaign_creators (campaign_id, creator_id, name, handle, platform, profile_url, city,
    niche, followers, er, est_views, fit, reasons_json, quoted_fee, agreed_fee, status, added_at, updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING"""


# ------------------------------------------------------------------ campaigns

class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    brief: dict
    batches: list[int] | None = None
    creators: list[dict] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None


@router.get("/campaigns")
def list_campaigns(ctx: Ctx = Depends(require)):
    with db() as conn:
        cs = rows(conn.execute("SELECT * FROM campaigns WHERE org_id = ? ORDER BY id DESC", (ctx.org_id,)))
        return clean([_campaign_summary(conn, c) for c in cs])


@router.post("/campaigns")
def create_campaign(req: CampaignIn, ctx: Ctx = Depends(require)):
    b = req.brief
    now = now_iso()
    with db() as conn:
        cid = conn.execute(
            "INSERT INTO campaigns (org_id, name, brand, product, objective, deliverable, budget, brief_json, scope_json,"
            " status, start_date, end_date, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (ctx.org_id, req.name.strip(), b.get("brand"), b.get("product"), b.get("objective"), b.get("deliverable"),
             b.get("budget"), dumps(b), dumps(req.batches), "draft", req.start_date, req.end_date, ctx.user_id, now),
        ).fetchone()[0]
        conn.executemany(INSERT_CC, [_creator_row(p, now, cid) for p in req.creators])
        log(conn, ctx.org_id, f"{ctx.name} created campaign “{req.name.strip()}” with {len(req.creators)} shortlisted creators",
            ctx.user_id, cid)
    return {"id": cid}


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, ctx: Ctx = Depends(require)):
    with db() as conn:
        c = _campaign(conn, ctx, campaign_id)
        creators = rows(conn.execute("SELECT * FROM campaign_creators WHERE campaign_id = ? ORDER BY fit DESC NULLS LAST, id",
                                     (campaign_id,)))
        latest = _latest_metrics(conn, [x["id"] for x in creators])
        for x in creators:
            x["metrics"] = latest.get(x["id"])
            x["reasons"] = loads(x.pop("reasons_json"), [])
        series = rows(conn.execute("""SELECT substr(pm.recorded_at, 1, 10) AS day, pm.cc_id, MAX(pm.views) AS views
                                       FROM post_metrics pm JOIN campaign_creators cc ON cc.id = pm.cc_id
                                       WHERE cc.campaign_id = ? GROUP BY day, pm.cc_id ORDER BY day""", (campaign_id,)))
        activity = rows(conn.execute("SELECT a.at, a.text FROM activity a WHERE a.campaign_id = ? ORDER BY a.id DESC LIMIT 40",
                                     (campaign_id,)))
        invoices = rows(conn.execute("SELECT id, number, status, total, issued_at FROM invoices WHERE campaign_id = ? ORDER BY id",
                                     (campaign_id,)))
        pending_bill = len(unbilled(conn, campaign_id))
        fee = fee_for(conn, ctx.org_id)
    # cumulative views per day: carry each post's last known value forward
    days = sorted({s["day"] for s in series})
    last, timeline = {}, []
    for d in days:
        for s in series:
            if s["day"] == d:
                last[s["cc_id"]] = s["views"] or 0
        timeline.append({"day": d, "views": sum(last.values())})
    return clean(dict(c, brief=loads(c["brief_json"], {}), creators=creators, kpis=_kpis(creators, c),
                      timeline=timeline, activity=activity, invoices=invoices, unbilled=pending_bill,
                      fee_per_creator=fee, pipeline=[{"key": k, "label": STATUS_LABEL[k]} for k in PIPELINE]))


class CampaignPatch(BaseModel):
    name: str | None = None
    budget: float | None = None
    start_date: str | None = None
    end_date: str | None = None


@router.patch("/campaigns/{campaign_id}")
def update_campaign(campaign_id: int, req: CampaignPatch, ctx: Ctx = Depends(require)):
    with db() as conn:
        _campaign(conn, ctx, campaign_id)
        for k, v in req.model_dump(exclude_none=True).items():
            conn.execute(f"UPDATE campaigns SET {k} = ? WHERE id = ?", (v, campaign_id))
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/launch")
def launch(campaign_id: int, ctx: Ctx = Depends(require)):
    return campaign_action(campaign_id, "launch", ctx)


@router.post("/campaigns/{campaign_id}/complete")
def complete(campaign_id: int, ctx: Ctx = Depends(require)):
    return campaign_action(campaign_id, "complete", ctx)


@router.post("/campaigns/{campaign_id}/cancel")
def cancel(campaign_id: int, ctx: Ctx = Depends(require)):
    return campaign_action(campaign_id, "cancel", ctx)


def campaign_action(campaign_id: int, action: str, ctx: Ctx):
    with db() as conn:
        c = _campaign(conn, ctx, campaign_id)
        now = now_iso()
        invoice = None
        if action == "launch":
            if c["status"] != "draft":
                raise HTTPException(400, "Only draft campaigns can be launched")
            conn.execute("UPDATE campaigns SET status = 'active', launched_at = ?, start_date = COALESCE(start_date, ?)"
                         " WHERE id = ?", (now, now[:10], campaign_id))
            log(conn, ctx.org_id, f"{ctx.name} launched the campaign", ctx.user_id, campaign_id)
            invoice = bill_campaign(conn, dict(c, status="active"), ctx.user_id)
        elif action == "complete":
            if c["status"] != "active":
                raise HTTPException(400, "Only active campaigns can be completed")
            invoice = bill_campaign(conn, c, ctx.user_id)
            conn.execute("UPDATE campaigns SET status = 'completed', closed_at = ?, end_date = COALESCE(end_date, ?)"
                         " WHERE id = ?", (now, now[:10], campaign_id))
            log(conn, ctx.org_id, f"{ctx.name} marked the campaign completed", ctx.user_id, campaign_id)
        else:
            if c["status"] in ("completed", "cancelled"):
                raise HTTPException(400, f"Campaign is already {c['status']}")
            conn.execute("UPDATE campaigns SET status = 'cancelled', closed_at = ? WHERE id = ?", (now, campaign_id))
            log(conn, ctx.org_id, f"{ctx.name} cancelled the campaign", ctx.user_id, campaign_id)
    return {"ok": True, "invoice": invoice}


class AddCreators(BaseModel):
    creators: list[dict]


@router.post("/campaigns/{campaign_id}/creators")
def add_creators(campaign_id: int, req: AddCreators, ctx: Ctx = Depends(require)):
    with db() as conn:
        c = _campaign(conn, ctx, campaign_id)
        if c["status"] in ("completed", "cancelled"):
            raise HTTPException(400, f"Campaign is {c['status']}")
        now = now_iso()
        added = max(0, conn.executemany(INSERT_CC, [_creator_row(p, now, campaign_id) for p in req.creators]).rowcount)
        if added:
            log(conn, ctx.org_id, f"{ctx.name} added {added} creator(s): {', '.join(p.get('name') or '' for p in req.creators[:4])}",
                ctx.user_id, campaign_id)
    return {"added": added}


@router.get("/campaigns/{campaign_id}/suggestions")
def suggestions(campaign_id: int, ctx: Ctx = Depends(require)):
    with db() as conn:
        c = _campaign(conn, ctx, campaign_id)
        have = [r["creator_id"] for r in conn.execute("SELECT creator_id FROM campaign_creators WHERE campaign_id = ?", (campaign_id,))]
    brief = dict(loads(c["brief_json"], {}), count=12, budget=0)
    res = run_match(ctx.org_id, brief, loads(c["scope_json"]), have)
    return clean({"suggestions": (res["pool"] + res["alternates"])[:16]})


# ------------------------------------------------------------------ creators in a campaign

class CCPatch(BaseModel):
    status: str | None = None
    agreed_fee: float | None = None
    due_date: str | None = None
    post_url: str | None = None
    notes: str | None = None


@router.patch("/campaign-creators/{cc_id}")
def update_cc(cc_id: int, req: CCPatch, ctx: Ctx = Depends(require)):
    data = req.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in PIPELINE + ["dropped"]:
        raise HTTPException(400, "Unknown status")
    with db() as conn:
        cc, c = _cc(conn, ctx, cc_id)
        if c["status"] in ("completed", "cancelled"):
            raise HTTPException(400, f"Campaign is {c['status']}")
        if data.get("status") == "dropped" and cc["billed"]:
            raise HTTPException(400, "This creator was already billed as confirmed - mark as completed instead")
        for k, v in data.items():
            conn.execute(f"UPDATE campaign_creators SET {k} = ?, updated_at = ? WHERE id = ?", (v, now_iso(), cc_id))
        if "status" in data and data["status"] != cc["status"]:
            log(conn, ctx.org_id, f"{cc['name']}: {STATUS_LABEL[cc['status']]} → {STATUS_LABEL[data['status']]}",
                ctx.user_id, c["id"])
        if data.get("agreed_fee") is not None and data["agreed_fee"] != cc["agreed_fee"]:
            log(conn, ctx.org_id, f"{cc['name']}: fee agreed at ₹{data['agreed_fee']:,.0f}", ctx.user_id, c["id"])
        if data.get("post_url") and data["post_url"] != cc["post_url"]:
            log(conn, ctx.org_id, f"{cc['name']}: post link added", ctx.user_id, c["id"])
    return {"ok": True}


class MetricsIn(BaseModel):
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)


@router.post("/campaign-creators/{cc_id}/metrics")
def add_metrics(cc_id: int, req: MetricsIn, ctx: Ctx = Depends(require)):
    with db() as conn:
        cc, c = _cc(conn, ctx, cc_id)
        conn.execute("INSERT INTO post_metrics (cc_id, recorded_at, views, likes, comments, shares, saves, source, recorded_by)"
                     " VALUES (?,?,?,?,?,?,?,?,?)", (cc_id, now_iso(), req.views, req.likes, req.comments, req.shares,
                                                     req.saves, "manual", ctx.user_id))
        if cc["status"] in ("confirmed", "submitted"):
            conn.execute("UPDATE campaign_creators SET status = 'live', updated_at = ? WHERE id = ?", (now_iso(), cc_id))
        log(conn, ctx.org_id, f"{cc['name']}: stats updated — {req.views or 0:,} views", ctx.user_id, c["id"])
    return {"ok": True}


_YT_VIDEO = re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|live/|embed/))([A-Za-z0-9_-]{11})")


@router.post("/campaign-creators/{cc_id}/fetch")
def fetch_metrics(cc_id: int, ctx: Ctx = Depends(require)):
    """Pull live stats for a YouTube post link (1 quota unit). Instagram needs a data provider / creator auth."""
    with db() as conn:
        cc, c = _cc(conn, ctx, cc_id)
    m = _YT_VIDEO.search(cc["post_url"] or "")
    if not m:
        raise HTTPException(400, "Auto-fetch works for YouTube video links; enter Instagram stats manually for now")
    if not YOUTUBE_API_KEY:
        raise HTTPException(400, "YouTube API key not configured on the server")
    r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                     params={"part": "statistics", "id": m.group(1), "key": YOUTUBE_API_KEY}, timeout=20)
    items = r.json().get("items") if r.ok else None
    if not items:
        raise HTTPException(400, "YouTube didn't return this video (private, deleted, or wrong link)")
    st = items[0]["statistics"]
    as_int = lambda k: int(st[k]) if k in st else None  # noqa: E731
    with db() as conn:
        conn.execute("INSERT INTO post_metrics (cc_id, recorded_at, views, likes, comments, source, recorded_by)"
                     " VALUES (?,?,?,?,?,?,?)", (cc_id, now_iso(), as_int("viewCount"), as_int("likeCount"),
                                                 as_int("commentCount"), "youtube_api", ctx.user_id))
        if cc["status"] in ("confirmed", "submitted"):
            conn.execute("UPDATE campaign_creators SET status = 'live', updated_at = ? WHERE id = ?", (now_iso(), cc_id))
        log(conn, ctx.org_id, f"{cc['name']}: YouTube stats fetched — {as_int('viewCount') or 0:,} views", ctx.user_id, c["id"])
    return {"ok": True, "views": as_int("viewCount")}


@router.get("/campaign-creators/{cc_id}/metrics")
def metrics_history(cc_id: int, ctx: Ctx = Depends(require)):
    with db() as conn:
        _cc(conn, ctx, cc_id)
        return rows(conn.execute("SELECT * FROM post_metrics WHERE cc_id = ? ORDER BY recorded_at, id", (cc_id,)))


# ------------------------------------------------------------------ dashboard

@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(require)):
    with db() as conn:
        cs = [_campaign_summary(conn, c) for c in
              rows(conn.execute("SELECT * FROM campaigns WHERE org_id = ? ORDER BY id DESC", (ctx.org_id,)))]
        activity = rows(conn.execute("SELECT at, text, campaign_id FROM activity WHERE org_id = ? ORDER BY id DESC LIMIT 12",
                                     (ctx.org_id,)))
        outstanding = conn.execute("SELECT COALESCE(SUM(total),0) FROM invoices WHERE org_id = ? AND status = 'issued'",
                                   (ctx.org_id,)).fetchone()[0]
        members = conn.execute("SELECT COUNT(*) FROM memberships WHERE org_id = ?", (ctx.org_id,)).fetchone()[0]
    conn = org_conn(ctx.org_id)
    try:
        library = conn.execute("SELECT COUNT(*) FROM creators").fetchone()[0]
        imports = conn.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0]
    finally:
        conn.close()
    active = [c for c in cs if c["status"] == "active"]
    return clean({
        "user": {"name": ctx.name, "org": ctx.org_name, "job_title": ctx.job_title},
        "library": library, "imports": imports, "members": members,
        "campaigns": {"total": len(cs), "active": len(active), "draft": sum(c["status"] == "draft" for c in cs),
                      "completed": sum(c["status"] == "completed" for c in cs)},
        "views": sum(c["kpis"]["views"] for c in cs),
        "live_posts": sum(c["kpis"]["live"] for c in cs),
        "committed_spend": sum(c["kpis"]["committed_spend"] for c in active),
        "outstanding": outstanding,
        "recent": cs[:6], "activity": activity,
    })
