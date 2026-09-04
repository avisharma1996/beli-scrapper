import datetime as dt
import json
from pathlib import Path

from .config import YELP_CACHE_TTL_DAYS

CACHE_PATH = Path(__file__).resolve().parent / "yelp_cache.json"

# Sentinel distinguishing "no fresh entry, needs a live fetch" from a cached
# None (a business Yelp genuinely has no match for).
MISSING = object()


def load() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def get(cache: dict, key: str):
    entry = cache.get(key)
    if entry is None:
        return MISSING
    try:
        fetched_at = dt.datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, ValueError):
        return MISSING
    if dt.datetime.now(dt.timezone.utc) - fetched_at > dt.timedelta(days=YELP_CACHE_TTL_DAYS):
        return MISSING
    return entry["yelp"]


def set(cache: dict, key: str, yelp: dict | None) -> None:
    cache[key] = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "yelp": yelp}
