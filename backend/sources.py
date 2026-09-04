import html
import re

import requests
from bs4 import BeautifulSoup

from .config import USER_AGENT
from .county_permits import classify_kind

THERESANDIEGO_URL = "https://theresandiego.com/new-restaurants-opening-in-san-diego-in-2026/"
SANDIEGOVILLE_URL = "https://www.sandiegoville.com/2025/12/the-ultimate-guide-to-san-diegos-80.html"

_DASH_SPLIT = re.compile(r"\s[–—-]\s")


def _fetch_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.content, "html.parser")


def scrape_theresandiego() -> list[dict]:
    """Parse the monthly 'restaurant openings' roundup on theresandiego.com."""
    soup = _fetch_soup(THERESANDIEGO_URL)
    start = soup.find(id="h-2026-restaurant-openings-by-month")
    if start is None:
        return []

    results = []
    current_month = None
    for el in start.find_all_next(["h2", "h3", "p"]):
        if el.name == "h2":
            break
        if el.name == "h3":
            current_month = el.get_text(strip=True)
            continue
        classes = el.get("class") or []
        if el.name == "p" and "wp-block-paragraph" in classes:
            strong = el.find("strong")
            if not strong:
                continue
            strong_text = strong.get_text(" ", strip=True)
            parts = _DASH_SPLIT.split(strong_text, maxsplit=1)
            name = parts[0].strip()
            neighborhood = parts[1].strip() if len(parts) > 1 else ""
            if not name:
                continue
            after_parts = []
            for sib in strong.next_siblings:
                if isinstance(sib, str):
                    after_parts.append(sib)
                else:
                    after_parts.append(sib.get_text(" ", strip=True))
            blurb = " ".join(p for p in after_parts if p).strip()
            blurb = blurb.lstrip(" -–—").strip()
            if not neighborhood:
                # some entries put the neighborhood outside <strong>, as a
                # short leading "Neighborhood – " fragment before the blurb
                dash_parts = _DASH_SPLIT.split(blurb, maxsplit=1)
                if len(dash_parts) == 2 and len(dash_parts[0]) < 40:
                    neighborhood = dash_parts[0].strip()
                    blurb = dash_parts[1].strip()
            link = strong.find("a")
            results.append(
                {
                    "name": name,
                    "neighborhood": neighborhood,
                    "blurb": blurb[:400],
                    "month": current_month,
                    "source": "theresandiego",
                    "source_url": link["href"] if link and link.get("href") else THERESANDIEGO_URL,
                    "kind": classify_kind(name),
                }
            )
    return results


_SDVILLE_PATTERN = re.compile(
    r'<b>\s*<a href="([^"]+)"[^>]*>([^<]+)</a>\s*(?:\(([^)]*)\))?\s*</b>\s*-\s*',
    re.S,
)


def scrape_sandiegoville() -> list[dict]:
    """Parse the bolded-link restaurant entries in sandiegoville.com's openings guide."""
    soup = _fetch_soup(SANDIEGOVILLE_URL)
    body = soup.find("div", class_="post-body")
    if body is None:
        return []

    fragment = str(body)
    matches = list(_SDVILLE_PATTERN.finditer(fragment))

    results = []
    for i, m in enumerate(matches):
        name = html.unescape(m.group(2)).strip()
        if not name:
            continue
        neighborhood = html.unescape(m.group(3) or "").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else start + 600
        desc_text = BeautifulSoup(fragment[start:end], "html.parser").get_text(" ", strip=True)
        results.append(
            {
                "name": name,
                "neighborhood": neighborhood,
                "blurb": desc_text[:400],
                "month": None,
                "source": "sandiegoville",
                "source_url": m.group(1),
                "kind": classify_kind(name),
            }
        )
    return results


def scrape_all() -> list[dict]:
    entries = []
    for scraper in (scrape_theresandiego, scrape_sandiegoville):
        try:
            entries.extend(scraper())
        except requests.RequestException:
            continue
    return entries
