"""Project paths and settings, loaded from .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

RAW_DIR = ROOT / "raw_data"
DATA_DIR = ROOT / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
PROCESSED_DIR = DATA_DIR / "processed"
REVIEW_DIR = DATA_DIR / "review"
ENRICHED_DIR = DATA_DIR / "enriched"
STAGING_DIR = DATA_DIR / "staging"

DB_PATH = ROOT / os.getenv("DB_PATH", "data/creators.db")
# SaaS: platform data (users, companies, campaigns, invoices) + one private creator DB per company
PLATFORM_DB_PATH = ROOT / os.getenv("PLATFORM_DB_PATH", "data/platform.db")
ORGS_DIR = ROOT / os.getenv("ORGS_DIR", "data/orgs")
# Postgres (e.g. Supabase transaction pooler URL). When set, the web app stores everything there instead of
# the SQLite files above: platform data in schema "platform", each company's creators in schema "org_<id>".
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
FEE_PER_CREATOR = int(os.getenv("FEE_PER_CREATOR_INR", "499") or 499)
GST_RATE = float(os.getenv("GST_RATE", "0.18") or 0.18)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_DAILY_QUOTA = int(os.getenv("YOUTUBE_DAILY_QUOTA", "10000") or 10000)
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "").strip()

PLATFORMS = ("instagram", "youtube", "threads", "tiktok")
