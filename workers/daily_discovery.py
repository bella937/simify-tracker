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

NICHES = [
    "travel", "digital nomad", "backpacking", "solo travel",
    "budget travel", "family travel", "van life", "adventure travel",
]

TARGET_NEW_LEADS = 50
MAX_NICHES_PER_RUN = 4  # safety cap on YouTube API quota use per day
COUNT_PER_NICHE = 40


def niches_for(target_date: date) -> list[str]:
    start = target_date.toordinal() % len(NICHES)
    return [NICHES[(start + offset) % len(NICHES)] for offset in range(MAX_NICHES_PER_RUN)]


def main():
    parser = argparse.ArgumentParser(description="Daily nano/micro YouTube lead discovery")
    parser.add_argument("--date", default=None, help="ISO date to compute the niche rotation for (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be added without writing to the spreadsheet")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else date.today()
    mode = "DRY RUN preview" if args.dry_run else "Live run"
    print(f"=== {mode} for {target_date.isoformat()} ===\n")

    total_new = 0
    attempted = []
    for niche in niches_for(target_date):
        attempted.append(niche)
        try:
            added = yda.run(
                niche=niche,
                market="Australia",
                region="AU",
                min_followers=1000,
                max_followers=100000,
                count=COUNT_PER_NICHE,
                exclude_file=None,
                no_score=True,
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

    print(f"=== Done. {total_new} new leads across niches: {attempted} ===")
    if total_new < TARGET_NEW_LEADS:
        print(f"(Under the {TARGET_NEW_LEADS}/day target even after {len(attempted)} niches — "
              f"the AU nano/micro travel pool may be thinning out. Consider widening region or follower range.)")

    if not args.dry_run:
        print()
        export_prospects_json.export()


if __name__ == "__main__":
    main()
