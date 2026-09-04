# San Diego Food & Drink Rankings

Ranks the top 50 in three categories -- **Restaurants** (new/up-and-coming),
**Coffee Shops** (top-rated), and **Bakeries** (top-rated) -- in San Diego.
A static frontend (`docs/`) renders the result and is meant to be served via
GitHub Pages.

## Why two different ranking methodologies

**Restaurants** use a genuine "new opening" signal: local food-press roundups
(theresandiego.com, sandiegoville.com) that report specific new restaurants
by name and (usually) an opening month. That's real evidence of newness, so
those rankings are scored on buzz + recency + ratings.

**Coffee shops and bakeries have no equivalent data source.** There's no
curated "new coffee shop/bakery" roundup for San Diego, and San Diego
County's [Food Facility Permits dataset](https://data.sandiegocounty.gov/Health/Food-Facility-Permits/c5ez-ufrd)
turned out not to help either: it declares `record_open_date` /
`record_issue_date` columns, but they're empty for every row, and
`last_updated` is just a bulk data-refresh timestamp shared by nearly every
record -- not a per-business event. (An earlier version of this project used
that field as a "new" proxy and it wrongly surfaced decades-old places like
Pablo's Coffee and Dudley's Bakery as "new." That was a real bug, not a
judgment call -- fixed by dropping newness claims for these categories
entirely.)

So coffee shops and bakeries are honestly framed as **"Top-Rated"**: the
candidate pool is the county's active-license inventory (filtered by
name-keyword classification -- see `permit_keywords` in
[backend/config.py](backend/config.py)), ranked purely by Yelp/Google rating
and review volume, with an active license as a small trust bonus. No
newness claim is made for these two categories.

## How ranking works

Each entry is scored 0-100 from a category-appropriate mix of:
- **Buzz** (restaurants only) -- how many independent source lists mention it
- **Recency** (restaurants only) -- how close its reported opening month is to today
- **Yelp rating** and **Yelp review volume** (log-scaled review count)
- **Google rating** and **Google review volume** -- only populated if you set
  `GOOGLE_PLACES_API_KEY`; silently contributes 0 otherwise. Google Places
  bills per call past a small free monthly quota (~1,000 calls with the
  rating field), so it's only spent on the top `GOOGLE_SHORTLIST_N` (20)
  candidates per category by Yelp-only score, not the full candidate pool --
  see `GOOGLE_SHORTLIST_N` in [backend/rank.py](backend/rank.py). At the
  default weekly schedule that's ~260 calls/month across all three
  categories, comfortably inside the free tier.
- **Active license** -- small bonus if it has a currently active SD County permit

See the `WEIGHTS` dict in [backend/rank.py](backend/rank.py) for exact numbers.

Only places rated 4.0+ on every platform that has rated them (and rated by
*at least one* platform) make the list -- see `MIN_RATING` in
[backend/config.py](backend/config.py). Chain locations (the county permit
inventory gives each one its own row, store number and all) are capped at
one per chain, keeping the best-scoring location -- see `chain_key()` in
[backend/rank.py](backend/rank.py).

Yelp's free tier is a modest **monthly** call budget, not daily, and easy to
exceed since a full run enriches every permit candidate. Results are cached
to `backend/yelp_cache.json` (committed by the workflow, like
`docs/data.json`) and reused for `YELP_CACHE_TTL_DAYS` (30) before
re-querying -- see [backend/yelp_cache.py](backend/yelp_cache.py). A failed
call (rate limited, network error) is never cached as "no match", so it
retries next run instead of getting stuck.

## Local setup

```
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in a [Yelp Fusion API key](https://fam.yelp.com/developers).
`GOOGLE_PLACES_API_KEY` is optional (requires a billing-enabled Google Cloud
project with the Places API enabled) -- leave it unset to skip Google enrichment.

Run the pipeline:

```
.venv\Scripts\python -m backend.main
```

This writes `docs/data.json`. Open `docs/index.html` in a browser (or serve
the `docs/` folder) to view the rankings locally.

## GitHub setup (once you push this repo)

1. **Add secrets**: repo Settings → Secrets and variables → Actions → New
   repository secret → `YELP_API_KEY` (required), `GOOGLE_PLACES_API_KEY`
   (optional).
2. **Enable Pages**: repo Settings → Pages → Source: "Deploy from a branch" →
   Branch: `main`, folder: `/docs`.
3. The `Update restaurant rankings` workflow (`.github/workflows/update.yml`)
   runs weekly (Mondays) and on manual dispatch, regenerating `docs/data.json`
   and committing it -- which Pages then redeploys automatically.

## Notes / known limitations

- Both blog sources are unstructured editorial pages (not APIs), so the
  scraper uses HTML-structure heuristics that may need small tweaks if the
  sites change layout -- check `backend/sources.py` first if restaurant
  entries stop showing up.
- The county's business-type field doesn't track cuisine, so coffee/bakery
  classification is a name-keyword heuristic (`backend/county_permits.py`)
  and will misclassify or miss some businesses.
- No Reddit/forum "chatter" signal is included -- Reddit blocks unauthenticated
  API access, and setting up an OAuth app was declined for this project.
