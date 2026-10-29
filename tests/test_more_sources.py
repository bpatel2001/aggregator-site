"""Offline tests for Eightfold, Oracle, multi-board Greenhouse, fallback sources and capped scans."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scraper import fetch, sources
from scraper.classify import classify


def pcsx_page(start, total, names, ts=1793232000):
    return {"data": {"count": total, "positions": [
        {"id": 1000 + start + i, "name": n, "locations": ["Redmond, Washington, United States", "Seattle, WA"],
         "postedTs": ts, "positionUrl": f"/careers/job/{1000 + start + i}"}
        for i, n in enumerate(names)]}}


class Net:
    def __init__(self):
        self.calls = []
        self.rate_limit_after = None  # pcsx page index after which 429 is returned

    def __call__(self, url, body=None, retries=2):
        self.calls.append(url)
        if "pcsx/search" in url and "bigco.example" in url:
            start = int(url.split("start=")[1].split("&")[0])
            if self.rate_limit_after is not None and start >= self.rate_limit_after:
                raise sources.FetchError("HTTP 429 from " + url)
            if "new+grad" in url:
                return pcsx_page(500, 1, ["Software Engineer - New Grad"])
            names = ["Software Engineer", "Senior Software Engineer", "Software Engineer II",
                     "Software Engineer Asc", "Principal PM", "Software Engineer (L3)",
                     "Program Manager", "Software Engineer: Early in Career", "Staff SWE", "Dev Intern"]
            return pcsx_page(start, 25, names if start < 20 else names[:5])
        if "pcsx/search" in url and "oldco.example" in url:
            raise sources.FetchError("HTTP 403 from " + url)
        if "apply/v2/jobs" in url and "oldco.example" in url:
            if "start=0" in url and "software" in url:
                return {"count": 2, "positions": [
                    {"id": 7, "name": "Software Engineer (L4)", "location": "Los Gatos, California",
                     "t_create": 1793232000, "canonicalPositionUrl": "https://oldco.example/careers/job/7"},
                    {"id": 8, "name": "Software Engineer (L3)", "location": "Los Gatos, California",
                     "t_create": 1793232000, "canonicalPositionUrl": "https://oldco.example/careers/job/8"}]}
            return {"count": 0, "positions": []}
        if "recruitingCEJobRequisitions" in url:
            offset = int(url.split("offset=")[1].split(",")[0])
            rows = [{"Id": str(210000 + offset + i), "Title": t, "PostedDate": "2026-10-27",
                     "PrimaryLocation": "Plano, TX, United States"}
                    for i, t in enumerate(["Software Engineer - Early Career Software Engineer Program",
                                           "Software Engineer III", "Lead Software Engineer", "Teller"] * 50)]
            return {"items": [{"TotalJobsCount": 5000, "requisitionList": rows}]}
        if "boards-api.greenhouse.io" in url:
            board = url.split("/boards/")[1].split("/")[0]
            return {"jobs": [{"id": hash(board) % 1000, "title": f"Software Engineer, New Grad ({board})",
                              "absolute_url": f"https://x/{board}", "location": {"name": "Remote - US"},
                              "first_published": "2026-10-20T00:00:00Z"}]}
        if "myworkdayjobs.com" in url:
            raise sources.FetchError("HTTP 404 from " + url)
        raise sources.FetchError("unexpected " + url)


class MoreSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "companies.json").write_text(json.dumps({"companies": [
            {"name": "BigCo", "ats": "eightfold", "host": "bigco.example", "domain": "bigco.com",
             "max_pages": 2, "delay": 0},
            {"name": "OldCo", "ats": "eightfold", "host": "oldco.example", "domain": "oldco.com", "delay": 0},
            {"name": "Bank", "ats": "oracle", "host": "bank.example", "site": "CX_1", "max_rows": 400},
            {"name": "MultiBoard", "ats": "greenhouse", "boards": ["one", "two"]},
            {"name": "Moved", "urls": ["https://moved.wd1.myworkdayjobs.com/External"],
             "alt": {"ats": "greenhouse", "board": "movedgh"}},
        ]}))
        self.net = Net()
        self.patches = [
            mock.patch.object(fetch, "COMPANIES", self.tmp / "companies.json"),
            mock.patch.object(fetch, "DATA", self.tmp / "data"),
            mock.patch.object(sources, "_request", self.net),
            mock.patch.object(sources, "REQUEST_DELAY", 0),
            mock.patch.object(sources.time, "sleep", lambda s: None),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def out(self):
        return json.loads((self.tmp / "data" / "jobs.json").read_text())

    def status(self):
        return json.loads((self.tmp / "data" / "status.json").read_text())["companies"]

    def test_all_sources(self):
        fetch.main([])
        jobs = self.out()["jobs"]
        by = {}
        for j in jobs:
            by.setdefault(j["company"], set()).add(j["title"])

        # Eightfold (new search): junior kept, senior dropped, capped at 2 pages -> flagged.
        self.assertIn("Software Engineer Asc", by["BigCo"])
        self.assertIn("Software Engineer - New Grad", by["BigCo"])
        self.assertIn("Software Engineer (L3)", by["BigCo"])
        self.assertNotIn("Senior Software Engineer", by["BigCo"])
        self.assertTrue(self.status()["BigCo"]["capped"])
        big = [j for j in jobs if j["company"] == "BigCo"][0]
        self.assertTrue(big["url"].startswith("https://bigco.example/careers/job/"))
        self.assertEqual(big["posted_at"], "2026-10-29")
        self.assertIn("+1 more", big["location"])

        # Eightfold falls back to the older search on 403.
        self.assertEqual(by["OldCo"], {"Software Engineer (L3)"})

        # Oracle: newest 400 rows read, junior titles kept, capped flag set (5000 total).
        self.assertEqual(by["Bank"], {"Software Engineer - Early Career Software Engineer Program"})
        self.assertTrue(self.status()["Bank"]["capped"])
        bank = [j for j in jobs if j["company"] == "Bank"][0]
        self.assertIn("/hcmUI/CandidateExperience/en/sites/CX_1/job/", bank["url"])

        # Several Greenhouse boards for one company.
        self.assertEqual(len(by["MultiBoard"]), 2)

        # Workday dead -> alt source used, company reported OK.
        self.assertEqual(by["Moved"], {"Software Engineer, New Grad (movedgh)"})
        self.assertTrue(self.status()["Moved"]["ok"])

    def test_rate_limit_keeps_partial_and_old_jobs(self):
        fetch.main(["--only", "BigCo"])
        first_ids = {j["id"] for j in self.out()["jobs"]}
        # Next run: rate-limited after the first page.
        self.net.rate_limit_after = 10
        fetch.main(["--only", "BigCo"])
        second_ids = {j["id"] for j in self.out()["jobs"]}
        self.assertTrue(self.status()["BigCo"]["ok"])
        self.assertEqual(first_ids, second_ids)  # jobs beyond the limit were kept, not dropped

    def test_check_mode(self):
        fetch.main(["--check"])
        st = self.status()
        self.assertTrue(st["BigCo"]["ok"])
        self.assertTrue(st["Moved"]["ok"])  # alt passes the check


class TitleTests(unittest.TestCase):
    def test_new_patterns(self):
        self.assertEqual(classify("Software Engineer Asc"), "entry")
        self.assertEqual(classify("Software Engineer (L3)"), "entry")
        self.assertIsNone(classify("Software Engineer (L4)"))
        self.assertIsNone(classify("Software Engineer 5 - iOS"))
        self.assertEqual(classify("Associate, Software Engineer"), "open")


if __name__ == "__main__":
    unittest.main()
