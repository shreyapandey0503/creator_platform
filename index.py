"""Vercel entrypoint - re-exports the FastAPI app from web/server.py."""
from web.server import app  # noqa: F401
