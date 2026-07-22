# Session Handoff — Inbox Redesign + Creators UX

_Written 2026-07-22. Complements the main `HANDOFF.md` (read that first for repo basics:
one-file app, Cloudflare auto-publish on `main`, safe-push worktree pattern, Gmail safety
invariant). This doc covers what changed **this session** and what's left._

To pick up: open a new Claude Code session in `~/AI Projects/simify-tracker` and say
_"Read SESSION-SUMMARY-inbox-crm.md and HANDOFF.md, then continue."_

---

## TL;DR

The **Inbox** was rebuilt from a drafts-only list into a **threaded, Gmail-synced campaign
workspace** with a **campaign command centre** on every conversation. The **Creators tab** got
an inline add-row, collapsible sections, and a column filter. Everything below is **live on
`main`** (auto-deployed to https://simify-tracker.pages.dev, behind Cloudflare Access). Gmail
**full read sync is confirmed working** (the token has `gmail.readonly` + `gmail.compose`).

**Only remaining item: Phase 5 — two-way write-back to Gmail** (archive/mark-read reflecting
back to Gmail). It needs a one-time re-auth to add the `gmail.modify` scope (steps below).

---

## What shipped this session (all live on `main`)

Commits (newest first): `de5515c` (Creators UX + handle link), `4a81f66` (inbox redesign),
`bbe150d` (composer width fix), `90c9040` (read endpoints).

### Backend — new Cloudflare Pages Functions (`functions/api/`)
- **`threads.js`** `GET /api/threads?q=&max=&pageToken=` — lists conversations (default
  `in:inbox OR in:sent`) with per-thread metadata, batched 6-at-a-time to respect Gmail quota;
  returns summaries + mailbox `historyId`.
- **`thread.js`** `GET /api/thread?id=` — full thread: every message (from/to/date/labels/
  html/text/attachment metadata), in order.
- **`history.js`** `GET /api/history?startHistoryId=` — cheap incremental poll; returns changed
  thread ids, or `{expired:true}` to trigger a full reload.
- **`draft-compose.js`** `POST` — create ONE draft (new email OR in-thread reply via
  `threadId`+`inReplyTo`+`references`); auto-appends the Gmail signature. **Draft-only.**
- **`_gmail.js`** — added exported `rawMessageThreaded({...})` and `getSignature(tok)`.
- **`draft-update.js`** — extended (back-compatible) to accept `threadId/inReplyTo/references`
  so editing a reply draft doesn't detach it from its thread.
- All read endpoints are read-only; **no new send/bulk/delete/auto-send path was added.**

### Inbox (single-file app `docs/index.html`, the Inbox IIFE)
- **Unified conversation list**: real Gmail threads (inbox+sent) merged with unsent drafts;
  unread dots, campaign chips, stage pills, follow-up-due badges, msg counts, Draft badges.
- **Threaded detail**: full history **newest-first**, latest expanded, older collapsed
  (click to expand), Expand-all toggle, **key-event badges** (📎 attachments, Approved,
  Shipping, Positive, Declined, Money) + attachment chips.
- **~45s polling** (`/api/history`, fallback `/api/threads`) + on tab-focus, so new mail
  appears without a manual refresh.
- **Campaign command centre** banner on every conversation, resolving live store data:
  campaign + status (clickable → campaign), creator status, product-shipped (derived from
  stage, toggleable), content-review status, affiliate (code + revenue), priority, next
  follow-up, campaign manager, **next recommended action**, **outstanding items**, and
  conversation-linked **tasks**.
- **Quick actions**: Move stage · Request revision · Mark approved · Send follow-up · Create task.
- **Composer**: in-thread reply, auto-signature, reusable **templates** with `{{creator}}` /
  `{{campaign}}` / `{{affiliate_link}}` / `{{signoff}}` variables, debounced **autosave**.
  New-email compose now routes through `draft-compose` (so it also gets the signature).
- Degrades gracefully: if the token ever lacks `readonly`, it falls back to drafts-only + a
  "full sync needs Gmail read access" note — nothing breaks.
- `@handle` in the command centre is a clickable link to the creator's YouTube channel.
- **AI drafting/proofreading was intentionally deferred** (Bella's call) — no AI button shipped.

### Creators tab (`docs/index.html`, Creators IIFE)
- **Inline add-row** replaces the Add-creator popup: "Add creator" (topbar `.ghost` **and** a
  new in-view `#crAddRow` button) drops an editable row into a new **"Unsorted"** section; the
  ✓ tick validates (name required, auto-prefixes `@`, coerces subs) → moves it to **New leads**
  via `window.simAddCreator`. Old modal (`#addModal`) kept as a fallback.
- **Collapsible sections**: caret (▾/▸) in each status group header; state persists in
  `SimifyStore` `ui.crCollapsed`.
- **Filter bar** (`#crFilter` + `#crFilterCol`): free-text across all columns, or scoped to one
  column (Creator/Handle/Email/Market/Subs/Niche/Tags/Status), with Clear. Stacks on top of the
  existing global search + market/tag filters (`filtered()`).

### SimifyStore
- New namespace **`tasks`** = `[{id,email,threadId,campaignId?,title,due,done,createdAt}]`.
- New `ui.crCollapsed` = `{ [statusName]: true }`.

---

## Key mechanics to know before editing

- **Conversation ↔ creator ↔ campaign resolution** (`resolveCtx(email)` in the Inbox IIFE):
  email → `window.simCreatorByEmail` → match into a campaign (by `crm[email].campaign` name,
  or by membership via `simCreatorByKey` identity match) → `deliverables[campId::key]` +
  `affiliate[campId::key]`. CRM is **email-keyed**; campaigns/deliverables/affiliate are
  **creatorKey-keyed** (`campId::key`) — this resolver is the bridge. `simCreatorByEmail`/
  `simCreatorByKey` return a **projection** (`{name,handle,subs,market,niche,statusLabel}`) —
  no email/id — so identity matching uses handle/name.
- **Pending add-rows** live in an in-memory `PENDING` array (not persisted until confirmed).
  Their inputs update `PENDING` via delegated `input`/`change` listeners **without re-render**
  (to keep focus); the list only re-renders on confirm/discard.
- **Big edits to `docs/index.html`**: it's a ~1 MB hand-written monolith. The Inbox IIFE was
  replaced by splicing between unique start/end marker strings via a Python one-liner (Edit's
  exact-match is impractical for 200-line blocks). Prefer unique-anchor Edits for small changes.

---

## Remaining work — Phase 5: two-way write-back (needs re-auth)

Read-from-Gmail works today. Writing app actions **back** to Gmail (archive → remove `INBOX`
label; mark-read → remove `UNREAD`) needs the `gmail.modify` scope, which the current token
lacks. Plan:

1. Build **`functions/api/modify.js`** `POST {id, addLabelIds, removeLabelIds}` calling
   `users.threads.modify`. Guard it: on `403 insufficient scope` return `{scope:false}` and the
   frontend keeps today's local-only archive/read overlay (`ui.inbox`). When scope is present,
   wire the inbox archive/mark-read actions to call it.
2. **One-time re-auth (Bella must do this — Claude cannot):**
   - In `workers/email_agent.py` `SCOPES` (~line 32) add
     `"https://www.googleapis.com/auth/gmail.modify"` (keep readonly + compose; optionally add
     `gmail.settings.basic` for the signature read).
   - Delete `workers/token.json`, run the script once locally to complete the OAuth browser
     flow → new `token.json`.
   - Update the Cloudflare **`GMAIL_REFRESH_TOKEN`** secret (Pages → simify-tracker → Settings →
     Env vars) with the new refresh token; redeploy.
   - Write-back turns on automatically once the scope check passes — no frontend change needed.

Other deferred (need a backend/vendor, not started): AI drafting engine (Cloudflare Workers AI
or an Anthropic key), scheduled/auto-send (would break the human-click invariant — treat
carefully), Shopify + Impact.com affiliate sync, Gmail push (Pub/Sub) — polling is the current
substitute.

---

## How to verify changes

Gmail-backed features can't run locally (no secrets). Per `HANDOFF.md §3`:
- Serve the worktree's docs: `python3 -m http.server 8802 --directory <worktree>/docs`, open in
  the in-app Browser.
- For endpoints, **mock `window.fetch`** to return sample `/api/threads` + `/api/thread` +
  `/api/drafts`, and stub `window.simCreatorByEmail` / `simCreatorByKey` / `simKeyOf` to
  exercise the command-centre resolver, quick actions, tasks, threading, and reply autosave.
- Seed `SimifyStore` (`campaigns`/`deliverables`/`affiliate`/`crm`) to test the resolver; align
  deliverable/affiliate keys to `campId::<keyOf>` (e.g. `cmp1::wanderlens`).
- After deploy, the real test is opening the live site (behind Access — only Bella can log in).
- **Always re-check the safety invariant**: draft-only + single human-click send; no bulk/auto
  send; archive/remove stay local + reversible.

## Deploy / concurrency notes

- Auto-publish is ON: push to `main` → live in ~1 min. Use the isolated-worktree safe-push
  pattern (`HANDOFF.md §2`); **re-fetch/rebase before every push** — a second Claude session
  shares this repo (it owns `creator-site/` and had been editing the Inbox/Creators code too).
- The `/tmp` worktree can be cleared between turns — push to a branch or `main` to avoid losing
  work; don't rely on `/tmp/simify-wt` persisting.
- Plan file for this work: `~/.claude/plans/mossy-riding-hinton.md`.
