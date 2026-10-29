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


def fetch_workday(url, searches, max_per_search, cache, meta=None):
    """Yield jobs from one Workday career site. Sets meta["truncated"] if a search hit the cap.
    Note: Workday pages are 20 rows max, and past offset 2,000 it silently repeats page one."""
    meta = meta if meta is not None else {}
    max_per_search = min(max_per_search, 2000)
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
            if not posts or offset >= total:
                break
            if offset >= max_per_search:
                meta["truncated"] = True
                break
            time.sleep(REQUEST_DELAY)


# --- Amazon (amazon.jobs public search JSON) ---------------------------------

def fetch_amazon(searches, max_per_search, meta=None):
    meta = meta if meta is not None else {}
    seen = set()
    for q in searches:
        offset = 0
        while offset < max_per_search:
            params = [
                ("base_query", q), ("result_limit", "100"), ("offset", str(offset)),
                ("sort", "recent"), ("normalized_country_code[]", "USA"),
            ]
            data = _request("https://amazon.jobs/en/search.json?" + urllib.parse.urlencode(params))
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
            if offset >= max_per_search and (data.get("hits") or 0) > offset:
                meta["truncated"] = True
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


# --- Eightfold (Microsoft, Netflix, Lockheed Martin, Morgan Stanley, Ford, ...) ---------
# Newer search: GET {host}/api/pcsx/search?domain=..&query=..&start=N  -> data.positions (10 per page)
# Older search: GET {host}/api/apply/v2/jobs?domain=..&query=..&start=N -> positions
# Some hosts rate-limit hard (Microsoft answers 429 quickly), so pages are capped and slow.

def _epoch_to_date(ts):
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return None
    if ts > 1e12:  # milliseconds
        ts /= 1000
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat()


def _eightfold_row(host, domain, p):
    pid = p.get("id") or p.get("positionId") or p.get("ats_job_id")
    path = p.get("positionUrl") or ""
    if not pid and path:
        m = re.search(r"/job/(\d+)", path)
        pid = m.group(1) if m else path
    url = p.get("canonicalPositionUrl") or (
        f"https://{host}{path}" if path.startswith("/") else path) or f"https://{host}/careers/job/{pid}"
    locs = p.get("locations") or ([p["location"]] if p.get("location") else [])
    locs = [l if isinstance(l, str) else (l.get("name") or "") for l in locs]
    location = locs[0] if locs else ""
    if len(locs) > 1:
        location += f" +{len(locs) - 1} more"
    posted = _epoch_to_date(p.get("postedTs") or p.get("t_create") or p.get("creationTs"))
    return {
        "id": f"ef:{domain}:{pid}",
        "title": (p.get("name") or p.get("title") or "").strip(),
        "url": url,
        "location": location,
        "posted_at": posted,
        "posted_approx": posted is None,
    }


def fetch_eightfold(host, domain, queries, max_pages=15, delay=1.5, meta=None):
    meta = meta if meta is not None else {}
    seen, use_v2 = set(), False
    for q in queries:
        start, pages = 0, 0
        while True:
            params = {"domain": domain, "query": q, "location": "", "start": start, "sort_by": "timestamp"}
            if use_v2:
                params["num"] = 10
                url = f"https://{host}/api/apply/v2/jobs?" + urllib.parse.urlencode(params)
            else:
                url = f"https://{host}/api/pcsx/search?" + urllib.parse.urlencode(params)
            try:
                data = _request(url, retries=0)
            except FetchError as e:
                msg = str(e)
                if not use_v2 and ("HTTP 403" in msg or "HTTP 404" in msg) and not seen:
                    use_v2 = True  # this tenant only answers the older search
                    continue
                if any(code in msg for code in ("HTTP 429", "HTTP 405")):
                    meta["truncated"] = True  # rate-limited: keep what we have
                    if seen:
                        return
                raise
            box = data if use_v2 else (data.get("data") or {})
            positions = box.get("positions") or []
            count = box.get("count") or 0
            for p in positions:
                row = _eightfold_row(host, domain, p)
                if row["id"] in seen:
                    continue
                seen.add(row["id"])
                yield row
            pages += 1
            start += len(positions) or 10
            if not positions or start >= count:
                break
            if pages >= max_pages:
                meta["truncated"] = True
                break
            time.sleep(delay)
        time.sleep(delay)


# --- Oracle Recruiting Cloud (JPMorgan Chase, ...) -----------------------------
# GET {host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true
#     &expand=requisitionList.secondaryLocations
#     &finder=findReqs;siteNumber=SITE,limit=200,offset=N,sortBy=POSTING_DATES_DESC
# Newest first; we read the newest `max_rows` and filter titles locally.

def fetch_oracle(host, site, max_rows=1000, meta=None):
    meta = meta if meta is not None else {}
    offset, total = 0, 0
    while offset < max_rows:
        url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
               f"?onlyData=true&expand=requisitionList.secondaryLocations"
               f"&finder=findReqs;siteNumber={site},limit=200,offset={offset},sortBy=POSTING_DATES_DESC")
        data = _request(url)
        item = (data.get("items") or [{}])[0]
        reqs = item.get("requisitionList") or []
        total = item.get("TotalJobsCount") or total
        for r in reqs:
            rid = r.get("Id") or r.get("RequisitionId")
            yield {
                "id": f"oracle:{host}:{rid}",
                "title": (r.get("Title") or "").strip(),
                "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}",
                "location": r.get("PrimaryLocation") or "",
                "posted_at": _iso_date(r.get("PostedDate")),
                "posted_approx": not r.get("PostedDate"),
            }
        offset += 200
        if not reqs or offset >= total:
            return
        time.sleep(REQUEST_DELAY)
    if total > offset:
        meta["truncated"] = True
