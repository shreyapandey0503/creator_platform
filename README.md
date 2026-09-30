# Creator Atlas — creator intelligence prototype

Messy creator lists in → clean, deduplicated, enriched creator database out → clusters to explore →
a budget-aware creator pool for a campaign brief.

**Creator Atlas is a multi-company SaaS** (`web/`, FastAPI + vanilla JS) — http://localhost:8000

| Page | What it does |
|---|---|
| `/` | Marketing site: what we do, how it works, pricing calculator, FAQ |
| `/signup`, `/login` | Account + company workspace (name, email, password, company, role, industry, size) |
| `/app#/dashboard` | Onboarding checklist, KPIs, recent campaigns, activity feed |
| `/app#/creators` | Upload CSV → import report → creator universe (clusters, facets, smart segments) |
| `/app#/campaigns/new` | Campaign studio: brief → fit-scored pool within budget → save as campaign |
| `/app#/campaigns/<id>` | Pipeline board (drag & drop), creator drawer (fee, due date, post link, stats), performance, billing, activity, brief |
| `/app#/billing` | Fee explainer, outstanding/paid, invoices, pay (test mode) |
| `/app#/settings` | Profile, company & GST details, team (add teammates), password |
| `/invoice/<id>` | Printable GST invoice (save as PDF) |

```powershell
.\.venv\Scripts\python.exe -m uvicorn web.server:app --port 8000     # Creator Atlas SaaS
.\.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py      # internal data-ops console (shared demo DB)
```

**Data isolation.** `data/platform.db` holds users, companies, sessions, campaigns, tracking and invoices.
Each company's creators live in their own database, `data/orgs/org_<id>/creators.db` (uploads in
`data/orgs/org_<id>/uploads/`), so rate cards and notes never leak across clients. Every API call is scoped to the
logged-in company; cross-company access returns 404 (tested).

**Accounts.** Passwords are PBKDF2-SHA256 (310k iterations, per-user salt); sessions are random tokens in
HttpOnly, SameSite=Lax cookies, stored server-side with a 14-day expiry. Roles: owner / admin / member.
Teammates are added from Settings with a one-time password (no email service configured yet).

**Billing model.** `FEE_PER_CREATOR_INR` (default ₹499) per *confirmed* creator per campaign, + `GST_RATE` (18%).
Launching a campaign invoices creators already confirmed; creators confirmed later are billed via “Bill” or on
completion; shortlisted-only creators are never billed; a billed creator can't be dropped. Payments are in
**test mode** — `pay_invoice()` in `web/billing_api.py` is where a Razorpay order + webhook would plug in.

**Tracking.** Creator statuses: shortlisted → contacted → negotiating → confirmed → content submitted → live →
completed (or dropped). Post stats are snapshots over time; YouTube video links can be fetched from the YouTube
Data API (needs `YOUTUBE_API_KEY`), Instagram stats are entered manually until a data provider is connected.

**Demo data:** `data/samples/SAMPLE_fictional_creators_india.csv` (downloadable from the upload page) —
600 **fictional** creators with city, age, gender, languages, rate cards and past collabs, written messily on
purpose. Regenerate with `python scripts/make_demo_dataset.py`. Names, handles and brands are invented; names
that match anyone in the Kaggle lists are excluded. Real public lists don't carry rates/ages/cities, and making
those up for real people would be misleading.

Optional real video wallpapers: drop licensed `.mp4`/`.webm` loops into `web/static/wallpapers/`.

Base data: Kaggle *Top 100 Social Media Influencers 2024 – Countrywise*, India files
(Instagram, Threads, TikTok, YouTube — 400 rows) in `raw_data/`. **Raw files are never modified.**

## Folder structure

```
creator_platform/
├── raw_data/                  source CSVs (read-only, never edited)
├── data/
│   ├── creators.db            SQLite database: every pipeline layer (generated)
│   ├── staging/               staging_rows.csv - raw rows + issues found
│   ├── processed/             accounts_clean.csv, creators.csv, rejected_rows.csv
│   ├── review/                dedupe_candidates.csv - the review queue
│   ├── enriched/              stat_snapshots.csv, youtube_channels.csv
│   ├── uploads/               untouched copies of files uploaded through the UI
│   └── samples/               SYNTHETIC messy test sheet + its ground truth
├── src/creator_pipeline/      the pipeline (importable package)
│   ├── config.py              paths + .env settings
│   ├── db.py                  SQLite schema (mirrors a future Postgres schema)
│   ├── parsing.py             numbers, %, names, handles, URL -> identity
│   ├── taxonomy.py            topic -> category map, city aliases, brand/media guess
│   ├── ingest.py              step 1: file -> staging (SHA-256, idempotent)
│   ├── normalise.py           step 2: staging -> clean platform accounts
│   ├── dedupe.py              step 3: same-creator matching + review queue + creators
│   ├── youtube.py             step 4: YouTube Data API enrichment + quota ledger
│   ├── export.py              step 5: every layer -> CSV
│   ├── profiles.py            creator-level table (accounts rolled up) + derived tiers, CPV, ER vs peers
│   ├── segments.py            k-means "smart segments", auto-named from centroids
│   ├── matching.py            campaign brief -> fit score + reasons -> budget-aware pool
│   └── labels.py              human-readable data-quality flag descriptions
├── scripts/                   CLI entry points (01_... to 05_..., run_pipeline.py)
├── web/                       Creator Atlas: FastAPI server.py + static/ (index.html, app.css, app.js)
├── app/                       Streamlit data-ops console (streamlit_app.py + views/)
├── tests/                     pytest unit tests for the cleaning rules
├── docs/                      proposal
├── .env / .env.example        API key + settings (.env is git-ignored)
└── requirements.txt
```

## Setup (Windows, PowerShell)

```powershell
cd C:\Users\Admin\Documents\Shreya\creator_platform
.\.venv\Scripts\Activate.ps1          # venv already created (Python 3.13)
pip install -r requirements.txt       # already installed
```

(Git Bash: `source .venv/Scripts/activate`.)

## Run

```powershell
python scripts/run_pipeline.py --reset      # ingest raw_data -> clean -> dedupe -> export CSVs
streamlit run app/streamlit_app.py          # UI at http://localhost:8501
python -m pytest -q                         # 52 tests for the cleaning rules
```

Step by step instead: `01_ingest.py`, `02_normalise.py`, `03_dedupe.py`, `04_enrich_youtube.py`, `05_export.py`.

### YouTube enrichment

1. Google Cloud Console → *APIs & Services* → enable **YouTube Data API v3** → *Credentials* → **Create API key**
   (restrict it to the YouTube Data API v3).
2. Put it in `.env`: `YOUTUBE_API_KEY=...` (optionally `GCP_PROJECT_ID=...`).
3. `python scripts/04_enrich_youtube.py --dry-run` shows the plan and the quota cost; drop `--dry-run` to run.
   Or use the **YouTube API** page in the UI.

The API is free; the limit is 10,000 quota units/day. The prototype only uses 1-unit calls (never the 100-unit
`search.list`): ≈2 units per channel with recent videos, ≈0.02 units per channel for stats only. Every call is
logged in `api_calls`; runs stop before the daily budget is exceeded.

## What the pipeline does

**1. Ingest.** Every CSV row goes into `staging_rows` as raw JSON, tagged with its file (by SHA-256; the same file
twice is a no-op). Uploads are stored untouched in `data/uploads/`.

**2. Normalise** (rebuilt from staging on every run, so improving a rule re-cleans everything):
- Columns are detected by name (`Creator Name`, `Profile Link`, `Followers`, `City`, `Engagement %`...).
- Identity: `Virat Kohli @virat.kohli` is split into name + handle; URLs lose tracking params (`?igsh=`, `?si=`);
  YouTube `/channel/UC…` IDs are used directly; `@handles` and legacy `/user/` URLs are queued for API
  resolution; `/c/` URLs and post/video links are flagged.
- Names: decorative Unicode fonts folded (`𝑨𝒋𝒆𝒚 𝑵𝒂𝒈𝒂𝒓` → `Ajey Nagar`), emojis/hashtags removed,
  spaced letters joined (`F I L M Y G Y A N`), ALL CAPS re-cased (acronyms kept), Indic scripts kept.
- Numbers: `267.1M`, `12,00,000`, `1.2 lakh`, `3 crore`, `2.23%`, `-` → numbers or empty.
- Topics: the source glues topics together with no separator (`Entertainment and Music Fashion and Accessories
  Actors`) → split by longest-phrase match → mapped to 29 canonical categories + tags.
- Cities: aliases → canonical city + state (Bombay → Mumbai, Gurgaon → Gurugram, BLR → Bengaluru).
- Exact duplicates (same platform + same ID/handle) merge into one account; every source row is kept as lineage.
- Nothing is silently dropped: each fix/warning is recorded per row (`row_issues`) and shown in the UI.

**3. Dedupe** (which accounts are the same creator?):
- *Auto-linked*: same handle on Instagram & Threads (Threads uses the Instagram username), or the same handle
  **and** name on two platforms.
- *Review queue*: fuzzy name/handle matches (e.g. YouTube "Harsh Beniwal" ↔ Threads @harshbeniwal,
  Neha Kakkar ↔ Tony Kakkar — siblings, *not* the same person). A person decides; decisions survive re-runs
  and can be undone.
- Candidate pairs come from blocking on name/handle prefixes, so it scales to 50K+ rows.

**4. Enrich.** YouTube: handles → channel IDs, channel stats (batched 50/call), last 10 uploads → avg views and
engagement rate (videos under 48h old excluded). Every fetch is an append-only, timestamped snapshot; each
profile shows the source and age of its numbers. "Only stale channels" (7 / 30 days) supports tiered refresh.

## Current results on the Kaggle data

| | |
|---|---|
| Raw rows | 400 (4 platforms × 100) |
| Clean accounts | 400 (no rejects, no exact duplicates in this source) |
| Creators | 383 — 16 creators on 2+ platforms |
| Auto-linked pairs | 18 · Review queue: 6 |
| Most common fixes | ER missing (182), topics missing (146), names re-cased / emojis removed (~100) |

Test with the synthetic messy sheet (`python scripts/make_sample_upload.py && python scripts/eval_sample_upload.py`):
**150/150 rows** mapped to the right account or correctly rejected.

## Campaign matching (how the fit score works)

Hard filters: platform, deliverable availability (YouTube video needs a channel), creator gender preference,
minimum ER, max rate, competitor conflicts (past collabs), brand/media accounts.
Fit (0-100) = weighted mix — weights shift with the objective (awareness / engagement / conversions):
relevance (niche, related niche, keyword hits in sub-niches), location (target city > same region),
age band (creator age as an audience proxy), language overlap, performance (ER vs same-size peers, views),
value (₹ per view for the chosen deliverable). The pool is greedy by fit under the budget, with a soft cap per
city and a rule that one creator can't take more than 2.5× the average remaining share. Every pick has
plain-English reasons; runners-up show why they weren't picked.

## Known limitations / next steps

- Entity type (person vs brand/media) is a keyword guess — shown as "(guess)" for a human to correct.
- CSV stats are dated by import time; the Kaggle numbers themselves are a 2024 snapshot.
- Instagram/Threads/TikTok stats come only from the file until a licensed Instagram data provider (or Meta
  Business Discovery for professional accounts) is connected.
- Creator age is used as a proxy for audience age until audience demographics are connected (Instagram
  creator-authorised insights / a data provider).
- Fit weights are hand-set; once campaigns have outcomes (views, CPV, sales), train a model on them.
- Next: Postgres + deploy (Vercel/Cloud Run), campaign workflow (outreach status, deliverables, live tracking),
  client-facing view with internal-only fields hidden.
