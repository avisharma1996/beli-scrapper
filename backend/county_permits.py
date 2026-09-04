import re

import requests

from .config import KIND_KEYWORDS, NON_PUBLIC_KEYWORDS, USER_AGENT

SOCRATA_URL = "https://data.sandiegocounty.gov/resource/c5ez-ufrd.json"

_BUSINESS_TYPES = ("Restaurant Food Facility", "Low Risk Food Facility", "Single Operating Site")


def _word_match(low_name: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", low_name) is not None


def classify_kind(name: str) -> str:
    low = name.lower()
    for kind, keywords in KIND_KEYWORDS.items():
        if any(_word_match(low, kw) for kw in keywords):
            return kind
    return "restaurant"


def is_public_facing(name: str) -> bool:
    low = name.lower()
    return not any(_word_match(low, phrase) for phrase in NON_PUBLIC_KEYWORDS)


def fetch_active_permits() -> list[dict]:
    """Fetch currently active/issued food facility permits, classified by kind.

    This is an inventory of licensed businesses, not a "newly opened" signal
    -- the dataset has no populated open/issue date (record_open_date and
    record_issue_date are empty for every row; last_updated is just a bulk
    refresh timestamp, not per-business). Used as a "top rated" candidate
    pool and as a "verified licensed" trust bonus.
    """
    type_clause = " OR ".join(f"business_type = '{bt}'" for bt in _BUSINESS_TYPES)
    params = {
        "$where": f"({type_clause}) AND active_permit = 'A'",
        "$limit": 5000,
    }
    try:
        resp = requests.get(
            SOCRATA_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=30
        )
        resp.raise_for_status()
        records = resp.json()
    except (requests.RequestException, ValueError):
        return []

    seen = set()
    permits = []
    for rec in records:
        name = rec.get("record_name")
        if not name or not is_public_facing(name):
            continue
        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        permits.append(
            {
                "name": name,
                "kind": classify_kind(name),
                "city": rec.get("city"),
                "address": rec.get("address"),
                "status": rec.get("permit_status"),
            }
        )
    return permits


def build_lookup(permits: list[dict]) -> dict[str, dict]:
    from .rank import normalize_name

    lookup: dict[str, dict] = {}
    for p in permits:
        key = normalize_name(p["name"])
        if key and key not in lookup:
            lookup[key] = p
    return lookup
