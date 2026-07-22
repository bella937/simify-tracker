#!/usr/bin/env python3
"""
roster_to_discovery.py — vet the roster's NEW LEADS and build a Discovery shortlist.

For every creator in docs/data/creators.json whose status is "New lead":
  1. resolve handle -> channelId via the YouTube Data API,
  2. fetch subs + channel title/description + latest video + last-upload date,
  3. DROP anyone who hasn't posted in the last --months (default 6),
  4. SCORE the survivors against Bella's ideal-creator pattern
     (nano-micro sweet spot, AU/UK/NZ/US/CA, on-pattern travel niches, recency,
      female-led / personal signals), and
  5. keep the top --top (default 100), newest-and-best first.

Writes a STAGING file (docs/data/prospects_candidates.json) by default so nothing
is overwritten until reviewed. Pass --write to overwrite docs/data/prospects.json.

Cost: ~2 quota units/creator (channels.list + playlistItems.list) -> ~1k units for
the ~488 new leads, well within the 10k/day default. Resumable via a local cache.

Usage:
    python3 workers/roster_to_discovery.py                 # stage top 100, 6 months
    python3 workers/roster_to_discovery.py --months 6 --top 100
    python3 workers/roster_to_discovery.py --write         # write prospects.json
"""
import os, sys, json, time, re, argparse, datetime, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREATORS = os.path.join(ROOT, "docs", "data", "creators.json")
STAGE = os.path.join(ROOT, "docs", "data", "prospects_candidates.json")
LIVE = os.path.join(ROOT, "docs", "data", "prospects.json")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".roster_disc_cache.json")
API = "https://www.googleapis.com/youtube/v3"

GOOD_MARKETS = {"AU", "GB", "UK", "NZ", "US", "CA"}
TOP_MARKETS = {"AU", "GB", "UK", "NZ"}  # pattern is UK-heavy + AU/NZ, then US/CA

# On-pattern niche signals (checked against roster niche + channel title/description).
STRONG_NICHE = re.compile(
    r"van ?life|#vanlife|sailing|sailboat|liveaboard|yacht|solo female|solo travel|"
    r"slow travel|wild camping|overland|road ?trip|caravan|motorhome|campervan|"
    r"backpack|hiking|thru-?hike|digital nomad|off.?grid|tiny (home|living)|"
    r"family travel|worldschool|couple travel|couple who travel", re.I)
TRAVEL_NICHE = re.compile(r"travel|wanderlust|adventure|explore|nomad|expat|lifestyle|vlog", re.I)
OFF_PATTERN = re.compile(
    r"gear review|compilation|top \d+|news|documentary|drone footage only|"
    r"stock footage|highlights channel|clips", re.I)
# Soft female-led / personal signals (a bonus, never a hard filter).
FEMALE_HINT = re.compile(r"\b(she|her|hers|woman|women|girl|mum|mom|wife|solo female|female)\b", re.I)


def load_key():
    k = os.environ.get("YOUTUBE_API_KEY")
    if k:
        return k.strip()
    envp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(envp):
        for line in open(envp):
            if line.strip().startswith("YOUTUBE_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("YOUTUBE_API_KEY not found in workers/.env")


def api(key, path, **p):
    p["key"] = key
    url = API + "/" + path + "?" + urllib.parse.urlencode(p)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def months_ago(iso):
    try:
        d = datetime.datetime.fromisoformat(str(iso).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - d).days / 30.44
    except Exception:
        return None


def norm_handle(h):
    return str(h or "").strip().lstrip("@")


def score(rec, roster_niche):
    """Return (score, why-note) for an active channel."""
    subs = rec.get("subs") or 0
    market = (rec.get("market") or "").upper()
    text = (rec.get("title", "") + " " + rec.get("desc", "") + " " + (roster_niche or "")).strip()
    m = rec.get("months")
    pts, notes = 0, []

    # recency (0-30): posted today ~30, ~6 months ago ~0
    if m is not None:
        pts += max(0, round((6 - min(m, 6)) / 6 * 30))

    # subscriber sweet spot (nano-micro)
    if 3000 <= subs <= 20000:
        pts += 30; notes.append("nano-micro sweet spot")
    elif 1000 <= subs < 3000 or 20000 < subs <= 40000:
        pts += 22; notes.append("nano-micro")
    elif 40000 < subs <= 100000:
        pts += 8
    elif subs < 1000:
        pts += 5
    else:  # >100K
        pts += 2; notes.append("larger than sweet spot")

    # market fit
    if market in TOP_MARKETS:
        pts += 15
    elif market in GOOD_MARKETS:
        pts += 10
    elif market:
        notes.append("off-target market")

    # niche fit
    if STRONG_NICHE.search(text):
        pts += 22; notes.append("on-pattern niche")
    elif TRAVEL_NICHE.search(text):
        pts += 12; notes.append("travel/lifestyle")
    if OFF_PATTERN.search(text):
        pts -= 15; notes.append("off-pattern format")

    # soft female-led / personal signal
    if FEMALE_HINT.search(text):
        pts += 8; notes.append("female-led/personal signal")

    return pts, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=float, default=6.0)
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--write", action="store_true", help="overwrite prospects.json (default: stage)")
    ap.add_argument("--limit", type=int, default=0, help="cap creators processed (debug)")
    args = ap.parse_args()

    key = load_key()
    data = json.load(open(CREATORS))
    creators = data.get("creators", data) if isinstance(data, dict) else data
    leads = [c for c in creators if (c.get("st") or ["", ""])[1] == "New lead"]
    if args.limit:
        leads = leads[: args.limit]
    print(f"New leads to vet: {len(leads)}")

    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    active, dropped, failed = [], 0, 0

    for i, c in enumerate(leads, 1):
        handle = norm_handle(c.get("handle"))
        if not handle:
            failed += 1
            continue
        rec = cache.get(handle)
        if rec is None:
            try:
                ch = api(key, "channels", part="snippet,contentDetails,statistics", forHandle=handle)
                items = ch.get("items") or []
                if not items:
                    rec = {"ok": False}
                else:
                    it = items[0]
                    sn = it.get("snippet", {})
                    uploads = it["contentDetails"]["relatedPlaylists"]["uploads"]
                    pl = api(key, "playlistItems", part="contentDetails,snippet", playlistId=uploads, maxResults=1)
                    pit = (pl.get("items") or [{}])[0]
                    vid = pit.get("contentDetails", {}).get("videoId", "")
                    pub = (pit.get("contentDetails", {}).get("videoPublishedAt")
                           or pit.get("snippet", {}).get("publishedAt") or "")[:10]
                    rec = {
                        "ok": True,
                        "channelId": it["id"],
                        "subs": int(it.get("statistics", {}).get("subscriberCount", 0) or 0),
                        "hidden": bool(it.get("statistics", {}).get("hiddenSubscriberCount")),
                        "title": sn.get("title", ""),
                        "desc": (sn.get("description", "") or "")[:600],
                        "country": sn.get("country", ""),
                        "videoId": vid,
                        "lastUpload": pub,
                    }
                cache[handle] = rec
                json.dump(cache, open(CACHE, "w"))
                time.sleep(0.05)
            except Exception as e:
                failed += 1
                print(f"  ! {handle}: {e}")
                continue
        if not rec.get("ok"):
            failed += 1
            continue

        m = months_ago(rec.get("lastUpload")) if rec.get("lastUpload") else None
        if m is None or m > args.months:
            dropped += 1
            continue

        market = (rec.get("country") or c.get("market") or "").upper()
        if market == "GB":
            market = "UK"
        rec2 = {**rec, "months": m, "market": market}
        pts, notes = score(rec2, c.get("niche", ""))
        subs = rec.get("subs") or 0
        why = (f"{subs:,} subs · {market or '—'} · last posted {rec.get('lastUpload')} "
               f"({m:.1f} mo ago). " + ("; ".join(notes) + "." if notes else ""))
        active.append({
            "name": c.get("name"),
            "handle": "@" + handle,
            "channelId": rec["channelId"],
            "subs": subs or c.get("subs"),
            "niche": c.get("niche", "") or "General",
            "market": market,
            "videoId": rec.get("videoId", ""),
            "lastUpload": rec.get("lastUpload", ""),
            "email": c.get("email", ""),
            "why": why,
            "_score": pts,
        })
        if i % 25 == 0:
            print(f"  ...{i}/{len(leads)} ({len(active)} active, {dropped} dropped, {failed} failed)")

    # rank: best score first, then most-recent upload
    active.sort(key=lambda p: (p["_score"], p.get("lastUpload", "")), reverse=True)
    top = active[: args.top]
    cut = top[-1]["_score"] if top else 0
    print(f"\nActive (<= {args.months:.0f} mo): {len(active)} | dropped inactive: {dropped} | "
          f"unresolved: {failed}")
    print(f"Keeping top {len(top)} (score cutoff {cut}). Score range "
          f"{top[0]['_score'] if top else 0}..{cut}.")

    out = {
        "generated": datetime.date.today().isoformat(),
        "source": "roster new-leads vetted + ranked (roster_to_discovery.py)",
        "note": (f"Top {len(top)} New-lead creators active within {args.months:.0f} months, "
                 f"ranked to Bella's pattern (nano-micro, AU/UK/NZ/US/CA, on-pattern travel). "
                 f"{dropped} dropped as inactive, {failed} unresolved."),
        "prospects": top,
    }
    dest = LIVE if args.write else STAGE
    json.dump(out, open(dest, "w"), ensure_ascii=False, indent=2)
    print(f"Wrote {len(top)} -> {dest}")


if __name__ == "__main__":
    main()
