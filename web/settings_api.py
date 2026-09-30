"""Profile, company details, password, team members."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import (COMPANY_SIZES, INDUSTRIES, JOB_TITLES, Ctx, _EMAIL, hash_password, require, require_admin,
                  verify_password)
from billing_api import fee_for
from creator_pipeline.config import GST_RATE
from platform_db import db, log, now_iso, rows

router = APIRouter(prefix="/api/settings")


@router.get("")
def get_settings(ctx: Ctx = Depends(require)):
    with db() as conn:
        org = dict(conn.execute("SELECT * FROM orgs WHERE id = ?", (ctx.org_id,)).fetchone())
        members = rows(conn.execute("""SELECT u.id, u.name, u.email, m.role, m.job_title, u.last_login FROM memberships m
                                       JOIN users u ON u.id = m.user_id WHERE m.org_id = ? ORDER BY u.id""", (ctx.org_id,)))
        fee = fee_for(conn, ctx.org_id)
    return {"me": ctx.__dict__, "org": org, "members": members, "fee_per_creator": fee, "gst_rate": GST_RATE,
            "options": {"job_titles": JOB_TITLES, "industries": INDUSTRIES, "company_sizes": COMPANY_SIZES}}


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    job_title: str = Field(min_length=2, max_length=80)


@router.patch("/profile")
def update_profile(req: ProfileIn, ctx: Ctx = Depends(require)):
    with db() as conn:
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (req.name.strip(), ctx.user_id))
        conn.execute("UPDATE memberships SET job_title = ? WHERE user_id = ? AND org_id = ?",
                     (req.job_title.strip(), ctx.user_id, ctx.org_id))
    return {"ok": True}


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    industry: str | None = None
    size: str | None = None
    gstin: str | None = Field(default=None, max_length=15)
    billing_email: str | None = None
    address: str | None = Field(default=None, max_length=300)


@router.patch("/company")
def update_company(req: CompanyIn, ctx: Ctx = Depends(require_admin)):
    if req.billing_email and not _EMAIL.match(req.billing_email):
        raise HTTPException(400, "Billing email doesn't look right")
    with db() as conn:
        conn.execute("UPDATE orgs SET name = ?, industry = ?, size = ?, gstin = ?, billing_email = ?, address = ? WHERE id = ?",
                     (req.name.strip(), req.industry, req.size, (req.gstin or "").upper() or None, req.billing_email,
                      req.address, ctx.org_id))
    return {"ok": True}


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=8, max_length=200)


@router.post("/password")
def change_password(req: PasswordIn, ctx: Ctx = Depends(require)):
    with db() as conn:
        u = conn.execute("SELECT pw_hash, pw_salt FROM users WHERE id = ?", (ctx.user_id,)).fetchone()
        if not verify_password(req.current, u["pw_hash"], u["pw_salt"]):
            raise HTTPException(400, "Current password is wrong")
        h, salt = hash_password(req.new)
        conn.execute("UPDATE users SET pw_hash = ?, pw_salt = ? WHERE id = ?", (h, salt, ctx.user_id))
    return {"ok": True}


class InviteIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str
    job_title: str = Field(min_length=2, max_length=80)
    role: str = "member"


@router.post("/members")
def invite(req: InviteIn, ctx: Ctx = Depends(require_admin)):
    """Creates the teammate's login with a one-time temporary password (no email service configured yet)."""
    email = req.email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(400, "That email doesn't look right")
    if req.role not in ("member", "admin"):
        raise HTTPException(400, "Role must be member or admin")
    temp = secrets.token_urlsafe(9)
    with db() as conn:
        u = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if u:
            if conn.execute("SELECT 1 FROM memberships WHERE user_id = ? AND org_id = ?", (u["id"], ctx.org_id)).fetchone():
                raise HTTPException(409, "Already a member")
            raise HTTPException(409, "This email already has an account with another company")
        h, salt = hash_password(temp)
        uid = conn.execute("INSERT INTO users (email, name, pw_hash, pw_salt, created_at) VALUES (?,?,?,?,?) RETURNING id",
                           (email, req.name.strip(), h, salt, now_iso())).fetchone()[0]
        conn.execute("INSERT INTO memberships (user_id, org_id, role, job_title) VALUES (?,?,?,?)",
                     (uid, ctx.org_id, req.role, req.job_title.strip()))
        log(conn, ctx.org_id, f"{ctx.name} added {req.name.strip()} to the team", ctx.user_id)
    return {"ok": True, "temporary_password": temp}
