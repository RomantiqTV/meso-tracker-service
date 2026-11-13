# Going live: exactly what to click

I can't do these four steps for you - they each need your own identity/bank details, which I'm not able to enter on your
behalf. Everything else (the server, the database schema, the website, the desktop client) is already built and tested;
these steps just connect it to real payments and email.

Budget about 30-45 minutes the first time.

## 1. Stripe (takes payments)

1. Go to https://dashboard.stripe.com/register and create an account (your bank details go here, for payouts).
2. **Products -> Add product.** Name: `Meso Tracker`. Pricing: **Recurring**, `$1.99`, **Monthly**. Save, then open the
   product and copy the **Price ID** (looks like `price_1Abc...`) - this is `STRIPE_PRICE_ID`.
2b. **Longer plans (optional).** On that same product, **Add another price** twice more: **Recurring**, `$8.00`,
    **Every 6 months**, and **Recurring**, `$10.00`, **Yearly**. Copy each Price ID - these are `STRIPE_PRICE_ID_6MO`
    and `STRIPE_PRICE_ID_YEARLY`. Skip either (or both) for now if you'd rather launch with Monthly only: the website's
    6 Months / Yearly buttons just show "not available yet" until the matching env var is set in Render (step 4) -
    nothing breaks, nothing needs a code change later, just add the env var whenever the Price exists.
3. **Developers -> API keys.** Copy the **Secret key** (`sk_live_...` once you're out of test mode, `sk_test_...` while
   testing) - this is `STRIPE_SECRET_KEY`. Copy the **Publishable key** too (`STRIPE_PUBLISHABLE_KEY`, not actually used
   server-side yet but worth saving).
4. **Developers -> Webhooks -> Add endpoint.** URL: `https://<your-render-api-url>/v1/webhooks/stripe` (you'll have this
   after step 3 below - come back and add it then). Events to send: `checkout.session.completed`,
   `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`,
   `invoice.payment_failed`. After creating it, copy the **Signing secret** (`whsec_...`) - this is
   `STRIPE_WEBHOOK_SECRET`.
5. Stay in **test mode** until you've run through a full purchase yourself with a test card (`4242 4242 4242 4242`, any
   future date/CVC) - the activity log below (step 5) shows how to watch it happen. Flip to live mode only once that works.

## 2. Resend (sends the licence-key email)

1. https://resend.com -> sign up.
2. **API Keys -> Create API Key** -> this is `RESEND_API_KEY`.
3. For real delivery to arbitrary customers, verify a sending domain under **Domains** (adds a couple of DNS records at
   your domain registrar) and set `EMAIL_FROM` to e.g. `Meso Tracker <hello@yourdomain.com>`. Until you do that, Resend's
   sandbox address `onboarding@resend.dev` works but only delivers to your own verified email - fine for testing, not for
   real customers.

## 3. Render (hosts the API, the database, and the website)

1. https://render.com -> sign up, connect your GitHub account.
2. Push this repo to a new GitHub repo (see the git commands at the bottom of this file).
3. In Render: **New -> Blueprint**, pick the repo. Render reads `render.yaml` and proposes three resources: the Postgres
   database, the `meso-tracker-api` web service, and the `meso-tracker-site` static site. Click **Apply**.
4. Open **meso-tracker-api -> Environment** and fill in the variables marked "from your own value" below (the ones Render
   generated itself - `DATABASE_URL`, `JWT_SIGNING_SECRET`, `LICENSE_KEY_PEPPER` - are already filled in and you don't
   need to touch them):
   - `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `STRIPE_PUBLISHABLE_KEY` (from step 1)
   - `STRIPE_PRICE_ID_6MO`, `STRIPE_PRICE_ID_YEARLY` (from step 1, optional - from step 2b, only if you added those plans)
   - `RESEND_API_KEY`, `EMAIL_FROM` (from step 2)
   - `SITE_URL` - your static site's URL, e.g. `https://meso-tracker-site.onrender.com` (or your custom domain later)
   - `DOWNLOAD_URL` - where the packaged .exe will live; a GitHub Releases asset URL is the easiest option (see
     `../build/README.md` for building it). You can leave this blank and fill it in after your first build.
5. Copy the API service's URL (e.g. `https://meso-tracker-api.onrender.com`) and:
   - go back to Stripe step 1.4 and finish adding the webhook endpoint with this URL,
   - edit `website/index.html`'s `<meta name="meso-api-base" ...>` tag to this URL, commit, and push (Render redeploys
     the static site automatically).
6. **Pushing an update to everyone who already has the app, later:** build the new version (`build/build_release.py`),
   upload it somewhere stable (a new GitHub Release asset works well), then in **meso-tracker-api -> Environment** set:
   - `LATEST_VERSION` to the new version string (e.g. `1.1.0`) - every running copy sees this on its next phone-home
     (immediately if they're not logged in yet or their cached session just expired; within `SESSION_TTL_HOURS`,
     24h by default, for everyone already logged in) and shows a dismissable "update available" notice with a
     Download button. Nothing is forced.
   - `RELEASE_NOTES` (optional) - a one-line summary shown under that notice.
   - `MIN_SUPPORTED_VERSION` - only set this if the old version must stop working (e.g. you changed something the
     server no longer supports). Anyone on an older version is refused outright (a clear "please update" message,
     not a crash) until they install the new build. Leave it blank for an ordinary, optional update.
   - No code deploy needed for any of this - it's just env vars the server reads on each request.
7. Render's free tier spins a web service down after 15 minutes idle and takes ~30-50s to wake on the next request - the
   app's first login after a quiet period will just feel slow once, not broken. Upgrade the plan if that's not acceptable.

## 4. A domain (optional, later)

Render's `*.onrender.com` subdomains work fine to launch with. If you buy a real domain, that's a real purchase with
your own payment method, so do it yourself at a registrar of your choice, then follow Render's "Custom Domains" docs for
that service and update `SITE_URL` / the webhook URL / the `<meta>` tag to match.

## Running it locally first (recommended before touching Stripe live mode)

```
cd server
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
# set the env vars above (test-mode Stripe keys, a Postgres you have locally, any JWT_SIGNING_SECRET/LICENSE_KEY_PEPPER)
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Open `website/index.html` directly in a browser (edit its `<meta name="meso-api-base">` to `http://127.0.0.1:8000`
first) and run through a test-mode purchase end to end.

## Pushing this repo to GitHub

```
cd F:\MesoTrackerService
git init
git add .
git commit -m "Meso Tracker licence server, site, and client"
git branch -M main
git remote add origin https://github.com/<you>/meso-tracker-service.git
git push -u origin main
```
