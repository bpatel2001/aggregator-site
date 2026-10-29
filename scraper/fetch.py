"""Pull junior software engineering jobs from every company in companies.json.

Usage:
    python -m scraper.fetch                 # all companies
    python -m scraper.fetch --only "Capital One,NVIDIA"
    python -m scraper.fetch --check         # just test each company's endpoint, write status.json

Writes (inside site/data/, which the website reads):
    jobs.json      current junior roles with first_seen / posted dates
    status.json    per-company result of this run
    resolved.json  cache of corrected Workday hosts
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

from . import sources
from .classify import classify, guess_country

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = ROOT / "companies.json"
DATA = ROOT / "site" / "data"

SEARCHES = ["software", "developer", "graduate"]   # Workday free-text searches per site
MAX_PER_SEARCH = int(os.environ.get("MAX_PER_SEARCH", "300"))
WORKERS = int(os.environ.get("WORKERS", "6"))       # companies fetched in parallel
DROP_STALE_DAYS = 7  # keep a failing company's old jobs this long before dropping them


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    tmp.replace(path)


def fetch_company(company, resolved):
    """Return (raw_jobs, errors) for one company."""
    ats = company.get("ats", "workday")
    raw, errors = [], []
    if ats == "workday":
        for url in company.get("urls", []):
            try:
                raw.extend(sources.fetch_workday(url, SEARCHES, MAX_PER_SEARCH, resolved))
            except sources.FetchError as e:
                errors.append(str(e))
    elif ats == "amazon":
        try:
            raw.extend(sources.fetch_amazon(["software development engineer", "new grad software"], 600))
        except sources.FetchError as e:
            errors.append(str(e))
    elif ats in ("greenhouse", "lever", "ashby"):
        fn = {"greenhouse": sources.fetch_greenhouse, "lever": sources.fetch_lever,
              "ashby": sources.fetch_ashby}[ats]
        try:
            raw.extend(fn(company["board"]))
        except sources.FetchError as e:
            errors.append(str(e))
    else:
        errors.append(f"Unknown ats '{ats}'")
    return raw, errors


def check_company(company, resolved):
    """Lightweight reachability check (no paging)."""
    ats = company.get("ats", "workday")
    if ats != "workday":
        try:
            next(iter(fetch_company(company, resolved)[0]), None)
            return []
        except Exception as e:  # noqa: BLE001
            return [str(e)]
    errors = []
    for url in company.get("urls", []):
        try:
            sources.resolve_workday(url, resolved)
        except sources.FetchError as e:
            errors.append(str(e))
    return errors


def merge(previous, company_name, raw_jobs, ok, now):
    """Combine this run's jobs for one company with what we knew before."""
    prev_for_company = {j["id"]: j for j in previous if j["company"] == company_name}
    out = []
    if ok:
        for r in raw_jobs:
            level = classify(r["title"])
            if level is None:
                continue
            old = prev_for_company.get(r["id"])
            out.append({
                "id": r["id"],
                "company": company_name,
                "title": r["title"],
                "url": r["url"],
                "location": r["location"],
                "country": guess_country(r["location"], r["title"]),
                "level": level,
                # Keep the first date we computed: Workday's "Posted N Days Ago" drifts.
                "posted_at": (old or {}).get("posted_at") or r["posted_at"],
                "posted_approx": old["posted_approx"] if old and "posted_approx" in old else r["posted_approx"],
                "first_seen": (old or {}).get("first_seen") or now,
                "last_seen": now,
            })
        # De-duplicate (same job reachable from two sites of one company).
        uniq = {}
        for j in out:
            uniq.setdefault((j["title"].lower(), j["location"].lower(), j["url"].split("_")[-1]), j)
        return list(uniq.values())
    # Fetch failed: keep recent old data so one bad run doesn't wipe the company.
    cutoff = (dt.datetime.fromisoformat(now) - dt.timedelta(days=DROP_STALE_DAYS)).isoformat()
    return [j for j in prev_for_company.values() if j.get("last_seen", now) >= cutoff]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated company names")
    ap.add_argument("--check", action="store_true", help="only test endpoints")
    args = ap.parse_args(argv)

    companies = load_json(COMPANIES, {})["companies"]
    if args.only:
        wanted = {n.strip().lower() for n in args.only.split(",")}
        companies = [c for c in companies if c["name"].lower() in wanted]

    resolved = load_json(DATA / "resolved.json", {})
    state = load_json(DATA / "jobs.json", {"jobs": []})
    previous = state.get("jobs", [])
    now = now_iso()
    started = time.time()

    status, merged = {}, []
    names_run = {c["name"] for c in companies}

    def work(c):
        t0 = time.time()
        if args.check:
            return c, [], check_company(c, resolved), time.time() - t0
        raw, errs = fetch_company(c, resolved)
        return c, raw, errs, time.time() - t0

    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for c, raw, errs, secs in pool.map(work, companies):
            ok = not errs or bool(raw)  # partial success (one of two sites) still counts
            jobs = [] if args.check else merge(previous, c["name"], raw, ok, now)
            merged.extend(jobs)
            status[c["name"]] = {
                "ok": not errs,
                "partial": bool(errs) and bool(raw),
                "errors": errs,
                "scanned": len(raw),
                "junior_roles": len(jobs),
                "seconds": round(secs, 1),
            }
            flag = "OK " if not errs else ("PART" if raw else "FAIL")
            print(f"[{flag}] {c['name']:<28} scanned={len(raw):<5} junior={len(jobs):<4} {errs[0] if errs else ''}",
                  flush=True)

    save_json(DATA / "resolved.json", resolved)
    save_json(DATA / "status.json", {"run_at": now, "check_only": args.check, "companies": status})
    if args.check:
        bad = [n for n, s in status.items() if not s["ok"]]
        print(f"\n{len(status) - len(bad)}/{len(status)} endpoints reachable. Failing: {', '.join(bad) or 'none'}")
        return 0

    # Companies not part of this run keep their previous jobs untouched.
    merged.extend(j for j in previous if j["company"] not in names_run)
    merged.sort(key=lambda j: (j.get("posted_at") or "", j["first_seen"]), reverse=True)
    save_json(DATA / "jobs.json", {
        "generated_at": now,
        "previous_run_at": state.get("generated_at"),
        "companies_total": len(load_json(COMPANIES, {})["companies"]),
        "companies_ok": sum(1 for s in status.values() if s["ok"] or s["partial"]),
        "jobs": merged,
    })
    print(f"\n{len(merged)} junior roles saved in {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
