import datetime as dt
import math
import re

from . import yelp_client
from .config import TOP_N

_PUNCT_RE = re.compile(r"[^a-z0-9 ]")
_THE_RE = re.compile(r"\bthe\b")
_WS_RE = re.compile(r"\s+")
_PAREN_RE = re.compile(r"\(.*?\)")

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

WEIGHT_BUZZ = 40
WEIGHT_RECENCY = 30
WEIGHT_YELP = 20
WEIGHT_PERMIT = 10


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


def _recency_score(label: str | None, today: dt.date | None = None) -> float:
    today = today or dt.date.today()
    parsed = _parse_month_label(label)
    if parsed is None:
        return 0.5
    delta_days = abs((parsed - today).days)
    return max(0.0, 1 - delta_days / 240)


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


def _score(agg: dict, yelp: dict | None, permit: dict | None) -> float:
    source_count = len({s["name"] for s in agg["sources"]})
    buzz = min(source_count, 3) / 3

    month_label = agg["months"][0] if agg["months"] else None
    recency = _recency_score(month_label)

    yelp_component = 0.0
    if yelp and yelp.get("rating") is not None:
        review_count = yelp.get("review_count") or 0
        confidence = min(1.0, math.log1p(review_count) / math.log1p(30))
        yelp_component = (yelp["rating"] / 5) * confidence

    permit_component = 1.0 if permit else 0.0

    score = (
        WEIGHT_BUZZ * buzz
        + WEIGHT_RECENCY * recency
        + WEIGHT_YELP * yelp_component
        + WEIGHT_PERMIT * permit_component
    )
    return round(score, 2)


def build_ranking(raw_entries: list[dict], permit_lookup: dict[str, dict]) -> list[dict]:
    merged = merge_entries(raw_entries)

    scored = []
    for key, agg in merged.items():
        yelp = yelp_client.search_business(agg["name"])
        permit = permit_lookup.get(key)
        entry = {
            "name": agg["name"],
            "neighborhood": agg["neighborhood"],
            "blurb": agg["blurbs"][0]["text"] if agg["blurbs"] else "",
            "month": agg["months"][0] if agg["months"] else None,
            "sources": [
                {"name": s["name"], "url": s["url"]}
                for s in {(s["name"], s["url"]): s for s in agg["sources"]}.values()
            ],
            "yelp": yelp,
            "permit": permit,
            "score": _score(agg, yelp, permit),
        }
        scored.append(entry)

    scored.sort(key=lambda e: e["score"], reverse=True)
    top = scored[:TOP_N]
    for i, entry in enumerate(top, start=1):
        entry["rank"] = i
    return top
