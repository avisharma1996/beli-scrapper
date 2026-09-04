import requests

from .config import CITY, USER_AGENT, YELP_API_KEY

SEARCH_URL = "https://api.yelp.com/v3/businesses/search"


def search_business(name: str, yelp_category: str | None = None) -> dict | None:
    """Best-effort Yelp match for a business name in San Diego."""
    if not YELP_API_KEY:
        return None
    params = {"term": name, "location": CITY, "limit": 1}
    if yelp_category:
        params["categories"] = yelp_category
    try:
        resp = requests.get(
            SEARCH_URL,
            headers={"Authorization": f"Bearer {YELP_API_KEY}", "User-Agent": USER_AGENT},
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        businesses = resp.json().get("businesses", [])
    except (requests.RequestException, ValueError):
        return None

    if not businesses:
        return None
    biz = businesses[0]
    return {
        "rating": biz.get("rating"),
        "review_count": biz.get("review_count"),
        "price": biz.get("price"),
        "url": biz.get("url", "").split("?")[0] if biz.get("url") else None,
        "image_url": biz.get("image_url"),
        "categories": [c["title"] for c in biz.get("categories", [])],
        "is_closed": biz.get("is_closed", False),
    }
