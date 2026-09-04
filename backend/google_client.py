import time

import requests

from .config import CITY, GOOGLE_PLACES_API_KEY

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = "places.rating,places.userRatingCount,places.googleMapsUri,places.businessStatus"


def search_place(name: str) -> dict | None:
    """Best-effort Google Places match. No-op until GOOGLE_PLACES_API_KEY is set."""
    if not GOOGLE_PLACES_API_KEY:
        return None
    try:
        resp = requests.post(
            SEARCH_URL,
            json={"textQuery": f"{name}, {CITY}"},
            headers={
                "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                "X-Goog-FieldMask": FIELD_MASK,
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        places = resp.json().get("places", [])
    except (requests.RequestException, ValueError):
        return None
    finally:
        time.sleep(0.1)

    if not places:
        return None
    place = places[0]
    return {
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
        "url": place.get("googleMapsUri"),
    }
