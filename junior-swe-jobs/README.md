# Junior SWE Jobs

A free, self-updating website that lists **junior and new-grad software engineering roles at Fortune 500 companies, newest first**.

Every 3 hours a GitHub Action pulls each company's own career site, keeps only junior software roles, and republishes the site on GitHub Pages. No server and no cost. It reads company career sites directly and never touches LinkedIn.

## Set it up (about 10 minutes)

1. **Create a public GitHub repo** and upload everything in this folder, keeping the folder structure. The `.github` folder is hidden on Mac, so press Cmd+Shift+. to see it. A public repo gets free GitHub Pages and unlimited Action minutes.
2. **Turn on Pages:** go to Settings → Pages → Build and deployment and set Source to **GitHub Actions**.
3. **Run it once:** go to the Actions tab → "Update jobs and publish site" → **Run workflow**. The first run takes about 10–15 minutes.
4. Your site is live at `https://YOUR-USERNAME.github.io/REPO-NAME/`. After that it refreshes itself every 3 hours.

## What's on the page

- Jobs grouped by day, newest first. You can switch between "Newest posted" (the company's posting date) and "Newest found" (when the scraper first saw the job).
- A dot and a banner mark roles that appeared since your last visit.
- Filters for search, company, US only vs. anywhere, and level:
  - **Entry level:** the title says so (new grad, junior, Engineer I, associate, early career, development program, and so on).
  - **Level not listed:** a software title with no seniority stated. These are often open to new grads, but check the posting.
  - **Internships:** off by default.
- A "Companies checked" list at the bottom shows which career sites responded on the last run.

## Coverage

`companies.json` starts with **73 Fortune 500 companies**:

- 70 on Workday. Each URL was confirmed live in October 2026.
- Amazon, through amazon.jobs.
- Airbnb and DoorDash on Greenhouse. These two are unconfirmed.

Many other Fortune 500 companies (Apple, Google, Microsoft, Meta, JPMorgan, IBM and others) run custom career sites. Those would each need their own adapter.

### Add a company

Find its job board URL and add one line to `companies.json`:

```json
{"name": "Some Company", "urls": ["https://somecompany.wd5.myworkdayjobs.com/External"]}
```

Most Workday career pages have a URL shaped like `https://TENANT.wdN.myworkdayjobs.com/SITE`, with an optional `/en-US/` before the site name. If the `wdN` number is wrong, the scraper tries the other Workday hosts and remembers the one that works.

Other supported boards:

```json
{"name": "X", "ats": "greenhouse", "board": "boardtoken"}
{"name": "X", "ats": "lever", "board": "companyname"}
{"name": "X", "ats": "ashby", "board": "boardname"}
```

## Run it on your computer

Only Python 3.10 or newer is needed. There are no packages to install.

```bash
python -m unittest discover tests                     # offline tests
python -m scraper.fetch --check                       # test every company endpoint quickly
python -m scraper.fetch --only "Capital One,NVIDIA"   # fetch a few companies
python -m scraper.fetch                               # fetch everything
python -m http.server -d site 8000                    # view at http://localhost:8000
```

## Tuning

| Setting | Where | Default |
|---|---|---|
| How often it runs | `cron` in `.github/workflows/update.yml` | every 3 hours |
| Workday search terms | `SEARCHES` in `scraper/fetch.py` | software, developer, graduate |
| Max results per search per site | `MAX_PER_SEARCH` env var | 300 |
| Companies fetched in parallel | `WORKERS` env var | 6 |
| Delay between requests to one site | `REQUEST_DELAY` env var | 0.4 s |
| What counts as junior | regexes in `scraper/classify.py` | see file |

## Notes

- The scraper reads the same public JSON that each company's career page loads in your browser. It runs slowly, a few requests at a time, and identifies itself in its user agent. Keep the delays polite. If a company asks you to stop, remove it.
- Workday only reports ages like "Posted 3 Days Ago" or "Posted 30+ Days Ago". The scraper turns these into dates when it first sees a job and keeps that date.
- If a site fails, its previous jobs stay up for up to 7 days, so one bad run doesn't wipe it.
