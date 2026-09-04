import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

YELP_API_KEY = os.environ.get("YELP_API_KEY", "")
USER_AGENT = "Mozilla/5.0 (compatible; sd-restaurant-rankings/1.0)"

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT_DIR / "docs" / "data.json"

CITY = "San Diego, CA"
TOP_N = 50
