"""
YouTube Creator Discovery Agent
- Searches YouTube Data API v3 for channels matching a niche
- Pulls subscriber count, country, and description via channels.list
- Filters by follower range and (optionally) excludes a handle list (e.g. Jerry's existing affiliates)
- Scores each channel with Claude Haiku (reuses discovery_agent's scorer)
- Appends new prospects to Simify_Influencer_Prospects.xlsx
"""

import os
import time
import argparse
from datetime import date
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from discovery_agent import (
    SPREADSHEET_PATH,
    _extract_email,
    _dedup_key,
    score_profile,
    ensure_spreadsheet,
    load_existing_handles,
    append_prospects,
)

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)


# Transient HTTP statuses worth retrying with backoff.
_RETRYABLE_STATUS = {500, 503, 429}


def _execute_with_retry(request, *, what: str = "YouTube API call", attempts: int = 3, base_delay: float = 2.0):
    """Execute a googleapiclient request with bounded exponential backoff.

    Retries only on transient errors (HTTP 500/503/429). Any other HttpError
    (e.g. 403 quota/invalid key) is re-raised immediately, as is the final
    error once all attempts are exhausted. Dependency-light — no extra pip deps.
    """
    for attempt in range(1, attempts + 1):
        try:
            return request.execute()
        except HttpError as e:
            status = getattr(e.resp, "status", None)
            try:
                status = int(status)
            except (TypeError, ValueError):
                status = None
            if status in _RETRYABLE_STATUS and attempt < attempts:
                delay = base_delay * (2 ** (attempt - 1))
                print(f"  [retry] {what} got HTTP {status} (attempt {attempt}/{attempts}); waiting {delay:.0f}s")
                time.sleep(delay)
                continue
            raise


def load_exclude_handles(path: str) -> set[str]:
    """Read a plain-text file of handles/channel IDs to skip, one per line."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Exclude file not found: {path}")
    return {
        line.strip().lstrip("@").lower()
        for line in p.read_text().splitlines()
        if line.strip()
    }


def search_channel_ids(youtube, query: str, region_code: str, limit: int) -> list[str]:
    """Search for channels matching the query, return unique channel IDs."""
    ids = []
    page_token = None
    while len(ids) < limit:
        resp = _execute_with_retry(
            youtube.search().list(
                part="snippet",
                q=query,
                type="channel",
                maxResults=min(50, limit - len(ids)),
                regionCode=region_code,
                pageToken=page_token,
            ),
            what="search.list",
        )
        ids.extend(item["snippet"]["channelId"] for item in resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return list(dict.fromkeys(ids))


def fetch_channel_details(youtube, channel_ids: list[str]) -> list[dict]:
    """Batch-fetch snippet/statistics/branding, 50 channel IDs per call."""
    channels = []
    for i in range(0, len(channel_ids), 50):
        batch = channel_ids[i:i + 50]
        try:
            resp = _execute_with_retry(
                youtube.channels().list(
                    part="snippet,statistics,brandingSettings",
                    id=",".join(batch),
                ),
                what="channels.list",
            )
        except HttpError as e:
            status = getattr(e.resp, "status", "?")
            print(f"  [warn] channels.list failed (HTTP {status}) for batch of {len(batch)} "
                  f"channel(s); skipping this batch and returning partial results.")
            continue
        channels.extend(resp.get("items", []))
    return channels


def normalise_channel(raw: dict) -> Optional[dict]:
    """Extract a discovery_agent-compatible profile dict from a channels.list item.

    Returns None for channels with hidden subscriber counts — can't verify follower range.
    """
    stats = raw.get("statistics", {})
    if stats.get("hiddenSubscriberCount"):
        return None

    snippet = raw.get("snippet", {})
    branding = raw.get("brandingSettings", {}).get("channel", {})
    description = snippet.get("description", "")

    handle = snippet.get("customUrl") or raw["id"]
    if handle and not handle.startswith("@"):
        handle = f"@{handle}"

    return {
        "name": snippet.get("title", handle),
        "handle": handle,
        "url": f"youtube.com/{handle}",
        "platform": "YouTube",
        "followers": int(stats.get("subscriberCount", 0)),
        "bio": description,
        "country": branding.get("country") or snippet.get("country") or "",
        "email": _extract_email(description),
    }


def run(
    niche: str,
    market: str,
    region: str,
    min_followers: int,
    max_followers: int,
    count: int,
    exclude_file: Optional[str],
    no_score: bool = False,
    dry_run: bool = False,
) -> int:
    """Returns the number of new prospects found (added to the sheet, unless dry_run)."""
    youtube_key = os.environ.get("YOUTUBE_API_KEY")
    if not youtube_key:
        raise EnvironmentError("YOUTUBE_API_KEY is not set in .env")

    client = None
    if not no_score:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if not anthropic_key:
            raise EnvironmentError("ANTHROPIC_API_KEY is not set in .env (or pass --no-score to skip scoring)")
        client = anthropic.Anthropic(api_key=anthropic_key)

    youtube = build("youtube", "v3", developerKey=youtube_key)
    exclude = load_exclude_handles(exclude_file) if exclude_file else set()

    print(f"\nSimify YouTube Creator Discovery")
    print(f"  Niche:     {niche}")
    print(f"  Region:    {region}")
    print(f"  Followers: {min_followers:,}-{max_followers:,}")
    print(f"  Target:    {count} prospects\n")

    # Bias the search toward travel, but don't double-append when the niche
    # already contains "travel" (e.g. "solo travel" -> "solo travel", not
    # "solo travel travel").
    query = niche if "travel" in niche.lower() else f"{niche} travel"
    try:
        channel_ids = search_channel_ids(youtube, query, region, limit=count * 4)
    except HttpError as e:
        if e.resp.status == 403:
            raise RuntimeError(
                "YouTube API quota exceeded or key invalid. search.list costs 100 units/call "
                "against a 10,000/day default quota — try a smaller --count or check YOUTUBE_API_KEY."
            ) from e
        raise
    print(f"Found {len(channel_ids)} candidate channels")

    raw_channels = fetch_channel_details(youtube, channel_ids)
    profiles = []
    skipped_hidden = 0
    for raw in raw_channels:
        p = normalise_channel(raw)
        if p is None:
            skipped_hidden += 1
            continue
        if p["handle"].lstrip("@").lower() in exclude:
            continue
        if min_followers <= p["followers"] <= max_followers:
            profiles.append(p)

    print(f"{len(profiles)} channels within follower range after filtering", end="")
    print(f" ({skipped_hidden} skipped: hidden subscriber count)\n" if skipped_hidden else "\n")

    if not profiles:
        print("Nothing to process. Try a broader niche, region, or follower range.")
        return 0

    if no_score:
        scored = [{
            **p,
            "notes": f"Auto-discovered via YouTube API {date.today().isoformat()} — not yet scored, review manually",
            "niche": niche,
        } for p in profiles]
        print(f"Skipping scoring (--no-score) — {len(scored)} channels ready to review\n")
    else:
        print("Scoring channels with Claude Haiku...")
        scored = []
        for p in profiles:
            result = score_profile(p, market, niche, client)
            if result is None:
                continue
            if result.get("recommended") or result.get("score", 0) >= 7:
                scored.append({
                    **p,
                    "score": result["score"],
                    "notes": f"Score {result['score']}/10 — {result['reason']}",
                    "niche": niche,
                })
                print(f"  PASS  {p['handle']:<30} score={result['score']}  {result['reason'][:60]}")
            else:
                print(f"  skip  {p['handle']:<30} score={result.get('score', '?')}")
        print(f"\n{len(scored)} prospects passed the filter")

    if not scored:
        print("No prospects passed. Try adjusting niche or region.")
        return 0

    if not dry_run:
        ensure_spreadsheet(SPREADSHEET_PATH)
    existing = load_existing_handles(SPREADSHEET_PATH)
    new_prospects = [p for p in scored if _dedup_key(p) not in existing]

    dupes = len(scored) - len(new_prospects)
    if dupes:
        print(f"{dupes} already in spreadsheet — skipped")

    if not new_prospects:
        print("All prospects are already in the spreadsheet.")
        return 0

    if dry_run:
        print(f"\n[DRY RUN — nothing written] {len(new_prospects)} would be added:")
        for p in new_prospects:
            print(f"  {p['name']:<40} {p['followers']:>7,} subs   {p['country']:<4}  {p['url']}")
        return len(new_prospects)

    append_prospects(SPREADSHEET_PATH, new_prospects)

    emails_found = sum(1 for p in new_prospects if p["email"])
    print(f"\nDone.")
    print(f"  {len(new_prospects)} new prospects added to {SPREADSHEET_PATH.name}")
    print(f"  {emails_found} had email addresses in their channel description")
    return len(new_prospects)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Discover YouTube creator prospects for Simify via the YouTube Data API"
    )
    parser.add_argument("--niche", default="travel", help="Content niche, e.g. 'travel', 'digital nomad', 'backpacking'")
    parser.add_argument("--market", default="Australia", help="Target audience market, used as scoring context")
    parser.add_argument("--region", default="AU", help="YouTube regionCode to bias search results")
    parser.add_argument("--min-followers", type=int, default=1000)
    parser.add_argument("--max-followers", type=int, default=100000)
    parser.add_argument("--count", type=int, default=20, help="Target number of new prospects")
    parser.add_argument(
        "--exclude-file", default=None,
        help="Path to a text file of handles/channel IDs to skip, one per line (e.g. Jerry's existing affiliate roster)",
    )
    parser.add_argument(
        "--no-score", action="store_true",
        help="Skip Claude Haiku scoring — write all channels in the follower range straight to the spreadsheet for manual review",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be added without writing to the spreadsheet",
    )
    args = parser.parse_args()

    run(
        niche=args.niche,
        market=args.market,
        region=args.region,
        min_followers=args.min_followers,
        max_followers=args.max_followers,
        count=args.count,
        exclude_file=args.exclude_file,
        no_score=args.no_score,
        dry_run=args.dry_run,
    )
