# Simify YouTube Gifting Tracker

A fully static dashboard (GitHub Pages) fed by scheduled automations (GitHub Actions).
**No server, no database, no Base44, no credits.** The only optional paid piece is a
few cents of Anthropic usage for reply-drafting — and even that is off by default.

## How it works

```
GitHub Actions (cron)              GitHub repo                 GitHub Pages
─────────────────────              ───────────                 ───────────
discovery.yml  ─ finds creators ─▶ workers/…xlsx  ─┐
export_data.py ─ builds JSON    ─▶ docs/data/*.json ├─ served ─▶ docs/index.html
inbox.yml      ─ drafts replies ─▶ (drafts land in your Gmail)  (the dashboard)
```

- **Dashboard** = `docs/index.html`, hosted free on GitHub Pages. It `fetch`es `docs/data/creators.json`.
- **Workers** = your existing Python scripts in `workers/`, run on a schedule by GitHub Actions.
- **Data** = JSON committed into the repo by the Actions. No database needed.

## Repo layout

```
docs/                 ← GitHub Pages serves this folder
  index.html          ← the dashboard
  data/creators.json  ← built from the spreadsheet (no emails — safe to publish)
workers/              ← Python automations (run by Actions)
  daily_discovery.py  ← finds new creators (YouTube API)
  export_data.py      ← spreadsheet → docs/data/creators.json
  email_agent.py      ← drafts Gmail replies (optional, uses AI)
  Simify_Influencer_Prospects.xlsx   ← the full roster (has emails — keep private)
.github/workflows/    ← the schedules
```

---

## Setup — do these once

### 1. Create a PRIVATE repo and push
The spreadsheet holds creator emails, so the repo must be **private**.
```bash
cd "simify-tracker"
git init && git add -A && git commit -m "Initial commit"
gh repo create simify-tracker --private --source=. --push   # or create it on github.com and push
```
(`creators.json` deliberately contains **no emails**, so the published dashboard is safe.)

### 2. Add your YouTube key as a secret
Repo → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `YOUTUBE_API_KEY`  ·  Value: your key
That's the **only** secret needed for discovery + the dashboard. No AI, no credits.

### 3. Publish the dashboard
The repo **must stay private** (see the warning below), and GitHub Pages does **not**
serve private repos on the Free plan. Pick one of these, in order of preference:

1. **RECOMMENDED — Cloudflare Pages or Netlify (free).** Connect the private repo, set the
   **build output / publish directory to `docs/`** (no build command needed — it's static).
   Because the dashboard exposes the creator pipeline, add **access protection**:
   Cloudflare Access (free tier) or Netlify password protection / Identity, so only your
   team can view it.
2. **GitHub Pro ($4/mo)** unlocks GitHub Pages on private repos. If you upgrade, then
   Repo → **Settings → Pages** → Source = **Deploy from a branch** → Branch `main`, folder
   **`/docs`** → Save. Dashboard lands at `https://<you>.github.io/simify-tracker/`.
3. **⚠️ DO NOT make the repo public to get free Pages.** The repo contains
   `workers/Simify_Influencer_Prospects.xlsx` with **real creator emails**. Going public
   exposes them **permanently in git history** — deleting the file later does not remove it
   from past commits. Keep it private and use option 1 or 2.

### 4. Run discovery once
Repo → **Actions → Discovery → Run workflow**. It finds creators, rebuilds
`creators.json`, and commits it — the dashboard updates automatically. After this it
runs every day on its own.

> **Cron timezone note:** GitHub cron is UTC. `0 22 * * *` ≈ 8am AEST (winter). During
> daylight saving (Oct–Apr) AEDT is UTC+11, so change it to `0 21 * * *` if you want 8am sharp.

**At this point the tracker is live and operating — for free, with zero AI.**

---

## Optional: Gmail reply drafts (the only AI step)

This runs `email_agent.py`, which reads unread email and drafts replies **for your
review**. It never sends — you send from Gmail. It's the one feature that uses AI
(a few cents/month on your own Anthropic key). Skip this whole section if you don't want it.

Gmail needs OAuth, which can't do a browser popup on a server. So you authorise **once on
your Mac**, then hand the resulting token to GitHub as a secret.

### A. Authorise once, locally
```bash
cd workers
pip install -r requirements.txt
python email_agent.py        # opens a browser → sign in → allow → creates token.json
```
You now have `credentials.json` (your Google OAuth client) and `token.json` (the saved login).

### B. Stop the token from expiring
In **Google Cloud Console → APIs & Services → OAuth consent screen**, set **Publishing
status = In production** (not "Testing"). In Testing mode Google expires the refresh
token every 7 days; In Production it lasts. You'll see an "unverified app" screen when you
authorise — you're the owner, so click **Advanced → go to (app) (unsafe)**. Safe for a
personal script. Scopes are read + draft only (never send).

### C. Add three secrets
Repo → Settings → Secrets and variables → Actions:
- `GMAIL_CREDENTIALS` = the full contents of `workers/credentials.json`
- `GMAIL_TOKEN` = the full contents of `workers/token.json`
- `ANTHROPIC_API_KEY` = your Anthropic key (set a low spend limit in the Anthropic console)

The `inbox.yml` workflow writes those back into files at runtime and runs headless. Done.

---

## Day-to-day

- **Discovery** runs every morning → new creators appear in the dashboard automatically.
- **Inbox** (if enabled) drafts replies hourly → you review + send in Gmail.
- To add attribution (Shopify + Impact) and Monday.com sync later, add a `sync.yml`
  workflow with those tokens as secrets (same pattern). Ask and it can be scaffolded.

> **Note:** the primary creator source is now `workers/Simify_YouTube_MicroNano_Prospects.xlsx`.

### Rollback
The dashboard data (`docs/data/creators.json`) is versioned in git, so a bad discovery run
is fully reversible. Find the offending commit and revert it — the previous data comes back:
```bash
git revert <sha>        # creates a new commit that undoes the bad one
git push
```
You can also revert the bad commit from the GitHub UI (open the commit → **Revert**). The
next scheduled run then rebuilds cleanly on top of the restored data.

## Cost

| Piece | Cost |
|---|---|
| GitHub Pages + Actions | Free |
| YouTube / Gmail APIs | Free |
| Reply drafting (optional) | ~cents/month on your own Anthropic key |

Nothing here consumes "credits" you have to buy. The automations are free API calls; the
only metered thing is the optional AI, billed pay-as-you-go on your own key.

## Security checklist
- [ ] Repo is **private** (it holds the xlsx with emails)
- [ ] `creators.json` has no emails (it doesn't — the exporter strips them)
- [ ] Secrets live in GitHub Actions Secrets, never committed (see `.gitignore`)
- [ ] Rotate any API key that was ever pasted in plaintext
