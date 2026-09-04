import datetime as dt
import math
import re
from concurrent.futures import ThreadPoolExecutor

from . import google_client, yelp_client
from .config import CATEGORIES, NEW_WINDOW_DAYS, OUTPUT_N

ENRICHMENT_WORKERS = 10

# Google Places is billed per call once past its free monthly quota, and some
# category pools (esp. coffee/bakeries, sourced from the full county permit
# inventory) can run into the hundreds of candidates. So Google is only
# spent on a shortlist -- the top N by a Yelp-only preliminary score -- not
# every candidate. Yelp itself is free, so it enriches everyone.
GOOGLE_SHORTLIST_N = 20

_PUNCT_RE = re.compile(r"[^a-z0-9 ]")
_THE_RE = re.compile(r"\bthe\b")
_WS_RE = re.compile(r"\s+")
_PAREN_RE = re.compile(r"\(.*?\)")

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

# "new" mode (restaurants): candidates are genuine new-opening evidence, so
# buzz/recency carry real weight. "top_rated" mode (coffee, bakeries): there's
# no reliable newness signal for these, so that budget shifts entirely onto
# rating/volume and permit becomes a small "verified licensed" trust bonus.
WEIGHTS = {
    "new": {
        "buzz": 20, "recency": 20,
        "yelp_rating": 15, "yelp_volume": 15,
        "google_rating": 10, "google_volume": 10,
        "permit": 10,
    },
    "top_rated": {
        "buzz": 0, "recency": 0,
        "yelp_rating": 30, "yelp_volume": 30,
        "google_rating": 15, "google_volume": 15,
        "permit": 10,
    },
}


def normalize_name(name: str) -> str:
    n = name.lower()
    n = _PAREN_RE.sub("", n)
    n = _PUNCT_RE.sub(" ", n)
    n = _THE_RE.sub(" ", n)
    return _WS_RE.sub(" ", n).strip()


def _parse_month_label(label: str | None) -> dt.date | None:
    if not label:
        return None
    low = label.lower()
    year_match = re.search(r"(20\d{2})", low)
    year = int(year_match.group(1)) if year_match else dt.date.today().year
    for name, num in MONTH_NAMES.items():
        if name in low:
            return dt.date(year, num, 15)
    if "summer" in low:
        return dt.date(year, 7, 15)
    if "winter" in low:
        return dt.date(year, 1, 15)
    if "late" in low:
        return dt.date(year, 11, 15)
    return None


def _recency_score(target: dt.date | None, today: dt.date | None = None) -> float:
    today = today or dt.date.today()
    if target is None:
        return 0.5
    delta_days = abs((target - today).days)
    return max(0.0, 1 - delta_days / 240)


def _within_new_window(target: dt.date | None, today: dt.date | None = None) -> bool:
    """True if target is a real, already-passed date within NEW_WINDOW_DAYS."""
    today = today or dt.date.today()
    if target is None:
        return False
    days_ago = (today - target).days
    return 0 <= days_ago <= NEW_WINDOW_DAYS


def merge_entries(raw_entries: list[dict]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for e in raw_entries:
        key = normalize_name(e["name"])
        if not key:
            continue
        agg = merged.setdefault(
            key,
            {"name": e["name"], "neighborhood": "", "blurbs": [], "months": [], "sources": []},
        )
        if e.get("neighborhood") and not agg["neighborhood"]:
            agg["neighborhood"] = e["neighborhood"]
        if e.get("blurb"):
            agg["blurbs"].append({"source": e["source"], "text": e["blurb"]})
        if e.get("month"):
            agg["months"].append(e["month"])
        agg["sources"].append({"name": e["source"], "url": e.get("source_url")})
    return merged


def _rating_volume(rating: float | None, review_count: int | None, volume_ceiling: int) -> tuple[float, float]:
    rating_component = (rating / 5) if rating is not None else 0.0
    volume_component = min(1.0, math.log1p(review_count or 0) / math.log1p(volume_ceiling))
    return rating_component, volume_component


def _score(mode: str, agg: dict, yelp: dict | None, google: dict | None, permit: dict | None) -> float:
    w = WEIGHTS[mode]

    source_count = len({s["name"] for s in agg["sources"]})
    buzz = min(source_count, 3) / 3

    month_label = agg["months"][0] if agg["months"] else None
    recency = _recency_score(_parse_month_label(month_label))

    yelp_rating, yelp_volume = _rating_volume(
        yelp.get("rating") if yelp else None, yelp.get("review_count") if yelp else None, 200
    )
    google_rating, google_volume = _rating_volume(
        google.get("rating") if google else None, google.get("review_count") if google else None, 200
    )

    permit_component = 1.0 if permit else 0.0

    score = (
        w["buzz"] * buzz
        + w["recency"] * recency
        + w["yelp_rating"] * yelp_rating
        + w["yelp_volume"] * yelp_volume
        + w["google_rating"] * google_rating
        + w["google_volume"] * google_volume
        + w["permit"] * permit_component
    )
    return round(score, 2)


def _fetch_yelp(item: tuple[str, dict], yelp_category: str) -> tuple[str, dict, dict | None]:
    key, agg = item
    yelp = yelp_client.search_business(agg["name"], yelp_category=yelp_category)
    return key, agg, yelp


def _fetch_google(entry: dict) -> dict | None:
    return google_client.search_place(entry["name"])


def build_ranking(category: str, raw_entries: list[dict], permit_lookup: dict[str, dict]) -> list[dict]:
    merged = merge_entries(raw_entries)
    yelp_category = CATEGORIES[category]["yelp_category"]
    mode = CATEGORIES[category]["mode"]

    if mode == "new":
        # hard cutoff -- only businesses with a confirmed opening date inside
        # the window count as "new"; anything without a parseable date (or
        # too old / not yet opened) is dropped rather than soft-scored
        merged = {
            k: v
            for k, v in merged.items()
            if _within_new_window(_parse_month_label(v["months"][0] if v["months"] else None))
        }

    with ThreadPoolExecutor(max_workers=ENRICHMENT_WORKERS) as pool:
        yelp_results = pool.map(lambda item: _fetch_yelp(item, yelp_category), merged.items())

    entries = []
    for key, agg, yelp in yelp_results:
        permit = permit_lookup.get(key)
        entry = {
            "id": key,
            "name": agg["name"],
            "neighborhood": agg["neighborhood"],
            "blurb": agg["blurbs"][0]["text"] if agg["blurbs"] else "",
            "month": agg["months"][0] if agg["months"] else None,
            "sources": [
                {"name": s["name"], "url": s["url"]}
                for s in {(s["name"], s["url"]): s for s in agg["sources"]}.values()
            ],
            "_agg": agg,
            "yelp": yelp,
            "google": None,
            "permit": permit,
        }
        entry["score"] = _score(mode, agg, yelp, None, permit)
        entries.append(entry)

    # Spend Google calls only on the strongest candidates by Yelp-only score
    entries.sort(key=lambda e: e["score"], reverse=True)
    shortlist = entries[:GOOGLE_SHORTLIST_N]
    with ThreadPoolExecutor(max_workers=ENRICHMENT_WORKERS) as pool:
        google_results = list(pool.map(_fetch_google, shortlist))
    for entry, google in zip(shortlist, google_results):
        entry["google"] = google
        entry["score"] = _score(mode, entry["_agg"], entry["yelp"], google, entry["permit"])

    for entry in entries:
        del entry["_agg"]

    entries.sort(key=lambda e: e["score"], reverse=True)
    top = entries[:OUTPUT_N]
    for i, entry in enumerate(top, start=1):
        entry["rank"] = i
    return top
