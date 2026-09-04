import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

YELP_API_KEY = os.environ.get("YELP_API_KEY", "")
GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
USER_AGENT = "Mozilla/5.0 (compatible; sd-restaurant-rankings/1.0)"

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT_DIR / "docs" / "data.json"

CITY = "San Diego, CA"

DISPLAY_N = 20  # how many the frontend shows at once per section
# Ranked list length written to JSON -- deeper than DISPLAY_N so the frontend
# has a bench of already-ranked runners-up to backfill from as the viewer
# checks items off as "tried", without needing a fresh scrape.
OUTPUT_N = 40

NEW_WINDOW_DAYS = 180  # "new" restaurants must have opened within this window

# The county's active-restaurant permit pool alone runs ~3,800+ candidates --
# enriching all of them via Yelp/Google every run isn't practical. Cap how
# many get sampled per "top_rated" kind each run (random sample, not a fixed
# slice, so coverage varies run to run rather than always evaluating the
# same subset).
MAX_PERMIT_CANDIDATES = 500

# Keyword classification for county permit records, which don't carry
# cuisine/type info -- only a coarse facility business_type. Matched as
# whole words against the name (not substrings -- "cafe" must not match
# inside "cafeteria").
KIND_KEYWORDS = {
    "coffee": (
        "coffee", "cafe", "café", "espresso", "roaster", "roasters", "roastery",
    ),
    "bakery": (
        "bakery", "bakehouse", "patisserie", "bagel", "bagels", "bread",
        "boulangerie", "pastry", "bakeshop",
    ),
}

# Licensed but not actually open to the public -- excluded from every
# category regardless of kind classification.
NON_PUBLIC_KEYWORDS = (
    "employee cafeteria", "employee dining", "staff cafeteria", "staff dining",
    "commissary", "central kitchen", "concession", "convention center",
    "mezzanine", "suite level",
)

# "new" mode: candidates must come from genuine new-opening evidence
#   (editorial coverage), hard-filtered to NEW_WINDOW_DAYS; scored on
#   buzz + recency + ratings.
# "top_rated" mode: no reliable new-opening data exists for this kind of
#   business, so candidates come from the county's licensed-facility list
#   and are scored purely on rating + review volume, not "newness".
CATEGORIES = {
    "new_restaurants": {
        "label": "New Restaurants",
        "title": "New Restaurants (opened in the last 6 months)",
        "methodology": "Ranked by local food-press buzz, opening recency, and ratings. "
        "Only includes places with a confirmed opening date within the last 6 months.",
        "yelp_category": "restaurants",
        "mode": "new",
        "kind": "restaurant",
    },
    "top_restaurants": {
        "label": "Top Restaurants",
        "title": "Top-Rated Restaurants",
        "methodology": "Ranked by Yelp/Google rating and review volume.",
        "yelp_category": "restaurants",
        "mode": "top_rated",
        "kind": "restaurant",
    },
    "coffee": {
        "label": "Coffee Shops",
        "title": "Top-Rated Coffee Shops",
        "methodology": "Ranked by Yelp/Google rating and review volume. (No reliable "
        "\"newly opened\" data source exists for this category -- see README.)",
        "yelp_category": "coffee",
        "mode": "top_rated",
        "kind": "coffee",
    },
    "bakeries": {
        "label": "Bakeries",
        "title": "Top-Rated Bakeries",
        "methodology": "Ranked by Yelp/Google rating and review volume. (No reliable "
        "\"newly opened\" data source exists for this category -- see README.)",
        "yelp_category": "bakeries",
        "mode": "top_rated",
        "kind": "bakery",
    },
}
