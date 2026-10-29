"""Offline tests: the network layer is replaced by a fake router that mimics
Workday, Amazon and Greenhouse responses. Run: python -m unittest discover tests
"""
import datetime as dt
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scraper import classify as C
from scraper import fetch, sources


def workday_page(titles, total, posted="Posted Today", loc="Austin, Texas"):
    return {
        "total": total,
        "jobPostings": [
            {"title": t, "externalPath": f"/job/X/{t.replace(' ', '-')}_R{abs(hash(t)) % 99999}",
             "locationsText": loc, "postedOn": posted}
            for t in titles
        ],
    }


class FakeNet:
    """Routes _request(url, body) calls to canned responses."""

    def __init__(self):
        self.calls = []
        self.wd_good_host = "wd5"  # pretend the company moved from wd1 to wd5
        self.fail_tenants = set()

    def __call__(self, url, body=None, retries=2):
        self.calls.append((url, body))
        if "myworkdayjobs.com" in url:
            tenant = url.split("//")[1].split(".")[0]
            wd = url.split(".")[1]
            if tenant in self.fail_tenants:
                raise sources.FetchError("HTTP 500")
            if wd != self.wd_good_host:
                raise sources.FetchError("HTTP 404")
            if body["limit"] == 1:
                return workday_page(["probe"], 1)
            q, off = body["searchText"], body["offset"]
            if q == "software" and off == 0:
                return workday_page(
                    ["Software Engineer I", "Senior Software Engineer", "Software Engineer",
                     "Software Engineer II", "Software Engineering Intern", "Accountant",
                     "Associate Software Engineer", "Staff Software Engineer", "Software Sales Rep",
                     "Software Engineer III", "Full Stack Developer", "Software Development Engineer",
                     "Principal Engineer", "Lead Developer", "SRE Manager", "Software QA Engineer",
                     "Software Engineer, New Grad 2027", "Mobile Developer", "Data Analyst", "Software Architect"],
                    total=25)
            if q == "software" and off == 20:
                return workday_page(["(IND) Software Engineer I", "Junior Software Engineer",
                                     "Software Engineer - Remote", "Sr Developer", "Software Engineer I"],
                                    total=0, posted="Posted 30+ Days Ago", loc="Hyderabad, India")
            if q == "graduate":
                return workday_page(["Technology Development Program Associate - 2027"], total=1,
                                    posted="Posted 3 Days Ago", loc="McLean, VA")
            return {"total": 0, "jobPostings": []}
        if "amazon.jobs" in url:
            if "offset=0" in url and "software+development+engineer" in url:
                return {"hits": 2, "jobs": [
                    {"id_icims": "111", "title": "Software Development Engineer I", "job_path": "/en/jobs/111",
                     "posted_date": "October 27, 2026", "normalized_location": "Seattle, Washington, USA"},
                    {"id_icims": "222", "title": "Senior Software Development Engineer", "job_path": "/en/jobs/222",
                     "posted_date": "October 28, 2026", "normalized_location": "Seattle, Washington, USA"},
                ]}
            return {"hits": 0, "jobs": []}
        if "greenhouse" in url:
            return {"jobs": [
                {"id": 9, "title": "Software Engineer, New Grad", "absolute_url": "https://x/9",
                 "location": {"name": "San Francisco, CA"}, "first_published": "2026-10-20T10:00:00Z"},
                {"id": 10, "title": "Staff Engineer", "absolute_url": "https://x/10",
                 "location": {"name": "Remote"}, "first_published": "2026-10-21T10:00:00Z"},
            ]}
        raise sources.FetchError("unexpected url " + url)


class ClassifierTests(unittest.TestCase):
    CASES = {
        "Software Engineer, New College Grad, Bellevue - 2027": "entry",
        "Software Engineer II (New College Grad 2026)": "entry",
        "Associate Software Engineer": "entry",
        "Software Engineer I": "entry",
        "Software Engineer (Apps), I": "entry",
        "Junior Full Stack Developer (Eng1)": "entry",
        "Technology Development Program Associate - August 2027": "entry",
        "Software Development Engineer I - Early Career (2027 Starts)": "entry",
        "Software Engineer I/II": "entry",
        "Software Engineer": "open",
        "Applications Development Programmer Analyst": "open",
        "Summer 2027 Intern - Software Engineer": "intern",
        "(IND) Software Engineer II": None,
        "Senior Software Engineer": None,
        "Software Engineering MTS": None,
        "Applications Development Intermediate Programmer Analyst": None,
        "VP; Software Engineer": None,
        "Software Sales Specialists - West": None,
        "Software Product Management Intern": None,
        "Engineer III": None,
    }

    def test_titles(self):
        for title, expected in self.CASES.items():
            with self.subTest(title=title):
                self.assertEqual(C.classify(title), expected)

    def test_country(self):
        self.assertEqual(C.guess_country("Bentonville, Arkansas"), "us")
        self.assertEqual(C.guess_country("Remote - US"), "us")
        self.assertEqual(C.guess_country("Plano, TX"), "us")
        self.assertEqual(C.guess_country("Bangalore, India"), "non-us")
        self.assertEqual(C.guess_country("", "(IND) Software Engineer II"), "non-us")
        self.assertEqual(C.guess_country("2 Locations"), "unknown")


class PostedDateTests(unittest.TestCase):
    def test_workday_labels(self):
        today = dt.date(2026, 10, 29)
        self.assertEqual(sources.parse_workday_posted("Posted Today", today), ("2026-10-29", False))
        self.assertEqual(sources.parse_workday_posted("Posted Yesterday", today), ("2026-10-28", False))
        self.assertEqual(sources.parse_workday_posted("Posted 5 Days Ago", today), ("2026-10-24", False))
        self.assertEqual(sources.parse_workday_posted("Posted 30+ Days Ago", today), ("2026-09-29", True))
        self.assertEqual(sources.parse_workday_posted(None, today), (None, True))

    def test_url_parsing(self):
        self.assertEqual(sources.parse_workday_url("https://walmart.wd504.myworkdayjobs.com/en-US/WalmartExternal"),
                         ("walmart", "wd504", "WalmartExternal"))
        self.assertEqual(sources.parse_workday_url("https://citi.wd5.myworkdayjobs.com/2/job/x"), ("citi", "wd5", "2"))
        with self.assertRaises(sources.FetchError):
            sources.parse_workday_url("https://example.com/careers")


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "companies.json").write_text(json.dumps({"companies": [
            {"name": "Acme Bank", "urls": ["https://acme.wd1.myworkdayjobs.com/External"]},
            {"name": "Broken Co", "urls": ["https://broken.wd5.myworkdayjobs.com/Jobs"]},
            {"name": "Amazon", "ats": "amazon"},
            {"name": "Startup", "ats": "greenhouse", "board": "startup"},
        ]}))
        self.net = FakeNet()
        self.net.fail_tenants = {"broken"}
        self.patches = [
            mock.patch.object(fetch, "COMPANIES", self.tmp / "companies.json"),
            mock.patch.object(fetch, "DATA", self.tmp / "data"),
            mock.patch.object(sources, "_request", self.net),
            mock.patch.object(sources, "REQUEST_DELAY", 0),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def jobs(self):
        return json.loads((self.tmp / "data" / "jobs.json").read_text())

    def test_full_run(self):
        fetch.main([])
        out = self.jobs()
        titles = {(j["company"], j["title"]) for j in out["jobs"]}
        # Junior + level-less roles kept, seniors dropped.
        self.assertIn(("Acme Bank", "Software Engineer I"), titles)
        self.assertIn(("Acme Bank", "Associate Software Engineer"), titles)
        self.assertIn(("Acme Bank", "Software Engineer"), titles)
        self.assertIn(("Acme Bank", "Technology Development Program Associate - 2027"), titles)
        self.assertIn(("Acme Bank", "Software Engineering Intern"), titles)
        self.assertNotIn(("Acme Bank", "Senior Software Engineer"), titles)
        self.assertNotIn(("Acme Bank", "Software Engineer II"), titles)
        self.assertNotIn(("Acme Bank", "Accountant"), titles)
        self.assertIn(("Amazon", "Software Development Engineer I"), titles)
        self.assertNotIn(("Amazon", "Senior Software Development Engineer"), titles)
        self.assertIn(("Startup", "Software Engineer, New Grad"), titles)

        # Paging: second page was requested, wd1 -> wd5 auto-repair recorded.
        resolved = json.loads((self.tmp / "data" / "resolved.json").read_text())
        self.assertEqual(resolved["https://acme.wd1.myworkdayjobs.com/External"][1], "wd5")
        self.assertTrue(any(b and b.get("offset") == 20 for _, b in self.net.calls))

        # Status reflects the broken company.
        status = json.loads((self.tmp / "data" / "status.json").read_text())["companies"]
        self.assertFalse(status["Broken Co"]["ok"])
        self.assertTrue(status["Acme Bank"]["ok"])

        # Non-US flagged; sorted newest first.
        india = [j for j in out["jobs"] if j["title"] == "(IND) Software Engineer I"][0]
        self.assertEqual(india["country"], "non-us")
        dates = [j["posted_at"] or "" for j in out["jobs"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_second_run_keeps_first_seen_and_survives_failure(self):
        fetch.main([])
        first = {j["id"]: j for j in self.jobs()["jobs"]}
        # Next run: Acme's Workday is down.
        self.net.fail_tenants = {"broken", "acme"}
        fetch.main([])
        second = {j["id"]: j for j in self.jobs()["jobs"]}
        acme_ids = [i for i, j in first.items() if j["company"] == "Acme Bank"]
        self.assertTrue(acme_ids)
        for i in acme_ids:  # old Acme jobs kept while its site is failing
            self.assertIn(i, second)
            self.assertEqual(second[i]["first_seen"], first[i]["first_seen"])

    def test_closed_jobs_removed(self):
        fetch.main([])
        # Next run: greenhouse returns nothing -> its job disappears.
        orig = self.net.__call__

        def no_gh(url, body=None, retries=2):
            if "greenhouse" in url:
                return {"jobs": []}
            return orig(url, body, retries)

        with mock.patch.object(sources, "_request", no_gh):
            fetch.main([])
        self.assertFalse([j for j in self.jobs()["jobs"] if j["company"] == "Startup"])


if __name__ == "__main__":
    unittest.main()
