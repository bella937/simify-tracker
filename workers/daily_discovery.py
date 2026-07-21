"""
Daily driver for youtube_discovery_agent.py.

Rotates the search niche by day so repeated runs surface new candidates
instead of mostly re-finding the same channels, and tops up with the next
niche(s) in rotation if the day's first niche doesn't reach TARGET_NEW_LEADS
(YouTube search yield varies day to day — a fixed single niche can't
guarantee a count).

No scoring by default (ANTHROPIC_API_KEY not required) — new channels land
in the spreadsheet as "New" for manual review.
"""

import argparse
from datetime import date, timedelta

import export_prospects_json
import youtube_discovery_agent as yda

# Niches tuned to the "Global 100+ Prospects" reference sheet: lifestyle + travel
# creators who make snackable short-form (the point of gifting = content for paid
# ads). Vlog-flavoured queries skew toward gen-z/millennial faces-on-camera
# creators rather than faceless/stock travel channels.
# Retuned to Bella's winning pattern (2026-07): nano-micro, FEMALE-LED /
# personal, face-forward slow-travel creators. Persona-tight queries bias the
# YouTube search away from big faceless / male gear-review / aviation channels.
NICHES = [
    "solo female travel vlog", "solo female van life", "van life couple",
    "wild camping solo", "solo hiking vlog", "sailing couple liveaboard",
    "digital nomad woman", "slow travel vlog", "aesthetic travel vlog",
    "couple travel vlog", "adventure travel woman", "solo female road trip",
]

# Rotate the search market daily instead of AU-only. English-primary markets:
# the AU home base + the UK/NZ expansion focus + the US/CA (largest creator pools
# and the biggest paid-ad audiences). (regionCode, human name for scoring prompt.)
REGIONS = [
    ("AU", "Australia"), ("GB", "United Kingdom"), ("US", "United States"),
    ("CA", "Canada"), ("NZ", "New Zealand"),
]

TARGET_NEW_LEADS = 50
MAX_NICHES_PER_RUN = 4  # safety cap on YouTube API quota use per day
COUNT_PER_NICHE = 40
MIN_SUBS = 1_000        # nano floor
MAX_SUBS = 40_000       # nano-micro sweet spot (Bella's examples top out ~33K); keeps big/off-pattern channels out


def niches_for(target_date: date) -> list[str]:
    start = target_date.toordinal() % len(NICHES)
    return [NICHES[(start + offset) % len(NICHES)] for offset in range(MAX_NICHES_PER_RUN)]


def region_for(target_date: date) -> tuple[str, str]:
    """One market per day, cycling through REGIONS so a week covers them all
    (keeps daily API quota the same as the old AU-only run)."""
    return REGIONS[target_date.toordinal() % len(REGIONS)]


def main():
    parser = argparse.ArgumentParser(description="Daily nano/micro/small YouTube lead discovery")
    parser.add_argument("--date", default=None, help="ISO date to compute the niche/region rotation for (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be added without writing to the spreadsheet")
    parser.add_argument("--score", action="store_true",
                        help="Quality-filter with Claude (needs ANTHROPIC_API_KEY): keeps only creators who fit the "
                             "short-form / ad-ready / gen-z-millennial lifestyle+travel rubric. Recommended for quality.")
    parser.add_argument("--region", default=None,
                        help="Override the daily market rotation with a single regionCode (e.g. GB, US, NZ)")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else date.today()
    if args.region:
        region_code = args.region.upper()
        market = dict(REGIONS).get(region_code, region_code)
    else:
        region_code, market = region_for(target_date)
    mode = "DRY RUN preview" if args.dry_run else "Live run"
    scoring = "ON (quality-filtered)" if args.score else "OFF (raw, review manually)"
    print(f"=== {mode} for {target_date.isoformat()} | market={market} ({region_code}) | "
          f"subs {MIN_SUBS:,}-{MAX_SUBS:,} | scoring {scoring} ===\n")

    total_new = 0
    attempted = []
    for niche in niches_for(target_date):
        attempted.append(niche)
        try:
            added = yda.run(
                niche=niche,
                market=market,
                region=region_code,
                min_followers=MIN_SUBS,
                max_followers=MAX_SUBS,
                count=COUNT_PER_NICHE,
                exclude_file=None,
                no_score=not args.score,
                dry_run=args.dry_run,
            )
        except Exception as e:
            # One bad niche (transient API error, quota, etc.) must not abort
            # the whole run — log, skip it, and let the remaining niches and the
            # final export still happen so the day's leads aren't lost.
            print(f"\n!!! niche '{niche}' failed: {type(e).__name__}: {e} — skipping and continuing\n")
            continue
        total_new += added
        print(f"\n--- niche '{niche}' contributed {added} new — running total {total_new} ---\n")
        if total_new >= TARGET_NEW_LEADS:
            break

    print(f"=== Done. {total_new} new leads in {market} across niches: {attempted} ===")
    if total_new < TARGET_NEW_LEADS:
        print(f"(Under the {TARGET_NEW_LEADS}/day target even after {len(attempted)} niches in {market} — "
              f"tomorrow's rotation hits a different market. Widen NICHES or MAX_SUBS if this persists.)")

    if not args.dry_run:
        print()
        export_prospects_json.export()


if __name__ == "__main__":
    main()
