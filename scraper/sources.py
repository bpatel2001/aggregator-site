"""Fetchers for each job board type. Each fetcher yields plain dicts:

    {"id", "title", "url", "location", "posted_at" (ISO date or None), "posted_approx" (bool)}

Only the Python standard library is used, so the GitHub Action needs no installs.
"""
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = os.environ.get(
    "SCRAPER_USER_AGENT",
    "Mozilla/5.0 (compatible; junior-swe-jobs/1.0; personal job aggregator)",
)
REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "0.4"))  # seconds between calls to one company
TIMEOUT = 30


class FetchError(Exception):
    pass


def _request(url, body=None, retries=2):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = FetchError(f"HTTP {e.code} from {url}")
            if e.code in (400, 401, 403, 404, 410, 422):
                raise last  # not worth retrying
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as e:
            last = FetchError(f"{type(e).__name__}: {e} ({url})")
        time.sleep(2 * (attempt + 1))
    raise last


def _today():
    return dt.datetime.now(dt.timezone.utc).date()


# --- Workday ---------------------------------------------------------------

WORKDAY_URL = re.compile(
    r"https?://(?P<tenant>[\w-]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?(?P<site>[^/?#]+)",
    re.I,
)
# Workday spreads tenants across numbered data centers; companies move between them.
WD_CANDIDATES = ["wd1", "wd5", "wd3", "wd12", "wd10", "wd103", "wd108", "wd115",
                 "wd501", "wd502", "wd503", "wd504", "wd2", "wd101", "wd102"]


def parse_workday_url(url):
    m = WORKDAY_URL.match(url.strip())
    if not m:
        raise FetchError(f"Not a Workday career-site URL: {url}")
    return m.group("tenant"), m.group("wd"), m.group("site")


def workday_api(tenant, wd, site):
    return f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"


def parse_workday_posted(text, today=None):
    """'Posted Today' / 'Posted Yesterday' / 'Posted 3 Days Ago' / 'Posted 30+ Days Ago'."""
    today = today or _today()
    t = (text or "").lower()
    if "today" in t:
        return today.isoformat(), False
    if "yesterday" in t:
        return (today - dt.timedelta(days=1)).isoformat(), False
    m = re.search(r"(\d+)\+?\s*days?", t)
    if m:
        days = int(m.group(1))
        return (today - dt.timedelta(days=days)).isoformat(), "+" in t
    return None, True


def resolve_workday(url, cache):
    """Return a working (tenant, wd, site). Tries other wdN hosts if the given one fails."""
    if url in cache:
        return tuple(cache[url])
    tenant, wd, site = parse_workday_url(url)
    probe = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
    errors = []
    for cand in [wd] + [c for c in WD_CANDIDATES if c != wd]:
        try:
            data = _request(workday_api(tenant, cand, site), probe, retries=0)
            if isinstance(data, dict) and "jobPostings" in data:
                cache[url] = [tenant, cand, site]
                return tenant, cand, site
        except FetchError as e:
            errors.append(str(e))
        time.sleep(REQUEST_DELAY)
    raise FetchError(f"No working Workday host for {url} (first error: {errors[0] if errors else 'n/a'})")


def fetch_workday(url, searches, max_per_search, cache):
    tenant, wd, site = resolve_workday(url, cache)
    api = workday_api(tenant, wd, site)
    base = f"https://{tenant}.{wd}.myworkdayjobs.com/{site}"
    seen = set()
    for q in searches:
        offset, total = 0, None
        while True:
            body = {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": q}
            data = _request(api, body)
            posts = data.get("jobPostings") or []
            if total is None:
                total = data.get("total") or 0
            for p in posts:
                path = p.get("externalPath") or ""
                if not path or path in seen:
                    continue
                seen.add(path)
                posted, approx = parse_workday_posted(p.get("postedOn"))
                yield {
                    "id": f"wd:{tenant}:{site}:{path}",
                    "title": p.get("title", "").strip(),
                    "url": base + path,
                    "location": p.get("locationsText") or "",
                    "posted_at": posted,
                    "posted_approx": approx,
                }
            offset += 20
            if not posts or offset >= total or offset >= max_per_search:
                break
            time.sleep(REQUEST_DELAY)


# --- Amazon (amazon.jobs public search JSON) ---------------------------------

def fetch_amazon(searches, max_per_search):
    seen = set()
    for q in searches:
        offset = 0
        while offset < max_per_search:
            params = [
                ("base_query", q), ("result_limit", "100"), ("offset", str(offset)),
                ("sort", "recent"), ("normalized_country_code[]", "USA"),
            ]
            data = _request("https://www.amazon.jobs/en/search.json?" + urllib.parse.urlencode(params))
            jobs = data.get("jobs") or []
            for j in jobs:
                jid = j.get("id_icims") or j.get("id") or j.get("job_path")
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                posted = None
                try:
                    posted = dt.datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").date().isoformat()
                except ValueError:
                    pass
                yield {
                    "id": f"amazon:{jid}",
                    "title": (j.get("title") or "").strip(),
                    "url": "https://www.amazon.jobs" + (j.get("job_path") or ""),
                    "location": j.get("normalized_location") or j.get("location") or "",
                    "posted_at": posted,
                    "posted_approx": posted is None,
                }
            offset += 100
            if len(jobs) < 100:
                break
            time.sleep(REQUEST_DELAY)


# --- Greenhouse / Lever / Ashby (public job-board APIs) ----------------------

def _iso_date(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):  # epoch milliseconds
        return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).date().isoformat()
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def fetch_greenhouse(board):
    data = _request(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
    for j in data.get("jobs") or []:
        posted = _iso_date(j.get("first_published") or j.get("updated_at"))
        yield {
            "id": f"gh:{board}:{j.get('id')}",
            "title": (j.get("title") or "").strip(),
            "url": j.get("absolute_url") or "",
            "location": (j.get("location") or {}).get("name", ""),
            "posted_at": posted,
            "posted_approx": not j.get("first_published"),
        }


def fetch_lever(company):
    data = _request(f"https://api.lever.co/v0/postings/{company}?mode=json")
    for j in data or []:
        yield {
            "id": f"lever:{company}:{j.get('id')}",
            "title": (j.get("text") or "").strip(),
            "url": j.get("hostedUrl") or "",
            "location": (j.get("categories") or {}).get("location", ""),
            "posted_at": _iso_date(j.get("createdAt")),
            "posted_approx": False,
        }


def fetch_ashby(board):
    data = _request(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    for j in data.get("jobs") or []:
        yield {
            "id": f"ashby:{board}:{j.get('id') or j.get('jobUrl')}",
            "title": (j.get("title") or "").strip(),
            "url": j.get("jobUrl") or "",
            "location": j.get("location") or "",
            "posted_at": _iso_date(j.get("publishedAt")),
            "posted_approx": False,
        }
