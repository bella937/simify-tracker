# Simify YouTube Gifting & Affiliate Tracker — Session Handoff

_Last updated: 2026-07-21_

A working CRM for Simify's YouTube gifting + affiliate programme. Started as a static
dashboard; now a real, auto-saving CRM used daily by Bella (Influencer Partnerships).
This doc is the pick-up point for a new session.

---

## 1. Where everything lives

| Thing | Value |
|---|---|
| **Live site** | https://simify-tracker.pages.dev (behind Cloudflare Access — Bella login only) |
| **Repo** | `~/AI Projects/simify-tracker` · GitHub `bella937/simify-tracker` (private) |
| **The app** | **one file**: `docs/index.html` (~1 MB, hand-written HTML+CSS+vanilla JS) |
| **Gmail backend** | Cloudflare Pages Functions in `functions/api/*.js` |
| **Data files** | `docs/data/creators.json` (roster), `briefs.json`, `creative-intelligence.json` |
| **Python tools** | `workers/*.py` (discovery, outreach, export) — CLI; `source_prospects.py` also runs **weekly via GitHub Actions** (`.github/workflows/discovery.yml`) |
| **Hosting** | Cloudflare Pages, **auto-deploys `main`** (publish dir = `docs/`) |

There are **two Cloudflare Pages projects on this repo**:
- `simify-tracker` → publishes `docs/` → **the CRM** (this project)
- `simify-creators` → publishes `creator-site/` → a separate public creator page (built by a
  parallel session). Its red ✗ on feature-branch PRs is **benign** (it fails on branches that
  lack `creator-site/`; fine on `main`).

---

## 2. How changes go live (IMPORTANT — auto-publish is ON)

Bella chose **auto-publish**: commit to `main` → Cloudflare auto-deploys to the live site in
~1 min. **No PRs, no manual merge.** She does not want to click merge for every change.

**Safe push pattern (used all session)** — because a second Claude session shares this working
tree, don't edit/commit on the shared checkout. Use an isolated worktree on `origin/main`:

```bash
cd ~/AI\ Projects/simify-tracker
git fetch origin -q
WT=/tmp/simify-wt && rm -rf "$WT"
git worktree add --detach "$WT" origin/main -q
# ...edit files inside "$WT" (e.g. "$WT/docs/index.html")...
git -C "$WT" add -A && git -C "$WT" commit -m "..."
git -C "$WT" push origin HEAD:main          # triggers the live deploy
git worktree remove "$WT" --force && git worktree prune
```

Confirm the deploy on the Cloudflare dashboard (Bella is logged in via the in-app Browser):
`https://dash.cloudflare.com/a286dcdc366a59a5516762c9085daee0/pages/view/simify-tracker`
Production should show `main @ <your commit>`.

**End every commit message with:** `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## 3. How to verify a change (do this before pushing)

The Gmail-backed features can't be tested locally (no secrets), but everything else can:

```bash
python3 -m http.server 8802 --directory ~/AI\ Projects/simify-tracker/docs   # or the worktree's docs
```
Open it in the in-app Browser, then drive it: check `read_console_messages` for errors, click
through the changed flow, reload to confirm persistence. For inbox features (which need
`/api/drafts` etc.), **mock `window.fetch`** in the browser to return fake drafts and exercise
the UI.

---

## 4. Architecture & persistence

- **`SimifyStore`** (top of `docs/index.html`) is the unified persistence layer. One versioned
  localStorage key `simify_store_v1`, debounced auto-save, cross-tab sync, JSON Backup/Restore
  (bottom-left "All changes saved" pill). **Everything reads/writes through it** — this is the
  seam to later swap in a real backend (Supabase/D1) without touching feature code.
- **Namespaces in the store:** `triage` (per-creator flags/email/tags/outreached, keyed by a
  stable id or handle), `daily` (draft counter), `crm` (per-email: stage/priority/follow/
  campaign/affiliate/notes), `creatorsAdded` (manually-added creators), `campaigns` (array),
  `deliverables` (map `campaignId::creatorKey`), `affiliate` (map `campaignId::creatorKey`),
  `ui` (`segments`, `inbox` archive/delete map, `sent` history).
- **Roster** = `docs/data/creators.json` (server-owned, ~498 creators) + the local overlay
  (adds/edits/tags/outreached). Merged on load.
- **Long-term recommendation (not built):** move the system of record to **Supabase (Postgres)**;
  Cloudflare D1 is the no-new-vendor alternative. See the Architecture & Migration Plan artifact
  (phased strangler-fig migration) — link is in the chat history / ask Bella.

---

## 5. What's built (all live)

- **Persistence** — auto-save, survives refresh/restart, Backup/Restore.
- **Overview** — roster stats + a **"Today"** action hub (follow-ups due / ready-to-draft /
  to-review / commission owed, each jumps to its view).
- **Creators** — triage table: **✓ = mark Outreached** (reversible toggle, syncs Pipeline +
  Overview), **× = skip**, **✉ = draft one email**, **🗑 = remove**. Inline email edit, **tags**
  + **saved segments**, market filter, **Import CSV** (dedupe) + **Export CSV** (incl. CRM fields).
- **Campaigns** — first-class objects (name/market/dates/budget/brief/status), assign creators,
  per-campaign rollup (creators/submitted/approved/% + ROI).
- **Content review** — creator submissions per campaign: paste link, compliance checklist,
  Approve / Request changes / Mark live; filter tabs.
- **Affiliate & revenue** — code + clicks/redemptions/revenue/commission (15% default) per
  creator; KPI strip. (Manual entry; built for a future Shopify + Impact.com sync.)
- **Analytics** — outreach funnel, content throughput, revenue by market/campaign, campaign ROI.
- **Automated inbox** — Gmail **drafts** list + editor (edit To/Subject/Body, Save, Send). Now
  also: **＋ New email** composer, **Archive / Remove** (reversible, Gmail draft preserved), and a
  **Sent** tab (sent emails logged locally with a read-only view).
- **⌘K** command palette — global search + jump to any page/creator/campaign.
- **Auto-discovery** — `.github/workflows/discovery.yml` runs `source_prospects.py` every Mon
  06:00 UTC (+ manual `workflow_dispatch`), sourcing fresh on-pattern leads into
  `docs/data/prospects.json` → the **Discovery** tab. Rotates an 8-query window through a
  24-niche pool (3-week cycle) + rotates region order by ISO week. Uses the `YOUTUBE_API_KEY`
  repo secret only; commits (and thus deploys) only when new leads are found; opens a GitHub
  issue on failure. **Note:** the git token now has `workflow` scope, so `.github/workflows/`
  files can be pushed via the worktree pattern.
- **Creative Intelligence** — dated snapshot from Motion (paid-ad creative analytics) + Brief Builder.
- Accessibility pass (focus rings, reduced-motion, tap targets, aria).

---

## 6. Outreach email template (current default)

Generated by `functions/api/draft.js` (`subjectLine`/`bodyText`/`bodyHtml`) and mirrored in
`workers/outreach.py`. Keep them identical. **Rule: plain hyphen `-`, never em dash.**

- **Subject:** `{Creator} get paid to travel - Partnership with Simify ✈️`
- **Body:** `Hey {Creator}` → tailored first line (`firstLine`, from niche) → "I'm Bella from
  Simify - we're a Travel eSIM brand trusted by 1M+ travellers, and we're inviting you to join
  our YouTube affiliate programme. Here's how it works:" → 4 offer bullets (🎁 $100 USD voucher /
  📱 Short or integration / 💸 15% commission / 🚀 featured in paid campaigns) → "Let me know if
  you're interested…" → signature.
- The signature comes from Bella's **Gmail signature** (auto-appended). The "Unlimited Data ·
  190+ destinations" banner some drafts show is part of that Gmail signature, **not** the
  template — remove it in Gmail settings, or ask to strip `<img>` from the signature in `draft.js`.

**Gmail safety invariant:** the backend is **draft-only + single human-click send**. Never add a
bulk-send or auto-send path. Never wire permanent email/draft deletion (archive/remove in the
inbox are local + reversible by design). `functions/api/` endpoints: `draft.js` (batch create),
`draft-new.js` (create one blank), `draft-update.js`, `draft-get.js`, `drafts.js` (list),
`send.js` (send one), `_gmail.js` (shared helpers).

---

## 7. Gotchas learned this session (read before editing)

- **`[hidden]` vs CSS `display`:** a class rule like `.kbar{display:flex}` overrides the HTML
  `hidden` attribute (equal specificity, later in source) → the element shows even when
  "hidden". Always add a `.thing[hidden]{display:none}` guard (like `.modal[hidden]` does).
  And **verify visibility via computed `display`, not the `.hidden` property.**
- **Zero-width chars:** an invisible ZWNJ (U+200C) once slipped into a JS string and broke the
  parser. If JS mysteriously fails, check with:
  `python3 -c "d=open('docs/index.html').read(); print(d.count('‌'), d.count('​'))"`
- **Concurrency:** a second Claude session works in this same repo/worktree (owns
  `creator-site/` + sometimes the outreach template). It can change files under you and its dev
  server can grab ports. Always edit the **current `origin/main`** version (via worktree), never a
  stale local branch, or you'll clobber its work. Ideally one session owns the email/outreach code.
- **`docs/index.html` is huge & hand-written.** Edit by unique anchor strings. This monolith is the
  #1 tech-debt item — see the migration plan.

---

## 8. Roadmap / open items

- **Batch "Draft flagged" button** is now vestigial (✓ = Outreached replaced the old
  flag→batch-draft flow). Decide: repurpose it (draft all shown emailable non-outreached) or remove it.
- **Gmail-signature banner** removal (Bella's Gmail settings, or strip signature images in code).
- **Architecture rebuild** — Vite + TypeScript + component framework + Supabase, phased/strangler
  (plan already written as an artifact). The big one; needs Bella's go, not to be done blind.
- Deferred integrations that need a backend: Shopify + Impact.com (affiliate revenue sync),
  Gmail thread ingestion (auto-detect replies/submissions), outreach sequences, live CI refresh.

---

## 9. Working style Bella prefers

- **Ship fast, verify each change, keep a human gate on anything that goes outward** (sends, deletes).
- Don't ask permission for every step — just build, verify, push, and report. Flag genuinely
  risky/ambiguous things (permanent deletes, big rewrites) before acting.
- Auto-publish is on: changes go live on push to `main`.
