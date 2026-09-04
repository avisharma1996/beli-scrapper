import datetime as dt

import requests

from .config import USER_AGENT

SOCRATA_URL = "https://data.sandiegocounty.gov/resource/c5ez-ufrd.json"


def fetch_recent_restaurant_permits() -> dict[str, dict]:
    """Fetch this-year's issued restaurant permits, keyed by normalized business name.

    Used as a best-effort confirmation signal ("this place has an active county
    health permit filed this year"), not as a primary data source.
    """
    from .rank import normalize_name

    year = dt.date.today().year
    params = {
        "$where": f"business_type = 'Restaurant Food Facility' AND record_id LIKE 'DEH{year}%'",
        "$limit": 5000,
        "$order": "last_updated DESC",
    }
    try:
        resp = requests.get(
            SOCRATA_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=30
        )
        resp.raise_for_status()
        records = resp.json()
    except (requests.RequestException, ValueError):
        return {}

    lookup: dict[str, dict] = {}
    for rec in records:
        name = rec.get("record_name")
        if not name:
            continue
        key = normalize_name(name)
        if key and key not in lookup:
            lookup[key] = {
                "status": rec.get("permit_status"),
                "city": rec.get("city"),
                "address": rec.get("address"),
                "last_updated": rec.get("last_updated"),
            }
    return lookup
