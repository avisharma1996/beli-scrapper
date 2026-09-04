import datetime as dt
import math
import random
import re
from concurrent.futures import ThreadPoolExecutor

from . import google_client, yelp_cache, yelp_client
from .config import (
    CATEGORIES,
    GOOGLE_SHORTLIST_FALLBACK_N,
    MIN_RATING,
    NEW_WINDOW_DAYS,
    OUTPUT_N,
    YELP_API_KEY,
    YELP_FAILURE_FALLBACK_THRESHOLD,
)

ENRICHMENT_WORKERS = 10

# Google Places is billed per call once past its free monthly quota, and some
# category pools (esp. coffee/bakeries, sourced from the full county permit
# inventory) can run into the hundreds of candidates. So Google is only
# spent on a shortlist -- the top N by a Yelp-only preliminary score -- not
# every candidate. Yelp has its own modest monthly call budget too (not
# unlimited), so it's enriched for everyone but through yelp_cache -- see
# _fetch_all_yelp below -- rather than re-queried fresh every run.
GOOGLE_SHORTLIST_N = 20

_PUNCT_RE = re.compile(r"[^a-z0-9 ]")
_THE_RE = re.compile(r"\bthe\b")
_WS_RE = re.compile(r"\s+")
_PAREN_RE = re.compile(r"\(.*?\)")
_TRAILING_DIGIT_TOKEN_RE = re.compile(r"\s+\S*\d\S*$")
_CORP_SUFFIX_WORDS = {"llc", "inc", "co", "company", "corp", "corporation"}

# Well-known multi-location chains -- if a (normalized) name contains one of
# these as a whole word/phrase, it's used as the chain key directly instead
# of the generic trailing-token stripping in chain_key(). Permit records
# store a chain's brand in wildly inconsistent formats across locations
# (bare "STARBUCKS", "STARBUCKS COFFEE COMPANY", "HILTON ... - STARBUCKS",
# "PALOMAR ESCONDIDO STARBUCKS LLC", airport-terminal kiosks, ...) that no
# generic suffix-stripping heuristic catches consistently. Not exhaustive --
# a chain missing from this list still gets deduped by the generic
# stripping below, just not across such wildly different naming formats.
# Apostrophes are already stripped by normalize_name, so e.g. "mcdonald's"
# is written here as "mcdonald s".
KNOWN_CHAINS = (
    "starbucks", "peets coffee", "dunkin", "dutch bros", "philz coffee",
    "coffee bean and tea leaf", "jamba juice", "jamba", "panera bread",
    "einstein bros", "noah s bagels", "corner bakery", "paris baguette",
    "krispy kreme", "baskin robbins", "cold stone creamery",
    "subway", "mcdonald s", "jack in the box", "chipotle", "panda express",
    "jersey mike s", "jimmy john s", "wendy s", "taco bell", "kfc",
    "popeyes", "chick fil a", "in n out", "del taco", "carl s jr",
    "burger king", "pizza hut", "domino s", "little caesars", "wingstop",
)
_KNOWN_CHAIN_RES = [(brand, re.compile(rf"\b{re.escape(brand)}\b")) for brand in KNOWN_CHAINS]

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

# "new" mode (restaurants): candidates are genuine new-opening evidence, so
# buzz/recency carry real weight. "top_rated" mode (coffee, bakeries): there's
# no reliable newness signal for these, so that budget shifts entirely onto
# rating/volume and permit becomes a small "verified licensed" trust bonus.
# Rating + review-volume dominate both modes -- a high-volume-but-mediocre
# place shouldn't be able to out-buzz or out-permit its way past genuinely
# well-rated ones. MIN_RATING below is what actually keeps low-rated places
# (e.g. 2.3 stars) off the list -- reweighting alone can't guarantee that
# since a high review count can still offset a middling rating in a linear
# score.
WEIGHTS = {
    "new": {
        "buzz": 15, "recency": 15,
        "yelp_rating": 20, "yelp_volume": 20,
        "google_rating": 10, "google_volume": 10,
        "permit": 10,
    },
    "top_rated": {
        "buzz": 0, "recency": 0,
        "yelp_rating": 35, "yelp_volume": 35,
        "google_rating": 12, "google_volume": 12,
        "permit": 6,
    },
}


def normalize_name(name: str) -> str:
    n = name.lower()
    n = _PAREN_RE.sub("", n)
    n = _PUNCT_RE.sub(" ", n)
    n = _THE_RE.sub(" ", n)
    return _WS_RE.sub(" ", n).strip()


def chain_key(name: str) -> str:
    """Groups different locations of the same chain together.

    County permit records give each physical location its own row, with a
    store/unit code baked into the name in whatever form that chain uses
    ("STARBUCKS COFFEE #6783", "STARBUCKS COFFEE CO #19826",
    "STARBUCKS COFFEE CO TERMINAL 2W-2038", "STARBUCKS COFFEE COMPANY", ...)
    -- so without collapsing these, a single chain can fill most of a
    category with near-duplicate entries. Repeatedly strips trailing
    corporate-suffix words and trailing tokens that contain a digit (store
    numbers, unit/terminal codes) until neither applies.
    """
    n = normalize_name(name)
    for brand, pattern in _KNOWN_CHAIN_RES:
        if pattern.search(n):
            return brand
    while True:
        next_n = _TRAILING_DIGIT_TOKEN_RE.sub("", n)
        words = next_n.split()
        if words and words[-1] in _CORP_SUFFIX_WORDS:
            words.pop()
        next_n = " ".join(words)
        if next_n == n:
            return n
        n = next_n


def _passes_rating_floor(yelp: dict | None, google: dict | None, require_rating: bool = False) -> bool:
    """False if any present rating (Yelp/Google) is below MIN_RATING.

    With require_rating=True, also false if neither platform rated it at
    all -- otherwise a place nobody has ever rated (no bad rating on record,
    but no good one either) could still backfill the list once genuinely
    well-rated candidates run out.
    """
    ratings = [r for r in (yelp and yelp.get("rating"), google and google.get("rating")) if r is not None]
    if not ratings:
        return not require_rating
    return all(r >= MIN_RATING for r in ratings)


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


def _fetch_yelp(item: tuple[str, dict], yelp_category: str) -> tuple[str, dict, dict | None, bool]:
    """Returns (key, agg, yelp, ok). ok=False means the call itself failed
    (network error, rate limiting) -- the caller must not cache that as
    "no match"."""
    key, agg = item
    try:
        yelp = yelp_client.search_business(agg["name"], yelp_category=yelp_category)
        return key, agg, yelp, True
    except yelp_client.YelpUnavailable:
        return key, agg, None, False


def _fetch_all_yelp(merged: dict[str, dict], yelp_category: str) -> tuple[list[tuple[str, dict, dict | None]], float]:
    """Yelp-enriches every merged candidate, reusing cached results (see
    yelp_cache) instead of re-querying businesses already looked up within
    YELP_CACHE_TTL_DAYS -- Yelp's free tier is a modest monthly call budget,
    not unlimited, and a full run can have thousands of candidates.

    Also returns the fraction of *fresh* lookups (cache misses) that failed
    outright (rate limited, network error) rather than genuinely finding no
    match -- callers use this to detect "Yelp is down this run" and widen
    the Google shortlist accordingly (see build_ranking). Cache hits aren't
    counted since they don't reflect Yelp's current availability.
    """
    cache = yelp_cache.load()
    results: list[tuple[str, dict, dict | None]] = []
    to_fetch: list[tuple[str, dict]] = []
    for key, agg in merged.items():
        cached = yelp_cache.get(cache, key)
        if cached is yelp_cache.MISSING:
            to_fetch.append((key, agg))
        else:
            results.append((key, agg, cached))

    failure_rate = 0.0
    if to_fetch:
        with ThreadPoolExecutor(max_workers=ENRICHMENT_WORKERS) as pool:
            fetched = list(pool.map(lambda item: _fetch_yelp(item, yelp_category), to_fetch))
        failures = 0
        for key, agg, yelp, ok in fetched:
            if ok and YELP_API_KEY:
                yelp_cache.set(cache, key, yelp)
            if not ok:
                failures += 1
            results.append((key, agg, yelp))
        failure_rate = failures / len(fetched)
        if YELP_API_KEY:
            yelp_cache.save(cache)

    return results, failure_rate


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

    yelp_results, yelp_failure_rate = _fetch_all_yelp(merged, yelp_category)

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

    # Drop clearly bad places outright -- a high review count can offset a
    # middling rating in the weighted score, which would otherwise let e.g.
    # a 2.3-star location still make a "top rated" list.
    entries = [e for e in entries if _passes_rating_floor(e["yelp"], None)]

    # Cap each chain at its single best-scoring location (see chain_key) --
    # do this before spending Google-enrichment budget so it isn't wasted on
    # near-duplicate chain locations.
    entries.sort(key=lambda e: e["score"], reverse=True)
    seen_chains: set[str] = set()
    deduped = []
    for e in entries:
        ck = chain_key(e["name"])
        if ck in seen_chains:
            continue
        seen_chains.add(ck)
        deduped.append(e)
    entries = deduped

    # Spend Google calls on the strongest candidates by Yelp-only score --
    # unless Yelp itself was largely unavailable this run, in which case
    # that pre-sort is meaningless (every candidate ties at ~the same
    # score), so fall back to a wider, randomized sample instead of an
    # arbitrary fixed-order slice. See GOOGLE_SHORTLIST_FALLBACK_N in
    # config.py for why this stays modest rather than "enrich everyone".
    if yelp_failure_rate >= YELP_FAILURE_FALLBACK_THRESHOLD:
        pool_for_shortlist = entries[:]
        random.shuffle(pool_for_shortlist)
        shortlist = pool_for_shortlist[:GOOGLE_SHORTLIST_FALLBACK_N]
    else:
        shortlist = entries[:GOOGLE_SHORTLIST_N]
    with ThreadPoolExecutor(max_workers=ENRICHMENT_WORKERS) as pool:
        google_results = list(pool.map(_fetch_google, shortlist))
    for entry, google in zip(shortlist, google_results):
        entry["google"] = google
        entry["score"] = _score(mode, entry["_agg"], entry["yelp"], google, entry["permit"])

    # Re-check the floor now that Google data is in, in case a place had no
    # Yelp rating but a bad Google one.
    entries = [e for e in entries if _passes_rating_floor(e["yelp"], e["google"], require_rating=True)]

    for entry in entries:
        del entry["_agg"]

    entries.sort(key=lambda e: e["score"], reverse=True)
    top = entries[:OUTPUT_N]
    for i, entry in enumerate(top, start=1):
        entry["rank"] = i
    return top
