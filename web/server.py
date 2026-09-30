"""Creator Atlas - SaaS web app.

    .\\.venv\\Scripts\\python.exe -m uvicorn web.server:app --port 8000     (from the project root)

Pages:  /            marketing site          /login, /signup    accounts
        /app         the product (needs a session): dashboard, creators, campaigns, billing, settings
        /invoice/N   printable invoice
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as FastHTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
sys.path[:0] = [str(ROOT / "src"), str(WEB)]

import auth  # noqa: E402
import billing_api  # noqa: E402
import campaigns_api  # noqa: E402
import creators_api  # noqa: E402
import settings_api  # noqa: E402
from creator_pipeline.config import DATABASE_URL  # noqa: E402
from platform_db import connect  # noqa: E402

if os.getenv("VERCEL") and not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Vercel has no writable disk for the SQLite files - add your Supabase "
                       "connection string under Project Settings -> Environment Variables and redeploy.")

STATIC = WEB / "static"
WALLPAPERS = STATIC / "wallpapers"

app = FastAPI(title="Creator Atlas", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
for r in (auth.router, creators_api.router, campaigns_api.router, billing_api.router, settings_api.router):
    app.include_router(r)
connect().close()  # create the platform DB (or Postgres schema) on startup


@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(STATIC / "landing.html")


@app.get("/login", include_in_schema=False)
@app.get("/signup", include_in_schema=False)
def auth_page(request: Request):
    if auth.current(request):
        return RedirectResponse("/app")
    return FileResponse(STATIC / "auth.html")


@app.get("/app", include_in_schema=False)
def app_page(request: Request):
    if not auth.current(request):
        return RedirectResponse("/login")
    return FileResponse(STATIC / "app.html")


@app.get("/api/sample.csv", include_in_schema=False)
def sample_csv():
    if not creators_api.SAMPLE.exists():
        raise FastHTTPException(404, "Sample not generated - run scripts/make_demo_dataset.py")
    return FileResponse(creators_api.SAMPLE, media_type="text/csv", filename=creators_api.SAMPLE.name)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">◉</text></svg>'
    return Response(svg, media_type="image/svg+xml")


@app.get("/api/pricing", include_in_schema=False)
def pricing():
    from creator_pipeline.config import FEE_PER_CREATOR, GST_RATE
    return {"fee_per_creator": FEE_PER_CREATOR, "gst_rate": GST_RATE}


@app.get("/api/wallpapers", include_in_schema=False)
def wallpapers():
    vids = sorted(p.name for p in WALLPAPERS.glob("*") if p.suffix.lower() in (".mp4", ".webm")) if WALLPAPERS.exists() else []
    return {"videos": [f"/static/wallpapers/{v}" for v in vids]}


@app.exception_handler(FastHTTPException)
async def http_error(request: Request, exc: FastHTTPException):
    if exc.status_code == 401 and request.url.path.startswith("/invoice"):
        return RedirectResponse("/login")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def on_error(_, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.server:app", host="127.0.0.1", port=8000, app_dir=str(ROOT))
