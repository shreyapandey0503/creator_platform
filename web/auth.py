"""Email + password accounts, company workspaces and cookie sessions.

Passwords: PBKDF2-HMAC-SHA256, 310k iterations, per-user random salt (stdlib only).
Sessions: 32-byte random token in an HttpOnly, SameSite=Lax cookie; stored server-side with an expiry.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from platform_db import db, log, now_iso

COOKIE = "ca_session"
SESSION_DAYS = 14
ITERATIONS = 310_000
router = APIRouter(prefix="/api/auth")

JOB_TITLES = ["Founder / CEO", "Marketing head", "Brand manager", "Influencer marketing manager",
              "Agency account manager", "Social media manager", "Other"]
INDUSTRIES = ["Food & beverage", "Beauty & personal care", "Fashion & apparel", "Consumer tech",
              "Fintech", "Travel & hospitality", "Health & fitness", "Education", "Gaming",
              "D2C / e-commerce", "Marketing agency", "Other"]
COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-1000", "1000+"]


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return h, salt


def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt)[0], pw_hash)


@dataclass
class Ctx:
    user_id: int
    org_id: int
    name: str
    email: str
    role: str
    job_title: str | None
    org_name: str


def _new_session(conn, user_id: int, org_id: int, response: Response):
    token = secrets.token_urlsafe(32)
    exp = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    conn.execute("INSERT INTO sessions (token, user_id, org_id, created_at, expires_at) VALUES (?,?,?,?,?)",
                 (token, user_id, org_id, now_iso(), exp.replace(microsecond=0).isoformat()))
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", path="/")


def current(request: Request) -> Ctx | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    with db() as conn:
        r = conn.execute("""
            SELECT s.user_id, s.org_id, s.expires_at, u.name, u.email, m.role, m.job_title, o.name AS org_name
            FROM sessions s JOIN users u ON u.id = s.user_id
            JOIN memberships m ON m.user_id = s.user_id AND m.org_id = s.org_id
            JOIN orgs o ON o.id = s.org_id WHERE s.token = ?""", (token,)).fetchone()
        if not r or r["expires_at"] < now_iso():
            return None
        return Ctx(r["user_id"], r["org_id"], r["name"], r["email"], r["role"], r["job_title"], r["org_name"])


def require(request: Request) -> Ctx:
    ctx = current(request)
    if not ctx:
        raise HTTPException(401, "Please log in")
    return ctx


def require_admin(ctx: Ctx = Depends(require)) -> Ctx:
    if ctx.role not in ("owner", "admin"):
        raise HTTPException(403, "Only company admins can do this")
    return ctx


# ------------------------------------------------------------------ routes

class SignupReq(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    company: str = Field(min_length=2, max_length=120)
    job_title: str = Field(min_length=2, max_length=80)
    industry: str | None = None
    company_size: str | None = None
    phone: str | None = None


class LoginReq(BaseModel):
    email: str
    password: str


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("/options")
def signup_options():
    return {"job_titles": JOB_TITLES, "industries": INDUSTRIES, "company_sizes": COMPANY_SIZES}


@router.post("/signup")
def signup(req: SignupReq, response: Response):
    email = req.email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(400, "That email doesn't look right")
    with db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "An account with this email already exists - log in instead")
        h, salt = hash_password(req.password)
        ts = now_iso()
        uid = conn.execute("INSERT INTO users (email, name, pw_hash, pw_salt, created_at, last_login) VALUES (?,?,?,?,?,?)"
                           " RETURNING id", (email, req.name.strip(), h, salt, ts, ts)).fetchone()[0]
        oid = conn.execute("INSERT INTO orgs (name, industry, size, billing_email, created_at) VALUES (?,?,?,?,?)"
                           " RETURNING id", (req.company.strip(), req.industry, req.company_size, email, ts)).fetchone()[0]
        conn.execute("INSERT INTO memberships (user_id, org_id, role, job_title) VALUES (?,?,?,?)",
                     (uid, oid, "owner", req.job_title.strip()))
        log(conn, oid, f"{req.name.strip()} created the {req.company.strip()} workspace", uid)
        _new_session(conn, uid, oid, response)
    return {"ok": True}


@router.post("/login")
def login(req: LoginReq, response: Response):
    with db() as conn:
        u = conn.execute("SELECT * FROM users WHERE email = ?", (req.email.strip().lower(),)).fetchone()
        if not u or not verify_password(req.password, u["pw_hash"], u["pw_salt"]):
            raise HTTPException(401, "Wrong email or password")
        m = conn.execute("SELECT org_id FROM memberships WHERE user_id = ? ORDER BY org_id LIMIT 1", (u["id"],)).fetchone()
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now_iso(), u["id"]))
        _new_session(conn, u["id"], m["org_id"], response)
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(ctx: Ctx = Depends(require)):
    return ctx.__dict__
