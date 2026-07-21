#!/usr/bin/env python3
"""
enrich_prospects.py — turn the sourced roster into a Discovery batch.

Reads docs/data/creators.json, looks up each channel via the YouTube Data API
(channel handle -> channelId + uploads playlist + latest video + last-upload
date), DROPS anyone who hasn't posted in >8 months, and writes
docs/data/prospects.json for the Creators -> Discovery tab (inline video +
one-click Add/Skip).

Cost: ~2 quota units per creator (channels.list + playlistItems.list). For a
~500-channel roster that's ~1,000 units, well within the default 10,000/day.

Usage:
    # put your key in workers/.env  ->   YOUTUBE_API_KEY=AIza...
    python3 workers/enrich_prospects.py
    # options:
    python3 workers/enrich_prospects.py --months 8 --limit 0 --min-subs 0

Resumable: caches per-handle lookups in workers/.prospects_cache.json so a
re-run only fetches new/failed channels.
"""
import os, sys, json, time, argparse, datetime, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREATORS = os.path.join(ROOT, "docs", "data", "creators.json")
OUT = os.path.join(ROOT, "docs", "data", "prospects.json")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".prospects_cache.json")
API = "https://www.googleapis.com/youtube/v3"


def load_key():
    key = os.environ.get("YOUTUBE_API_KEY")
    if key:
        return key.strip()
    envp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(envp):
        for line in open(envp):
            line = line.strip()
            if line.startswith("YOUTUBE_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("YOUTUBE_API_KEY not found. Add it to workers/.env or export it.")


def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def api(key, path, **params):
    params["key"] = key
    return get(API + "/" + path + "?" + urllib.parse.urlencode(params))


def months_ago(iso):
    try:
        d = datetime.datetime.fromisoformat(str(iso).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - d).days / 30.44
    except Exception:
        return None


def norm_handle(h):
    return str(h or "").strip().lstrip("@")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=float, default=8.0, help="drop channels quiet longer than this")
    ap.add_argument("--limit", type=int, default=0, help="cap number of creators processed (0 = all)")
    ap.add_argument("--min-subs", type=int, default=0, help="skip channels below this sub count")
    args = ap.parse_args()

    key = load_key()
    data = json.load(open(CREATORS))
    creators = data.get("creators", data) if isinstance(data, dict) else data
    if args.limit:
        creators = creators[: args.limit]

    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    prospects, dropped, failed = [], 0, 0

    for i, c in enumerate(creators, 1):
        handle = norm_handle(c.get("handle"))
        if not handle:
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
                    uploads = it["contentDetails"]["relatedPlaylists"]["uploads"]
                    pl = api(key, "playlistItems", part="snippet,contentDetails", playlistId=uploads, maxResults=1)
                    pit = (pl.get("items") or [{}])[0]
                    vid = pit.get("contentDetails", {}).get("videoId", "")
                    published = pit.get("contentDetails", {}).get("videoPublishedAt") or pit.get("snippet", {}).get("publishedAt", "")
                    rec = {
                        "ok": True,
                        "channelId": it["id"],
                        "subs": int(it.get("statistics", {}).get("subscriberCount", 0) or 0),
                        "videoId": vid,
                        "lastUpload": (published or "")[:10],
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

        m = months_ago(rec["lastUpload"]) if rec.get("lastUpload") else None
        if m is not None and m > args.months:
            dropped += 1
            continue
        subs = rec.get("subs") or 0
        if subs < args.min_subs:
            continue

        prospects.append({
            "name": c.get("name"),
            "handle": "@" + handle,
            "channelId": rec["channelId"],
            "subs": subs or c.get("subs"),
            "niche": c.get("niche", ""),
            "market": c.get("market", ""),
            "videoId": rec.get("videoId", ""),
            "lastUpload": rec.get("lastUpload", ""),
            "email": c.get("email", ""),
        })
        if i % 25 == 0:
            print(f"  ...{i}/{len(creators)} processed ({len(prospects)} kept, {dropped} dropped)")

    # newest-active first
    prospects.sort(key=lambda p: p.get("lastUpload", ""), reverse=True)
    out = {
        "generated": datetime.date.today().isoformat(),
        "source": "roster enrichment (enrich_prospects.py)",
        "note": f"Active roster channels (posted within {args.months:.0f} months). {dropped} dropped as inactive.",
        "prospects": prospects,
    }
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=2)
    print(f"\nDone. {len(prospects)} active -> {OUT}. Dropped {dropped} inactive, {failed} not found/failed.")


if __name__ == "__main__":
    main()
