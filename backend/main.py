import datetime as dt
import json
import random
import sys

from . import county_permits, sources
from .config import CATEGORIES, MAX_PERMIT_CANDIDATES, OUTPUT_PATH
from .rank import build_ranking


def _permit_entries(permits: list[dict], kind: str) -> list[dict]:
    matches = [p for p in permits if p["kind"] == kind]
    if len(matches) > MAX_PERMIT_CANDIDATES:
        matches = random.sample(matches, MAX_PERMIT_CANDIDATES)
    return [
        {
            "name": p["name"],
            "neighborhood": p.get("city") or "",
            "blurb": "",
            "month": None,
            "source": "county_permit",
            "source_url": None,
            "kind": kind,
        }
        for p in matches
    ]


def run() -> None:
    blog_entries = sources.scrape_all()
    permits = county_permits.fetch_active_permits()
    permit_lookup = county_permits.build_lookup(permits)

    if not blog_entries and not permits:
        print("No entries scraped from any source; aborting.", file=sys.stderr)
        sys.exit(1)

    categories_out = {}
    for category, cfg in CATEGORIES.items():
        raw_entries = [e for e in blog_entries if e["kind"] == cfg["kind"]]
        if cfg["mode"] == "top_rated":
            # no reliable "newly opened" signal for this kind -- use the
            # licensed-business inventory as the candidate pool instead
            raw_entries = raw_entries + _permit_entries(permits, cfg["kind"])
        categories_out[category] = build_ranking(category, raw_entries, permit_lookup)

    output = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "categories": {
            key: {
                "label": cfg["label"],
                "title": cfg["title"],
                "methodology": cfg["methodology"],
                "restaurants": categories_out[key],
            }
            for key, cfg in CATEGORIES.items()
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    for key, cfg in CATEGORIES.items():
        print(f"{cfg['label']}: {len(categories_out[key])} entries")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    run()
