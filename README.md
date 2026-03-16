# ClassPro Web

ClassPro Web is a read-only FastAPI web application that renders shared class reports and student grade summaries from a ClassPro (FastScores) Supabase backend. Teachers generate share tokens in the iOS app; recipients open the token URL in any browser to view formatted reports or download CSV/Excel exports — no login required.

## Prerequisites

- Python 3.12+
- A Supabase project with the ClassPro schema applied (`supabase_schema.sql`)
- A `service_role` key from your Supabase project (bypasses RLS for read access)

## Local Development

```bash
cp .env.example .env
# Edit .env and fill in SUPABASE_URL and SUPABASE_SERVICE_KEY
pip install -r requirements.txt
uvicorn main:app --reload
# Open http://localhost:8000
```

## Supabase Setup

The `service_role` key is used server-side and bypasses Row Level Security automatically — no additional RLS policies are needed. Never expose this key to the browser.

## Deploy to Koyeb

1. Push this repository to GitHub.
2. Go to [app.koyeb.com](https://app.koyeb.com) → **New Service** → **Web Service** → select your GitHub repo.
3. Set **Build type** to **Dockerfile**.
4. Add environment variables in the Koyeb dashboard:

| Key | Value |
|-----|-------|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Your Supabase `service_role` secret key |

5. Click **Deploy**.

## Routes

| Route | Description |
|-------|-------------|
| `GET /` | Landing page |
| `GET /report/{token}` | Full class report (grades, attendance, rankings) |
| `GET /student/{token}` | Individual student grade summary |
| `GET /export/{token}?format=csv` | Download report as CSV |
| `GET /export/{token}?format=excel` | Download report as Excel (`.xlsx`) |
| `GET /health` | Health check — returns `{"status": "ok"}` |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL (e.g. `https://xyz.supabase.co`) |
| `SUPABASE_SERVICE_KEY` | Yes | Supabase `service_role` key — server-side only |
