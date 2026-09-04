import datetime as dt
import json
import sys

from . import county_permits, sources
from .config import OUTPUT_PATH
from .rank import build_ranking


def run() -> None:
    raw_entries = sources.scrape_all()
    if not raw_entries:
        print("No restaurant entries scraped from any source; aborting.", file=sys.stderr)
        sys.exit(1)

    permit_lookup = county_permits.fetch_recent_restaurant_permits()
    ranking = build_ranking(raw_entries, permit_lookup)

    output = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "restaurant_count": len(ranking),
        "restaurants": ranking,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote {len(ranking)} restaurants to {OUTPUT_PATH}")


if __name__ == "__main__":
    run()
