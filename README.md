# Junior SWE Jobs

A free, self-updating website that lists **junior and new-grad software engineering roles at Fortune 500 companies and other big software employers, newest first**.

Every 3 hours a GitHub Action pulls each company's own career site, keeps only junior software roles, and republishes the site on GitHub Pages. No server and no cost. It reads company career sites directly and never touches LinkedIn.

## Set it up (about 10 minutes)

1. **Create a public GitHub repo** and upload everything in this folder, keeping the folder structure. The `.github` folder is hidden on Mac, so press Cmd+Shift+. to see it. A public repo gets free GitHub Pages and unlimited Action minutes.
2. **Turn on Pages:** go to Settings → Pages → Build and deployment and set Source to **GitHub Actions**.
3. **Run it once:** go to the Actions tab → "Update jobs and publish site" → **Run workflow**. The first run takes about 15–25 minutes.
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

`companies.json` covers **171 companies**: 105 from the Fortune 500 and 66 other large software employers. The site's company menu can filter to either group.

| Job system | Companies | Examples |
|---|---|---|
| Workday | 107 | Walmart, Cisco, Capital One, NVIDIA, Salesforce, Boeing, Fidelity |
| Greenhouse | 45 | Stripe, Databricks, Coinbase, Airbnb, Pinterest, SpaceX, Anthropic |
| Eightfold | 8 | Microsoft, Netflix, Lockheed Martin, Morgan Stanley, Ford, HP |
| Ashby | 6 | OpenAI, Notion, Ramp |
| Lever | 3 | Palantir, Spotify, Plaid |
| Amazon's own site | 1 | Amazon |
| Oracle | 1 | JPMorgan Chase |

Each job board was confirmed live in October 2026, except Morgan Stanley's, whose `domain` value is a best guess. Every run re-checks all of them and lists any that fail under "Companies checked" on the site.

Not covered: Apple, Google, Meta, IBM, Oracle, UnitedHealth and some others run career sites with no public job feed.

Some things to know:
- **Microsoft** limits how often its site can be read, so each run reads only its newest 50 or so matches per search. Occasionally it refuses entirely; the previous jobs stay up when that happens.
- **Big sites are read newest-first up to a cap** (300 results per Workday search, 1,000 for JPMorgan, 150 per Eightfold search). A job past the cap isn't treated as closed; it stays for up to 14 days. The status file marks these companies `"capped": true`.
- **Backup sources:** HP, Qualcomm, Micron and Northrop Grumman are moving between Workday and Eightfold, so each has an `alt` source that's tried if the main one fails.

### Add a company

Find its job board and add one line to `companies.json`. For Workday, paste the career-site URL:

```json
{"name": "Some Company", "urls": ["https://somecompany.wd5.myworkdayjobs.com/External"], "group": "fortune500"}
```

Workday career pages have a URL shaped like `https://TENANT.wdN.myworkdayjobs.com/SITE`, with an optional `/en-US/` before the site name. If the `wdN` number is wrong, the scraper tries the other Workday hosts and remembers the one that works.

Other job systems:

```json
{"name": "X", "ats": "greenhouse", "boards": ["boardtoken"], "group": "other"}
{"name": "X", "ats": "lever", "board": "companyname"}
{"name": "X", "ats": "ashby", "board": "boardname"}
{"name": "X", "ats": "eightfold", "host": "x.eightfold.ai", "domain": "x.com"}
{"name": "X", "ats": "oracle", "host": "xxxx.fa.us2.oraclecloud.com", "site": "CX_1001"}
```

How to find the values:
- **Greenhouse:** the word after `job-boards.greenhouse.io/` in a job link.
- **Lever:** the word after `jobs.lever.co/`.
- **Ashby:** the word after `jobs.ashbyhq.com/`.
- **Eightfold:** the careers site's host. `domain` is usually the company's web domain.
- **Oracle:** the host and the `sites/XXX` part of a job link.

Add `"alt": {...}` with a second source to have it tried when the first one fails.

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
| Max Workday results per search per site | `MAX_PER_SEARCH` env var | 300 |
| Eightfold pages (10 jobs each) and delay | `max_pages` and `delay` on the company entry | 15 pages, 1.5 s |
| Oracle rows read, newest first | `max_rows` on the company entry | 1000 |
| Companies fetched in parallel | `WORKERS` in the workflow file | 6 |
| Delay between requests to one site | `REQUEST_DELAY` env var | 0.4 s |
| What counts as junior | regexes in `scraper/classify.py` | see file |

## Notes

- The scraper reads the same public JSON that each company's career page loads in your browser. It runs slowly, a few requests at a time, and identifies itself in its user agent. Keep the delays polite. If a company asks you to stop, remove it.
- Workday only reports ages like "Posted 3 Days Ago" or "Posted 30+ Days Ago". The scraper turns these into dates when it first sees a job and keeps that date.
- If a site fails, its previous jobs stay up for up to 7 days, so one bad run doesn't wipe it.
