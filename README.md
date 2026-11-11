# Meso Tracker - licence server, website, and deploy config

This repo is the backend for the paid version of Meso Tracker (the desktop overlay lives in the main
`MapleClassicBot/meso_overlay` project and talks to the API here).

- `server/` - FastAPI licence/billing server (Stripe + Resend + Postgres). `server/tests` has 21 passing tests covering
  licence-key hashing, session tokens, and the full activate/status/deactivate control flow with a fake DB.
- `website/` - the plain static marketing site + checkout flow (no build step).
- `render.yaml` - the Render Blueprint that deploys all three (API, Postgres, static site) in one click.
- **`SETUP.md` - start here.** The exact steps to go from this code to a live, paying product.
- **`SECURITY.md`** - an honest account of what this system protects against and what it doesn't. Read this before
  calling anything "impenetrable" to a customer.

## Local development

```
cd server
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m unittest discover -s tests -v      # 21 tests, no external services needed
```

Running the real server locally needs env vars for Postgres/Stripe/Resend - see `SETUP.md`.
