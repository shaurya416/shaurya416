"""Offline tests: the network layer against a local mock of the GitHub API, then the stats step and
the renderer. No real API call is made and no token is needed.

    python3 -m unittest discover -s tests -v

tests/fixtures/search.json holds recorded search results; tests/fixtures/rest.json is constructed in
the documented REST shapes (timelines, commit lookups, star counts) and says so in its _note.

The suite never reads the live data/ directory, so a refresh that changes data/ cannot turn it red.
tests/fixtures/data/ is a frozen data directory: the hand-written and captured inputs (areas, notes, probe,
projects, trigalign) plus the five files a fetch writes from the two fixtures above. tests/fixtures/widgets/ holds
the files the workflow's two Actions write (see its NOTE.txt). Every fixture-driven test
builds from it into a temporary directory. One test (CommittedOutputs) checks that the committed
README, CHECKS and assets are what build.py renders from the live data/; that one passes after a refresh
because the refresh job renders before it commits.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import statistics
import sys
import tempfile
import threading
import unittest
import urllib.parse
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build as B  # noqa: E402

FX = ROOT / "tests" / "fixtures"
FXDATA = FX / "data"
HAND_WRITTEN = ("areas.json", "notes.json", "probe.json", "projects.json", "trigalign.json")
WIDGETS = FX / "widgets"   # the two Actions' files at their pinned versions, run on a made-up calendar


def copy_fixture_data(dest, only=None):
    """The frozen data directory into dest. projects.json is written from build.py's own TOOLS list (every package
    unreleased) rather than frozen, so adding or removing a package there needs no fixture edit."""
    for f in FXDATA.iterdir():
        if only is None or f.name in only:
            shutil.copy(f, dest / f.name)
    if only is None or "projects.json" in only:
        names = [n for _, items in B.TOOLS for n, _ in items]
        (dest / "projects.json").write_text(json.dumps({n: {"status": "unreleased"} for n in names}))
# (length, sha256) of product names no surface may carry; the private-name list is read from PRIVATE_ENV at test time
TOOL_DIGESTS = (
    (6, "c857d09db23e6822e3600bc06ad8d58f92ed62bc8efd81c753f77048662cb97d"),
    (9, "c70eca6b0f88f44d81a41311647e50fda1ac454ec04ffd442b0eb4743a993131"),
    (7, "60965168ce762e949600281ba6d01fee136e5b6e8257b1f216f9025ed324474c"),
    (7, "3ea125d0bff386e6754b3782b300016fc79a9cf8f8669c0a5c3db64467ddb681"),
    (6, "7d3194f79e645c42e4396dda38be04766810ec6a00d00aced3ffc2a0a1f1a9ef"),
    (4, "3360ada3f393965cbab00e7a603b39b890543462a99bd623a236dc2e9d8e9e28"),
)
PRIVATE_ENV = "PROFILE_PRIVATE_WORDS"   # comma-separated; the private-name check is skipped when unset
TOKEN = "ghs_test-token-0123456789abcdef"
EXCLUDE = "-org:hidden-org -user:other-owner"   # stands in for the real PROFILE_EXCLUDE secret
AS_OF = dt.datetime(2026, 10, 8, 20, 50, tzinfo=dt.timezone.utc)


class Clock:
    """sleep() advances time instead of waiting, so pacing and backoff are measurable."""

    def __init__(self):
        self.t, self.sleeps = 1_000_000.0, []

    def sleep(self, s):
        self.sleeps.append(round(s, 3))
        self.t += s

    def now(self):
        return self.t


def serve(handle):
    """handle(path, query, headers) -> (status, headers, body). Returns (server, base url)."""

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            status, headers, body = handle(u.path, urllib.parse.parse_qs(u.query), self.headers)
            raw = json.dumps(body).encode()
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class MockGitHub:
    """Enough of api.github.com for build.py fetch, driven by the fixtures."""

    def __init__(self, honour_org=True, extra_issues=()):
        s = json.loads((FX / "search.json").read_text())
        self.rest = json.loads((FX / "rest.json").read_text())
        self.items = s["issues"] + s["prs"] + list(extra_issues)
        self.honour_org = honour_org
        self.queries, self.paths, self.auth, self.accept = [], [], set(), {}
        self.base = ""

    def match(self, it, terms):
        owner = it["repository_url"].rstrip("/").split("/")[-2].lower()
        for t in terms:
            if t.startswith("author:") and it["user"]["login"].lower() != t[7:].lower():
                return False
            if t == "is:issue" and "pull_request" in it or t == "is:pr" and "pull_request" not in it:
                return False
            if t in ("is:open", "is:closed") and it["state"] != t[3:]:
                return False
            merged = (it.get("pull_request") or {}).get("merged_at")
            if t == "is:merged" and not merged or t == "is:unmerged" and merged:
                return False
            if t.split(":")[0] in ("-org", "-user") and self.honour_org and owner == t.split(":", 1)[1].lower():
                return False
            if t.startswith("created:"):
                lo, hi = t[8:].split("..")
                if not lo <= it["created_at"][:10] <= hi:
                    return False
        return True

    def handle(self, path, q, headers):
        self.paths.append(path)
        self.auth.add(headers.get("Authorization"))
        self.accept[path] = headers.get("Accept")
        one = {k: v[0] for k, v in q.items()}
        if path == "/search/issues":
            query = one["q"]
            self.queries.append(query)
            if query in self.rest["fallback_search"]:
                rows = self.rest["fallback_search"][query]
            else:
                rows = sorted((i for i in self.items if self.match(i, query.split())), key=lambda i: i["created_at"])
            page, per = int(one.get("page", 1)), int(one.get("per_page", 30))
            if page * per > 1000 + per - 1:
                return 422, {}, {"message": "Only the first 1000 search results are available"}
            return 200, {"x-ratelimit-remaining": "25", "x-ratelimit-reset": "0"}, {
                "total_count": len(rows), "incomplete_results": False, "items": rows[(page - 1) * per: page * per]}
        if path == "/search/repositories":
            names = [t[5:] for t in one["q"].split() if t.startswith("repo:")]
            stars = self.rest["stars"]
            return 200, {}, {"total_count": 0, "incomplete_results": False,
                             "items": [{"full_name": r, "stargazers_count": stars[r]} for r in names if r in stars]}
        parts = path.strip("/").split("/")
        if len(parts) == 6 and parts[0] == "repos" and parts[3] == "issues" and parts[5] == "timeline":
            key = f"{parts[1]}/{parts[2]}#{parts[4]}"
            if key in self.rest["timeline_missing"] or key not in self.rest["timelines"]:
                return 404, {}, {"message": "Not Found"}
            events = self.rest["timelines"][key]
            size = self.rest["timeline_page_size"].get(key, int(one.get("per_page", 30)))
            page = int(one.get("page", 1))
            h = {}
            if page * size < len(events):
                h["link"] = f'<{self.base}{path}?per_page=100&page={page + 1}>; rel="next"'
            return 200, h, events[(page - 1) * size: page * size]
        if len(parts) == 6 and parts[3] == "commits" and parts[5] == "pulls":
            return 200, {}, self.rest["commit_pulls"].get(parts[4], [])
        return 404, {}, {"message": "Not Found"}


class Fresh:
    """A data directory holding only the hand-written inputs, as on a first fetch."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())
        copy_fixture_data(self.dir, only=HAND_WRITTEN)

    def __enter__(self):
        return self.dir

    def __exit__(self, *a):
        shutil.rmtree(self.dir)


def run_fetch(data, mock, now=AS_OF, **kw):
    srv, url = serve(mock.handle)
    mock.base = url
    clock = Clock()
    client = B.Client(TOKEN, url, sleep=clock.sleep, clock=clock.now, wall=clock.now, proxies={}, **kw)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            summary = B.fetch(data, client, now)
    finally:
        srv.shutdown()
        srv.server_close()
    return summary, client, clock, out.getvalue() + err.getvalue()


def fixture_counts():
    """How many issues and pull requests the fixtures hold once the mock has honoured the exclusion."""
    return (len(json.loads((FXDATA / "issues.json").read_text())),
            len(json.loads((FXDATA / "prs.json").read_text())))


def pages(n):
    return max(1, -(-n // 100))


class FetchEndToEnd(unittest.TestCase):
    def reproduce(self, exclude):
        env = {"PROFILE_EXCLUDE": exclude} if exclude is not None else {}
        mock_api = MockGitHub()
        with mock.patch.dict("os.environ", env), Fresh() as data:
            if exclude is None:
                os.environ.pop("PROFILE_EXCLUDE", None)   # unset, not just empty
            summary, client, clock, logs = run_fetch(data, mock_api)
            for f in ("issues.json", "prs.json", "stars.json"):
                self.assertEqual((data / f).read_bytes(), (FXDATA / f).read_bytes(), f)
            meta = json.loads((data / "fetch.json").read_text())
            self.assertIs(meta["exclusion_applied"], bool(exclude and exclude.strip()))
            if not meta["exclusion_applied"]:
                return summary, client, clock, logs, mock_api
            for f in ("fetch.json", "stats.json"):
                self.assertEqual((data / f).read_bytes(), (FXDATA / f).read_bytes(), f)
            out = Path(tempfile.mkdtemp())
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    B.render(data, out)
                B.check_readme((out / "README.md").read_text())
                self.assertTrue((out / "CHECKS.md").read_text().startswith("# checks"))
                for p in B.PANELS:
                    for t in B.THEMES:
                        self.assertTrue((out / "assets" / f"{p}-{t}.svg").is_file())
            finally:
                shutil.rmtree(out)
        return summary, client, clock, logs, mock_api

    def test_fetch_reproduces_the_committed_data_and_page(self):
        summary, client, clock, logs, api = self.reproduce(EXCLUDE)
        self.assertEqual(summary["traced"], {"timeline": 24, "search": 1, "kept": 0})
        # PROFILE_EXCLUDE is appended verbatim to every author query and never printed
        author = [q for q in api.queries if q.startswith("author:")]
        n_issues, n_prs = fixture_counts()
        self.assertEqual(len(author), 7 + pages(n_issues) + pages(n_prs))   # seven counts, then the result pages
        self.assertTrue(all(q.endswith(" " + EXCLUDE) for q in author))
        self.assertTrue(all(q.startswith("author:shaurya416 is:public ") for q in author))
        for part in ("hidden-org", "other-owner", EXCLUDE):
            self.assertNotIn(part, logs)
        # the token reached the server in the header and nowhere else
        self.assertEqual(api.auth, {f"Bearer {TOKEN}"})
        self.assertNotIn(TOKEN, logs)
        self.assertNotIn(TOKEN, repr(client))
        # timeline calls ask for the preview media type; search was paced at 2.5 s
        timeline = [p for p in api.accept if p.endswith("/timeline")]
        self.assertTrue(timeline)
        self.assertTrue(all(api.accept[p] == B.TIMELINE_TYPE for p in timeline))
        self.assertGreaterEqual(client.calls["search"], 11 + 23 + 1)
        self.assertIn(B.SEARCH_GAP, clock.sleeps)
        self.assertEqual(api.paths.count("/repos/huggingface/trl/issues/7364/timeline"), 2)   # Link: rel="next"

    def test_no_exclusion_when_the_variable_is_empty_or_unset(self):
        for value in ("", None):
            _, _, _, _, api = self.reproduce(value)
            author = [q for q in api.queries if q.startswith("author:")]
            self.assertEqual(len(author), 7 + sum(pages(n) for n in fixture_counts()))
            self.assertTrue(all("-org:" not in q and "-user:" not in q and not q.endswith(" ") for q in author), author)
            self.assertTrue(all(" is:public " in q for q in author))
        with mock.patch.dict("os.environ", {"PROFILE_EXCLUDE": "  "}):
            self.assertEqual(B.excluded_owners(), ())
            self.assertEqual(B.author_query("is:pr"), "author:shaurya416 is:public is:pr")

    def test_the_exclusion_is_scrubbed_from_errors(self):
        with mock.patch.dict("os.environ", {"PROFILE_EXCLUDE": EXCLUDE}):
            e = B.ApiError(422, "/search/issues", f"cannot search {EXCLUDE}: hidden-org, OTHER-OWNER")
            self.assertNotIn("hidden-org", str(e).lower())
            self.assertNotIn("other-owner", str(e).lower())
            self.assertIn("[excluded]", str(e))
            self.assertEqual(B.excluded_owners(), ("hidden-org", "other-owner"))

    def test_quiet_rerun_writes_nothing_and_the_heartbeat_keeps_the_schedule_alive(self):
        with Fresh() as data:
            run_fetch(data, MockGitHub())
            before = {f.name: f.read_bytes() for f in data.iterdir()}
            summary, client, _, _ = run_fetch(data, MockGitHub(), AS_OF + dt.timedelta(days=1))
            self.assertEqual(summary["written"], [])
            self.assertEqual(summary["traced"], {"timeline": 0, "search": 0, "kept": 25})
            self.assertEqual(client.calls["core"], 0)
            self.assertEqual({f.name: f.read_bytes() for f in data.iterdir()}, before)
            later = AS_OF + dt.timedelta(days=B.HEARTBEAT_DAYS)
            summary, _, _, _ = run_fetch(data, MockGitHub(), later)
            self.assertTrue(summary["heartbeat"])
            self.assertFalse(summary["changed"])
            self.assertEqual(sorted(summary["written"]), ["fetch.json", "stars.json", "stats.json"])
            meta = json.loads((data / "fetch.json").read_text())
            self.assertEqual(meta["as_of"], "2026-10-08T20:50Z")       # no number changed
            self.assertEqual(meta["checked"], later.date().isoformat())

    def test_a_row_from_an_excluded_owner_is_dropped_and_the_run_refuses(self):
        row = {"html_url": "https://github.com/hidden-org/x/issues/1", "number": 1, "title": "t",
               "repository_url": "https://api.github.com/repos/hidden-org/x", "state": "open",
               "created_at": "2026-09-30T00:00:00Z", "comments": 0,
               "user": {"login": "shaurya416", "id": 298017155}}
        with mock.patch.dict("os.environ", {"PROFILE_EXCLUDE": EXCLUDE}):
            with Fresh() as data:   # the qualifier is honoured: the row never arrives
                summary, _, _, logs = run_fetch(data, MockGitHub(extra_issues=[row]))
                self.assertEqual(summary["issues"], fixture_counts()[0])
                self.assertNotIn("hidden-org", (data / "issues.json").read_text())
                self.assertNotIn("hidden-org", logs)
            with Fresh() as data:   # the qualifier fails: the row is dropped and the counts no longer agree
                with self.assertRaises(SystemExit) as e:
                    run_fetch(data, MockGitHub(honour_org=False, extra_issues=[row]))
                self.assertIn("disagree", str(e.exception))
                self.assertFalse((data / "issues.json").exists())
                self.assertNotIn("hidden-org", str(e.exception))

    def test_collapse_is_refused(self):
        with Fresh() as data:
            run_fetch(data, MockGitHub())
            mock = MockGitHub()
            mock.items = [i for i in mock.items if "pull_request" in i or i["created_at"] > "2026-09-30"]
            with self.assertRaises(SystemExit) as e:
                run_fetch(data, mock, AS_OF + dt.timedelta(days=1))
            self.assertIn("refusing to overwrite", str(e.exception))
            self.assertEqual(len(json.loads((data / "issues.json").read_text())), fixture_counts()[0])


class RateLimits(unittest.TestCase):
    def client(self, handle, **kw):
        srv, url = serve(handle)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        clock = Clock()
        return B.Client(TOKEN, url, sleep=clock.sleep, clock=clock.now, wall=clock.now, proxies={}, **kw), clock

    def test_retry_after_is_honoured(self):
        n = []

        def h(p, q, hd):
            n.append(p)
            if len(n) == 1:
                return 403, {"retry-after": "7"}, {"message": "You have exceeded a secondary rate limit."}
            return 200, {}, {"total_count": 0, "incomplete_results": False, "items": []}
        c, clock = self.client(h)
        B.search(c, "x", AS_OF.date())
        self.assertIn(8.0, clock.sleeps)
        self.assertEqual(len(n), 2)

    def test_exhausted_primary_limit_waits_for_reset(self):
        n = []

        def h(p, q, hd):
            n.append(p)
            if len(n) == 1:
                return 429, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(1_000_030)}, {"message": "API rate limit exceeded"}
            return 200, {}, {"total_count": 0, "incomplete_results": False, "items": []}
        c, clock = self.client(h)
        B.search(c, "x", AS_OF.date())
        self.assertTrue(any(29 <= s <= 32 for s in clock.sleeps), clock.sleeps)

    def test_low_remaining_after_success_sleeps_to_reset(self):
        def h(p, q, hd):
            return 200, {"x-ratelimit-remaining": "1", "x-ratelimit-reset": str(1_000_020)}, {
                "total_count": 0, "incomplete_results": False, "items": []}
        c, clock = self.client(h)
        B.search(c, "x", AS_OF.date())
        self.assertTrue(any(19 <= s <= 22 for s in clock.sleeps), clock.sleeps)

    def test_a_403_that_is_not_a_rate_limit_is_raised_at_once(self):
        n = []

        def h(p, q, hd):
            n.append(p)
            return 403, {}, {"message": "Resource not accessible by integration"}
        c, _ = self.client(h)
        with self.assertRaises(B.ApiError) as e:
            B.search(c, "x", AS_OF.date())
        self.assertNotIsInstance(e.exception, B.RateLimited)
        self.assertEqual(e.exception.status, 403)
        self.assertEqual(len(n), 1)

    def test_message_naming_a_rate_limit_backs_off_then_gives_up(self):
        def h(p, q, hd):
            return 403, {}, {"message": "API rate limit exceeded for installation"}
        c, clock = self.client(h, retries=2)
        with self.assertRaises(B.RateLimited):
            B.search(c, "x", AS_OF.date())
        self.assertEqual([s for s in clock.sleeps if s >= 60], [60.0, 120.0])

    def test_server_errors_back_off(self):
        n = []

        def h(p, q, hd):
            n.append(p)
            if len(n) < 3:
                return 502, {}, {"message": "Bad Gateway"}
            return 200, {}, {"total_count": 0, "incomplete_results": False, "items": []}
        c, clock = self.client(h)
        B.search(c, "x", AS_OF.date())
        self.assertEqual(len(n), 3)
        self.assertIn(2, clock.sleeps)
        self.assertIn(4, clock.sleeps)

    def test_search_pages_are_serial_and_paced(self):
        rows = [{"n": i} for i in range(250)]

        def h(p, q, hd):
            page, per = int(q["page"][0]), int(q["per_page"][0])
            self.assertEqual(per, 100)
            return 200, {}, {"total_count": 250, "incomplete_results": False, "items": rows[(page - 1) * per: page * per]}
        c, clock = self.client(h)
        self.assertEqual(len(B.search(c, "x", AS_OF.date())), 250)
        self.assertEqual(c.calls["search"], 3)
        self.assertEqual(sum(clock.sleeps), 2 * B.SEARCH_GAP)

    def test_over_1000_matches_is_split_by_date(self):
        start = dt.date(2025, 1, 1)
        rows = [{"n": i, "created_at": f"{start + dt.timedelta(days=i % 400)}T00:00:00Z"} for i in range(1500)]

        def h(p, q, hd):
            qs, page, per = q["q"][0], int(q["page"][0]), int(q["per_page"][0])
            sel = rows
            if "created:" in qs:
                lo, hi = qs.split("created:")[1].split("..")
                sel = [r for r in rows if lo <= r["created_at"][:10] <= hi]
            if (page - 1) * per >= 1000:
                return 422, {}, {"message": "Only the first 1000 search results are available"}
            return 200, {}, {"total_count": len(sel), "incomplete_results": False, "items": sel[(page - 1) * per: page * per]}
        c, _ = self.client(h)
        got = B.search(c, "x", dt.date(2026, 10, 8))
        self.assertEqual(sorted(r["n"] for r in got), list(range(1500)))

    def test_incomplete_results_stop_the_run(self):
        def h(p, q, hd):
            return 200, {}, {"total_count": 0, "incomplete_results": True, "items": []}
        with Fresh() as data:
            srv, url = serve(h)
            clock = Clock()
            c = B.Client(TOKEN, url, sleep=clock.sleep, clock=clock.now, wall=clock.now, proxies={})
            try:
                with self.assertRaises(SystemExit) as e:
                    B.fetch(data, c, AS_OF)
            finally:
                srv.shutdown()
                srv.server_close()
            self.assertIn("incomplete", str(e.exception))
            self.assertEqual(sorted(f.name for f in data.iterdir()), sorted(HAND_WRITTEN))

    def test_no_token_no_run(self):
        with self.assertRaises(SystemExit):
            B.Client("")

    def test_a_next_link_to_another_host_is_refused(self):
        def h(p, q, hd):
            return 200, {"link": '<https://elsewhere.example/x?page=2>; rel="next"'}, [{"event": "labeled"}]
        c, _ = self.client(h)
        with self.assertRaises(B.ApiError):
            c.pages("/repos/o/r/issues/1/timeline")


class StatsAndAreas(unittest.TestCase):
    def rows(self):
        return [json.loads(json.dumps(r)) for r in B.read(FXDATA / "issues.json")]

    def stats(self, issues, areas=None):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            st = B.derive_stats(issues, B.read(FXDATA / "prs.json"), B.read(FXDATA / "stars.json"),
                                areas if areas is not None else B.read(FXDATA / "areas.json"),
                                B.read(FXDATA / "fetch.json"))
        return st, err.getvalue()

    def test_stats_step_matches_the_committed_file(self):
        st, _ = self.stats(self.rows())
        self.assertEqual(B.dump(st), (FXDATA / "stats.json").read_text())

    def test_a_pr_merged_after_the_close_is_not_the_fix(self):
        issues = self.rows()
        before, _ = self.stats(self.rows())
        it = next(i for i in issues if i["repo"] == "unit8co/darts")
        it["merged_prs"].append({"pr": 3230, "author": "example-user", "merged_at": "2026-10-20T00:00:00Z",
                                 "hours": B.hours_between(it["created_at"], "2026-10-20T00:00:00Z")})
        st, _ = self.stats(issues)
        self.assertEqual(st["outcomes"]["fixed_by_merged_pr_from_someone_else"],
                         before["outcomes"]["fixed_by_merged_pr_from_someone_else"])
        self.assertNotIn(3230, [f["pr"] for f in st["fixes_by_others"]])

    def test_new_repository_gets_a_rule_area_and_is_reported(self):
        areas = B.read(FXDATA / "areas.json")
        areas.pop("ludlows/PESQ")
        areas.pop("rasbt/mlxtend")
        st, err = self.stats(self.rows(), areas)
        placed = {x["repo"]: x["area"] for x in st["areas_by_rule"]}
        self.assertEqual(placed["ludlows/PESQ"], "Speech & audio")
        self.assertIn("rasbt/mlxtend", placed)
        self.assertIn("ludlows/PESQ", err)
        self.assertEqual(B.area_of("someone/zzz", {}, ["qqq"]), (B.OTHER, False))
        self.assertEqual(sum(e["issues"] for e in st["ecosystems"]), len(self.rows()))


_BASE = []


def base_build():
    """README, CHECKS and assets built once from the frozen fixture data; read-only for the tests."""
    if not _BASE:
        out = Path(tempfile.mkdtemp())
        data = Path(tempfile.mkdtemp())
        try:
            copy_fixture_data(data)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                B.render(data, out)
        finally:
            shutil.rmtree(data)
        _BASE.append(out)
    return _BASE[0]


def tearDownModule():
    for out in _BASE:
        shutil.rmtree(out, ignore_errors=True)


class CommittedOutputs(unittest.TestCase):
    """The only test that reads the live data/ and the committed outputs. A refresh renders before it commits,
    so this holds after one; it fails only when build.py or a hand-written input changed and nobody rebuilt."""

    def test_the_committed_page_is_what_the_build_renders_from_the_committed_data(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            B.render(ROOT / "data", out, ROOT)
        names = B.PANELS + B.ART + [f"{a}-narrow" for a in sorted(B.NARROW_ART)]
        for f in ["README.md", "CHECKS.md"] + [f"assets/{p}-{t}.svg" for p in names for t in B.THEMES]:
            self.assertEqual((out / f).read_bytes(), (ROOT / f).read_bytes(), f)


class RenderGuards(unittest.TestCase):
    def build(self, mutate=None):
        data = Path(tempfile.mkdtemp())
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, data)
        self.addCleanup(shutil.rmtree, out)
        copy_fixture_data(data)
        if mutate:
            mutate(data)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            B.render(data, out)
        return out

    @staticmethod
    def snapshot(out):
        return {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*")) if p.is_file()}

    def test_two_builds_give_the_same_bytes(self):
        self.assertEqual(self.snapshot(self.build()), self.snapshot(self.build()))

    def test_hostile_text_is_escaped_everywhere(self):
        evil = '</text><script>alert(1)</script> | [x](javascript:alert(1)) <img src=x onerror=1> & *b* `c`\n\n# h'

        def mutate(data):
            notes = B.read(data / "notes.json")
            notes["rows"][0]["what"] = evil
            notes["lead"] = "eight of the fixes share one defect: " + evil
            (data / "notes.json").write_text(json.dumps(notes))
            issues = B.read(data / "issues.json")
            for i in issues:
                i["title"] = evil
            (data / "issues.json").write_text(json.dumps(issues))
        out = self.build(mutate)
        text = (out / "README.md").read_text()
        for bad in ("<script", "<img src=x", 'href="javascript', "\n# h"):
            self.assertNotIn(bad, text)
        self.assertNotRegex(text, r"(?<!\\)\]\(javascript")   # the bracket is escaped: text, not a link
        self.assertIn("&lt;script&gt;", text)
        B.check_readme(text)
        for f in (out / "assets").iterdir():
            B.check_svg(f.name, f.read_text())
            self.assertNotIn("<script", f.read_text())

    def test_guards_reject_what_they_should(self):
        good = (base_build() / "README.md").read_text()
        for bad in ("<script>x</script>", '<a href="http://example.com">x</a>', "[x](http://example.com)",
                    '<img src="https://example.com/x.svg">', '<td style="color:red">x</td>', "| a | b |\n|--|--|\n| a | b | c |"):
            with self.assertRaises(SystemExit, msg=bad):
                B.check_readme(good + "\n" + bad + "\n")
        svg = (base_build() / "assets" / "probe-light.svg").read_text()
        with self.assertRaises(SystemExit):
            B.check_svg("x", svg.replace("</svg>", '<image href="http://example.com/x"/></svg>'))
        with self.assertRaises(SystemExit):
            B.check_svg("x", svg.replace("</svg>", "<text>unclosed</svg>"))

    def test_overflow_and_collision_fail_the_build(self):
        s = B.Svg(B.THEMES["light"], "t", "d")
        with self.assertRaises(SystemExit):
            s.text(B.PAD, 40, "x" * 47)
        s.text(B.PAD, 60, "left")
        with self.assertRaises(SystemExit):
            s.text(B.PAD + 10, 62, "overlap")
        with self.assertRaises(SystemExit):
            s.text(B.CARD - B.PAD, 400, "below the card", "e")

    def test_the_method_states_the_exclusion_only_when_applied(self):
        def mutate(data):
            st = B.read(data / "stats.json")
            st["exclusion_applied"] = False
            (data / "stats.json").write_text(json.dumps(st))
        self.assertIn("excluding the owner's own organisations", (self.build() / "README.md").read_text())
        self.assertNotIn("excluding", (self.build(mutate) / "README.md").read_text())

    def test_no_text_below_twelve_units(self):
        for f in (base_build() / "assets").glob("*.svg"):
            sizes = [float(x) for x in __import__("re").findall(r"font-size:([\d.]+)px", f.read_text())]
            self.assertGreaterEqual(min(sizes), 12, f.name)

    def test_the_window_grows_into_weeks_then_months(self):
        for days, unit in ((40, "week"), (400, "month")):
            def mutate(data, days=days):
                st = B.read(data / "stats.json")
                st["as_of"] = (dt.date(2026, 10, 8) + dt.timedelta(days=days)).isoformat() + "T06:17Z"
                (data / "stats.json").write_text(json.dumps(st))
            out = self.build(mutate)
            self.assertIn(f"issues per {unit}, utc", (out / "assets" / "filed-light.svg").read_text())

    def test_the_lead_count_must_match_the_rows(self):
        n = len(B.read(FXDATA / "notes.json")["rows"])
        was, now = B.NUMBER_WORDS[n], B.NUMBER_WORDS[n + 1]

        def notes_with(lead=None, extra=False):
            def mutate(data):
                notes = B.read(data / "notes.json")
                if extra:   # a fix the merged pull requests really closed, not yet in the table
                    notes["rows"].append({"issue": "EvolvingLMMs-Lab/lmms-eval#1546", "what": "a ninth row"})
                if lead:
                    notes["lead"] = lead
                (data / "notes.json").write_text(json.dumps(notes))
            return mutate
        with self.assertRaises(SystemExit):          # one more row under a lead that still has the old count
            self.build(notes_with(extra=True))
        with self.assertRaises(SystemExit):          # a lead that does not state the count at all
            self.build(notes_with(lead="a missing result counted as a score."))
        out = self.build(notes_with(lead=f"{now} of the fixes share one defect: a missing result counted as a score.",
                                    extra=True))
        self.assertIn(f"{now} of the fixes share one defect", (out / "README.md").read_text())
        self.assertIn(f"| {now} of the fixes |", (out / "CHECKS.md").read_text().replace("\\", ""))
        self.assertNotEqual(was, now)

    def test_quoted_figures_are_listed_and_still_on_the_page(self):
        text, checks = (base_build() / "README.md").read_text(), (base_build() / "CHECKS.md").read_text()
        self.assertIn("## quoted, not computed", checks)
        for where, anchor, figure, source in B.QUOTED:
            line = next(ln for ln in text.splitlines() if anchor in ln)
            self.assertIn(figure, line, where)
            self.assertIn(f"| {B.md(where)} | {B.md(figure)} | {B.md(source)} |", checks)

    def test_a_quoted_figure_that_changes_on_the_page_stops_the_build(self):
        for where, anchor, figure, _ in B.QUOTED:
            changed = figure[::-1]
            guide = [ln.replace(figure, changed) for ln in B.FIELD_GUIDE]
            tools = [(g, [(n, d.replace(figure, changed)) for n, d in items]) for g, items in B.TOOLS]
            self.assertTrue(guide != B.FIELD_GUIDE or tools != B.TOOLS, f"{where}: the figure is not in the page text")
            with mock.patch.object(B, "FIELD_GUIDE", guide), mock.patch.object(B, "TOOLS", tools), \
                    self.assertRaises(SystemExit, msg=where):
                self.build()

    def test_the_prose_reads_the_way_a_stranger_would(self):
        text = (base_build() / "README.md").read_text()
        since = B.read(FXDATA / "stats.json")["issues"]["first_created_at"][:10]
        alt = readme_alts(text)["stats-light.svg"]
        self.assertTrue(alt.startswith(f"Since {since}: "), alt)   # a year, because "sept 23" reads as 2023
        for th in B.THEMES:
            self.assertIn(f"since {since}", B.drawn_text(art("stats-narrow", th)))
        self.assertNotIn("since sept", text)
        self.assertEqual(text.count("habit"), 1)     # only the side quest claims one
        self.assertEqual(text.count("share one defect"), 1)   # the fold's summary does not repeat the sentence under it
        self.assertIn("more panels and the one-defect table</summary>", text)

    def test_the_areas_panel_has_no_voice_echo(self):
        for theme in ("light", "dark"):
            svg = (base_build() / "assets" / f"areas-{theme}.svg").read_text()
            self.assertNotIn("any area", svg)
            self.assertNotIn("speech or audio", svg)
            self.assertIn("speech &amp; audio", svg)  # the area itself stays: it is where three repositories sit


class Projects(unittest.TestCase):
    """data/projects.json decides which package names are links. Every test but the first writes the state it needs
    instead of reading today's, so flipping an entry on release day changes nothing here."""

    NAMES = [n for _, items in B.TOOLS for n, _ in items]
    # a package the field guide names, so it is linked in two places; chosen from the page text, not by name,
    # so taking one off the page (PUBLISH.md section 0) leaves these tests as they were
    SAMPLE = next((n for n in NAMES if n != "scoreprobe" and any("{" + n + "}" in ln for ln in B.FIELD_GUIDE)),
                  next(n for n in NAMES if n != "scoreprobe"))
    SAMPLE_LINKS = 1 + "".join(B.FIELD_GUIDE).count("{" + SAMPLE + "}")

    @staticmethod
    def url(n):
        return f"https://github.com/shaurya416/{n}"

    def render(self, released=(), projects=None, probe_url="auto", probe_status="auto"):
        """README.md from a copy of the fixture data in which `released` names are public and the rest are not.
        projects overrides single entries (None removes one); probe_url and probe_status default to what
        scoreprobe's own state implies: its url and a version when released, neither when not."""
        if probe_url == "auto":
            probe_url = self.url("scoreprobe") if "scoreprobe" in released else None
        if probe_status == "auto":
            probe_status = "v0.1.0" if "scoreprobe" in released else B.PROBE_PENDING

        def mutate(data):
            p = {n: ({"status": "released", "url": self.url(n)} if n in released else {"status": "unreleased"})
                 for n in self.NAMES}
            for k, v in (projects or {}).items():
                p.pop(k, None) if v is None else p.__setitem__(k, v)
            (data / "projects.json").write_text(json.dumps(p))
            probe = B.read(data / "probe.json")
            probe.pop("url", None)
            probe["status"] = probe_status
            if probe_url:
                probe["url"] = probe_url
            (data / "probe.json").write_text(json.dumps(probe))
        return (RenderGuards.build(self, mutate) / "README.md").read_text()

    def test_the_committed_page_follows_projects_json(self):
        text = (ROOT / "README.md").read_text()
        projects = B.read(ROOT / "data" / "projects.json")
        self.assertEqual(sorted(projects), sorted(self.NAMES))
        out = [n for n, p in projects.items() if p["status"] == "released"]
        for n, p in projects.items():
            if p["status"] == "released":
                self.assertEqual(p["url"], self.url(n))
                self.assertIn(f"[**{n}**]({self.url(n)})", text, n)
            else:
                self.assertIn(n, readme_alts(text)["shelf-light.svg"], n)
                self.assertNotIn(self.url(n), text, n)
        self.assertEqual("none is public yet, so no links" in text, not out)
        self.assertEqual("linked names under the shelf are out" in text, 0 < len(out) < len(projects))
        self.assertEqual("its first public release is pending" in text, "scoreprobe" not in out)

    def test_an_unreleased_package_is_bold_and_never_linked(self):
        text = self.render()
        shelf = readme_alts(text)["shelf-light.svg"]
        for n in self.NAMES:
            self.assertIn(n, shelf, n)                # named on the shelf, which links nothing
            self.assertNotIn(self.url(n), text, n)
        self.assertNotIn("out now:", text)
        self.assertIn("none is public yet, so no links", text)
        self.assertIn("its first public release is pending", text)

    def test_a_released_package_is_linked_everywhere_it_is_named(self):
        sample = self.SAMPLE
        text = self.render(released=(sample,))
        self.assertEqual(text.count(f"[**{sample}**]({self.url(sample)})"), self.SAMPLE_LINKS)   # field guide + shelf line
        self.assertIn(f"out now: [**{sample}**]({self.url(sample)})", text)
        for n in self.NAMES:
            if n != sample:
                self.assertNotIn(self.url(n), text, n)
        self.assertIn("linked names under the shelf are out", text)
        self.assertNotIn("none is public yet", text)

    def test_with_every_package_released_the_page_says_so_and_scoreprobe_links_in_the_method(self):
        text = self.render(released=self.NAMES)
        for n in self.NAMES:
            self.assertIn(f"[**{n}**]({self.url(n)})", text, n)
        self.assertNotIn("none is public yet", text)
        self.assertNotIn("linked names under the shelf are out", text)
        self.assertNotIn("its first public release is pending", text)
        self.assertIn(f"a captured run of [scoreprobe]({self.url('scoreprobe')})", text)

    def test_bad_project_entries_stop_the_build(self):
        name = self.NAMES[0]
        for bad in ({name: {"status": "released"}},
                    {name: {"status": "released", "url": f"https://github.com/someone/{name}"}},
                    {name: {"status": "unreleased", "url": self.url(name)}},
                    {name: {"status": "coming"}},
                    {name: None},
                    {"extra": {"status": "unreleased"}},
                    {"scoreprobe": {"status": "released", "url": self.url("scoreprobe")}}):   # probe.json has no url
            with self.assertRaises(SystemExit, msg=bad):
                self.render(projects=bad)
        with self.assertRaises(SystemExit):           # the other way round: probe.json has a url, projects.json does not
            self.render(probe_url=self.url("scoreprobe"))

    def test_scoreprobe_released_in_one_file_and_not_the_other_stops_the_build(self):
        url = self.url("scoreprobe")
        pending = B.PROBE_PENDING
        with self.assertRaises(SystemExit) as e:      # linked in both files, but the panel still says pending
            self.render(released=("scoreprobe",), probe_status=pending)
        self.assertIn("released in projects.json but probe.json still says", str(e.exception))
        self.assertIn(pending, str(e.exception))
        with self.assertRaises(SystemExit) as e:      # not released, yet the panel carries a version
            self.render(probe_status="v0.1.0")
        self.assertIn("unreleased in projects.json but probe.json status is", str(e.exception))
        self.assertIn("capture-probe", str(e.exception))
        with self.assertRaises(SystemExit):           # a url in probe.json alone, status still pending
            self.render(probe_url=url)
        text = self.render(released=("scoreprobe",), probe_status="v9.9.9")   # consistent: builds, links, no "pending"
        self.assertIn(f"[scoreprobe]({url})", text)
        self.assertNotIn(pending, text)

    def test_the_side_quest_numbers_are_checked(self):
        checks = (base_build() / "CHECKS.md").read_text()
        st = B.read(FXDATA / "stats.json")
        o = st["outcomes"]
        words = B.NUMBER_WORDS
        rows = len(B.read(FXDATA / "notes.json")["rows"])
        tiles = "side-quest stat tiles, all three widths"
        for needle in ("README side quest", f"{tiles} | issues filed | {st['issues']['total']} issues filed",
                       f"{tiles} | repositories | {st['issues']['distinct_repos']} repos",
                       f"since {st['issues']['first_created_at'][:10]}",
                       f"{tiles} | fixed | {o['fixed_by_merged_pr_from_someone_else'] + o['fixed_by_his_own_merged_pr']} fixed",
                       f"{o['fixed_by_merged_pr_from_someone_else']} by others, {o['fixed_by_his_own_merged_pr']} by me",
                       f"{tiles} | PRs upstream | ",
                       f"{words[len(B.PANELS) - 1]} more panels",
                       f"README defect table | fixes in the table, lead sentence | {words[rows]} of the fixes",
                       f"{words[len(B.read(FXDATA / 'probe.json')['source'])]}-line grader"):
            self.assertIn(needle, checks)

    def test_no_voice_headline_and_no_banned_words(self):
        text = (base_build() / "README.md").read_text().lower()
        for w in ("voice", "passionate", "leverag", "cutting-edge", "enthusiast", "10x", "rockstar", "co-authored-by"):
            self.assertNotIn(w, text)


# ------------------------------------------------------------ illustrations ----
OLD_PANEL_HASHES = {   # sha1[:8] of the four panels, from the fixtures; a change to one is a deliberate edit here
    # filed (bars on a baseline, then a key for the hollow own-PR squares) and areas (card trimmed to its last line)
    # were redrawn on purpose; the others are as they were before the illustrations were added
    ("filed", "dark"): "66461f4d", ("filed", "light"): "8027f89d", ("outcome", "dark"): "b9cd6d71",
    ("outcome", "light"): "58445d9c", ("areas", "dark"): "0fdc2a5a", ("areas", "light"): "f56dc0bf",
    ("probe", "dark"): "f5b5ebe9", ("probe", "light"): "9ed7cb48",
}
ART_FILES = [(a, t) for a in B.ART for t in B.THEMES] + [(f"{a}-{size}", t) for a in sorted(B.NARROW_ART)
                                                          for size in B.SIZES_OF[1:] for t in B.THEMES]


def fixture_model():
    data = Path(tempfile.mkdtemp())
    try:
        copy_fixture_data(data)
        with contextlib.redirect_stderr(io.StringIO()):
            return B.model(data)
    finally:
        shutil.rmtree(data)


_MODEL = []


def model():
    if not _MODEL:
        _MODEL.append(fixture_model())
    return _MODEL[0]


def art(name, theme="light", out=None):
    return ((out or base_build()) / "assets" / f"{name}-{theme}.svg").read_text()


def readme_alts(text):
    """{src file name: alt} for every <img> on the page, unescaped as a browser would."""
    seen = {}

    class P(B.HTMLParser):
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "img":
                seen[a["src"].split("?")[0].rsplit("/", 1)[-1]] = a["alt"]
    P(convert_charrefs=True).feed(text)
    return seen


def build_with(mutate=None, widgets=None):
    data, out = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    try:
        copy_fixture_data(data)
        if mutate:
            mutate(data)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            B.render(data, out, widgets)
    except BaseException:
        shutil.rmtree(out)
        raise
    finally:
        shutil.rmtree(data)
    return out


class Illustrations(unittest.TestCase):
    def test_old_panels_are_byte_identical(self):
        text = (base_build() / "README.md").read_text()
        for (name, th), want in OLD_PANEL_HASHES.items():
            got = hashlib.sha1(art(name, th).encode()).hexdigest()[:8]
            self.assertEqual(got, want, f"{name}-{th}")
            self.assertIn(f"assets/{name}-{th}.svg?v={want}", text)

    def test_every_new_asset_is_guard_clean(self):
        self.assertEqual(len(ART_FILES), 40)
        for name, th in ART_FILES:
            B.check_art(f"{name}-{th}", art(name, th))
        svg = art("header")
        bad = {
            "image": svg.replace("</svg>", '<image href="https://example.com/x.png"/></svg>'),
            "infinite": svg.replace("animation:draw 2.4s ease-in-out .4s both", "animation:draw 2.4s ease-in-out .4s infinite"),
            "no reduced motion": svg.replace(B.MOTION, ""),
            "transform-box": svg.replace(".rt{", ".rt{transform-box:fill-box;"),
            "11-unit text": svg.replace(".s13{font-size:13px}", ".s13{font-size:11px}"),
            "web font": svg.replace("text{font-family:", "text{font-family:Inter,"),
            "six repeats": svg.replace("5.94s 4}", "5.94s 6}"),
            "too long": svg.replace("5.94s 4}", "9.5s 4}"),
        }
        for what, tampered in bad.items():
            with self.assertRaises(SystemExit, msg=what):
                B.check_art("x", tampered)

    def test_resting_state_is_the_final_frame(self):
        """With every animation taken away, nothing that carries content is hidden or half drawn."""
        allowed = {"cur", "fq", "cu"}    # blinking cursors, quantum's frames before the resting one, the sweep line
        for name, th in ART_FILES:
            svg = art(name, th)
            root = B.ET.fromstring(svg)
            css = next(el.text for el in root.iter() if el.tag.endswith("style"))
            hidden = set()
            for sel, decls in B.css_rules(css):
                decls.pop("animation", None)
                if decls.get("opacity") == "0" or decls.get("display") == "none" or \
                        decls.get("stroke-dashoffset", "0") not in ("0", "0px"):
                    hidden.add(sel.lstrip("."))
            self.assertLessEqual(hidden, allowed, name)
            for el in root.iter():
                self.assertNotEqual(el.get("opacity"), "0", name)
                self.assertNotIn("display:none", el.get("style", ""), name)
            if name.startswith("analyzer"):   # the sweep cover rests at zero width, inside the plot it covers
                w = float(root.get("width"))
                self.assertIn(".sw{transform-origin:", css)
                self.assertRegex(css, r"\.sw\{[^}]*transform:scaleX\(0\)")
                cover = re.search(r'<rect class="sw" x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', svg)
                self.assertLessEqual(float(cover.group(1)) + float(cover.group(2)), w - 1, name)

    def test_no_animation_runs_past_eleven_seconds(self):
        for name, th in ART_FILES:
            svg = art(name, th)
            root = B.ET.fromstring(svg)
            css = next(el.text for el in root.iter() if el.tag.endswith("style"))
            timed = {}
            for sel, decls in B.css_rules(css):
                if "animation" in decls:
                    dur, dly, count = B.animation(decls["animation"])
                    self.assertLessEqual(dly + dur * count, 11.0, f"{name} {sel}")
                    self.assertLessEqual(count, 5)
                    timed[sel.lstrip(".")] = dur * count
            for el in root.iter():
                mo = re.fullmatch(r"animation-delay:([\d.]+)s", el.get("style", ""))
                if mo:
                    run = max(timed[c] for c in el.get("class").split() if c in timed)
                    self.assertLessEqual(float(mo.group(1)) + run, 11.0, name)

    def test_text_floor_and_collisions_on_wide_canvases(self):
        for w, h in ((830, 390), (380, 912)):
            s = B.Svg(B.THEMES["dark"], "t", "d", w=w, h=h, frame=False, area=(14, w - 14, 0, h - 4))
            with self.assertRaises(SystemExit):
                s.text(14, 40, "x" * int((w - 28) / (12 * B.ADV) + 2))
            with self.assertRaises(SystemExit):
                s.text(w - 14, h + 10, "below", "e")
            with self.assertRaises(SystemExit):
                s.text(14, 40, "small", "", 11)
            s.text(14, 60, "left", "", 16)
            with self.assertRaises(SystemExit):
                s.text(20, 62, "overlap")
            s.text(14, 120, "frame a", layer=1)
            s.text(14, 120, "frame b", layer=2)          # two frames never shown at once may share a place
            with self.assertRaises(SystemExit):
                s.text(14, 120, "always")

    def test_shotfloor_formula(self):
        self.assertEqual(f"{B.fidelity_floor(1024):.4f}", "0.9239")
        guide = next(ln for ln in B.FIELD_GUIDE if ln.startswith("- **quantum**"))
        self.assertIn(f"about {B.fidelity_floor(1024):.2f} hellinger fidelity", guide)
        self.assertEqual(B.shots_for(0.95), 1425)
        self.assertEqual([f"{B.fidelity_floor(s):.3f}" for s in (128, 256, 512, 1024)], ["0.381", "0.599", "0.806", "0.924"])
        counts = B.counts_of(B.shot_draw(0, 256, 1024), 256)
        self.assertEqual(f"{B.bc2(counts, 1024, 256):.4f}", "0.9334")
        self.assertEqual(counts.count(0), 3)
        g = B.splitmix64(0)                      # the published first outputs of splitmix64 seeded with 0
        self.assertEqual([next(g) for _ in range(2)], [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4])

    def test_trigalign_capture_is_consistent(self):
        doc = B.read(FXDATA / "trigalign.json")
        B.check_trigalign(doc)
        for mutate in (lambda d: d["logs"][0].__setitem__("n_paired", 193),
                       lambda d: d["logs"][0]["pairs"][5].__setitem__("residual_ms", 3.0),
                       lambda d: d.__setitem__("source", d["source"].replace("CC0", "CC-BY"))):
            bad = json.loads(json.dumps(doc))
            mutate(bad)
            with self.assertRaises(SystemExit):
                B.check_trigalign(bad)

    def test_the_lost_trigger_note_needs_the_marker(self):
        self.assertIn("(the recording paused)", art("brains"))

        def drop(data):
            doc = B.read(data / "trigalign.json")
            doc["logs"][0]["unmatched"][0].pop("on_marker")
            (data / "trigalign.json").write_text(json.dumps(doc))
        out = build_with(drop)
        self.addCleanup(shutil.rmtree, out)
        self.assertNotIn("recording paused", art("brains", out=out))
        self.assertNotIn("recording paused", readme_alts((out / "README.md").read_text())["brains-light.svg"])
        self.assertIn("no trigger at", art("brains", out=out))

    def test_constellation_counts_equal_the_outcomes(self):
        m = model()
        o = dict(m["outcome"])
        for name in ("constellation", "constellation-narrow"):
            svg = art(name)
            sky = re.search(r'<g class="sky">(.*?)</g>', svg, re.S).group(1)
            self.assertEqual(sky.count('class="op"'), o["open"], name)
            self.assertEqual(sky.count('r="3.2"'), o["nofix"], name)
            self.assertEqual(svg.count('<g class="lit"'), m["fixed"], name)
            lit = re.findall(r'<g class="lit".*?</g>', svg)
            self.assertEqual(sum('r="12.5"' in g for g in lit), o["own"], name)
            self.assertEqual(o["open"] + o["nofix"] + m["fixed"], m["total"])
        self.assertEqual([len(st) for _, st in m["stars"]], [a["issues"] for a in m["areas"]])
        self.assertEqual(sum(1 for _, st in m["stars"] for x in st if x["rank"] is not None), m["fixed"])

    def test_star_labels_cover_every_area(self):
        self.assertTrue(all(len(v) <= B.STAR_LABEL_MAX for v in B.STAR_LABELS.values()))
        labels = dict(B.STAR_LABELS)
        labels.pop(model()["areas"][-1]["bucket"])
        with mock.patch.object(B, "STAR_LABELS", labels), self.assertRaises(SystemExit):
            fixture_model()

    def test_analyzer_rederives_every_hour(self):
        m = model()
        rows = m["fixrows"]
        self.assertEqual(len(rows), m["fixed"])
        table = (base_build() / "README.md").read_text()
        for r in rows:
            repo, num = r["key"].rsplit("#", 1)
            line = next(ln for ln in table.splitlines() if f"/{repo}/issues/{num})" in ln and ln.startswith("| "))
            self.assertIn(f"{r['hours']:.1f}", line.rsplit("|", 2)[1], r["key"])
        others = [r["hours"] for r in rows if not r["own"]]
        self.assertEqual(round(statistics.median(others), 1), m["lag"]["median"])
        ch0 = re.search(r'<path d="(M[^"]*)" stroke="#6e7781" stroke-width="1"/>', art("analyzer")).group(1)
        self.assertEqual(ch0.count("M"), m["total"])
        with mock.patch.object(B, "hours_between", lambda a, b: 1.0), self.assertRaises(SystemExit):
            fixture_model()

    def test_analyzer_axis_grows_into_weeks_then_months(self):
        for days, unit in ((40, "week"), (400, "month")):
            def mutate(data, days=days):
                st = B.read(data / "stats.json")
                st["as_of"] = (dt.date(2026, 10, 8) + dt.timedelta(days=days)).isoformat() + "T06:17Z"
                (data / "stats.json").write_text(json.dumps(st))
            out = build_with(mutate)
            self.addCleanup(shutil.rmtree, out)
            for name in ("analyzer", "analyzer-narrow"):
                self.assertIn(f"utc, {unit}s", art(name, out=out))
            if unit == "month":
                self.assertIn(">2026-09<", art("analyzer", out=out))

    def test_header_stops_follow_the_intro(self):
        intro = B.INTRO_TEXT[0]
        stops = [x for x in B.HEADER_STOPS if x[3] == "intro"]
        where = [intro.index(x[2]) for x in stops]
        self.assertEqual(where, sorted(where))
        self.assertEqual(B.HEADER_STOPS[-1][0], "music")
        clock = next(ln for ln in B.FIELD_GUIDE if ln.startswith("- **off the clock**"))
        self.assertIn(B.HEADER_STOPS[-1][2], clock)
        for name in ("header", "header-narrow"):
            svg = art(name)
            for label, *_ in B.HEADER_STOPS:
                self.assertIn(f">{label}<", svg)

    def test_the_grep_line_survives(self):
        text = (base_build() / "README.md").read_text()
        self.assertNotIn("```", text)
        alt = readme_alts(text)["header-light.svg"]
        for name in ("header", "header-narrow"):
            desc = B.ET.fromstring(art(name)).find("{http://www.w3.org/2000/svg}desc").text
            for line in B.GREP:
                self.assertIn(line, desc)
                self.assertIn(line, alt)
        typed = "".join(re.findall(r'<tspan class="k"[^>]*>([^<]*)</tspan>', art("header"))).replace("\xa0", " ")
        self.assertEqual(typed, B.GREP[0])

    def test_the_shelf_draws_every_tool_at_every_width(self):
        alt = readme_alts((base_build() / "README.md").read_text())["shelf-light.svg"]
        for size in ("shelf", "shelf-mid", "shelf-narrow"):
            for th in B.THEMES:
                svg = art(size, th)
                drawn = B.drawn_text(svg)
                root = B.ET.fromstring(svg)
                width = float(root.get("width"))
                for group, items in B.TOOLS:
                    self.assertIn(group, drawn)
                    for name, desc in items:
                        self.assertIn(f">{name}<", svg)
                        self.assertIn(desc.replace("`", ""), drawn, (size, name))   # wrapped, never cut
                        self.assertIn(desc.replace("`", ""), alt)
                for code in re.findall(r"`([^`]*)`", "".join(d for _, it in B.TOOLS for _, d in it)):
                    self.assertIn(f'<tspan class="a">{B.escape(code, quote=False)}</tspan>', svg)
                for x, w in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', svg):
                    self.assertLessEqual(float(x) + float(w), width - 13, size)       # cards stay inside the frame
        self.assertEqual(B.shelf_layout("narrow")["cols"], 1)
        self.assertEqual(B.shelf_layout("wide")["cols"], 2)
        with self.assertRaises(SystemExit):
            B.tool_icon("no-such-tool", B.THEMES["light"])
        with self.assertRaises(SystemExit):                      # a word longer than a card line stops the build
            B.tool_lines("x" * 200, 100)
        self.assertEqual(B.tool_lines("a `git status` b", 12 * B.ADV * 12), ["a `git status`", "b"])

    def test_the_brains_card_labels_its_extra_trigger(self):
        doc = B.read(FXDATA / "trigalign.json")
        k = len(doc.get("unpaired_triggers") or [])
        self.assertGreater(k, 0)                                 # the fixture carries one, so the label is tested
        for th in B.THEMES:
            self.assertIn(f"{k} extra trigger", B.drawn_text(art("brains", th)))

    def test_the_habit_sentence_does_not_repeat_the_table(self):
        text = (base_build() / "README.md").read_text()
        habit = next(ln for ln in text.splitlines() if ln.startswith(B.SIDE_ANCHOR))
        self.assertIsNone(re.search(r"\d", habit))
        self.assertNotIn("| since ", text)          # the numbers are the stat tiles now, not a table
        after = text.split(habit, 1)[1].lstrip("\n")
        self.assertTrue(after.startswith("<p>\n<picture>\n") and "stats-narrow-dark.svg" in after.split("</picture>")[0])

    def test_the_quantum_card_calls_its_curve_a_bound(self):
        alt = readme_alts((base_build() / "README.md").read_text())["quantum-light.svg"]
        self.assertIn("lower bound on the mean Hellinger fidelity", alt)
        self.assertNotIn("exact formula", alt)
        for th in B.THEMES:
            drawn = B.drawn_text(art("quantum", th))
            self.assertIn("E[BC]² ≤ mean F", drawn)
            self.assertNotIn("expected F", drawn)
            self.assertNotIn("uniform:8", drawn)

    def test_large_pictures_have_a_frame_in_both_themes(self):
        for name in ("constellation", "analyzer"):
            for size in ("", "-mid", "-narrow"):
                for th in B.THEMES:
                    svg = art(name + size, th)
                    self.assertIn(f'<rect x=".5" y=".5" ', svg)
                    self.assertIn(f'stroke="{B.THEMES[th]["line"]}"/>', svg.split("<rect", 2)[1])

    def test_schematics_say_so_on_the_image(self):
        def drawn(name):
            root = B.ET.fromstring(art(name))
            return " ".join("".join(el.itertext()) for el in root.iter() if el.tag.endswith("}text"))
        self.assertIn("schematic", drawn("proteins"))
        self.assertIn("schematic", drawn("music"))
        self.assertIn("icons, not data", drawn("header"))
        self.assertIn("icons, not data", drawn("header-narrow"))
        for name in ("brains", "quantum", "constellation", "analyzer", "divider"):
            self.assertNotIn("schematic", art(name).lower(), name)

    def test_alt_text_states_every_checked_value(self):
        m = model()
        alts = readme_alts((base_build() / "README.md").read_text())
        for where, what, value, field, keys in B.art_checks(m):
            name = keys[0]
            alt = alts[f"{name}-light.svg"]
            for num in re.findall(r"\d[\d,.]*\d|\d", value):
                self.assertIn(num, alt, f"{where}: {what} = {value!r}")

    def test_wide_pictures_use_six_sources_in_order(self):
        text = (base_build() / "README.md").read_text()
        for name in sorted(B.NARROW_ART):
            block = re.search(rf"<picture>\n(<source[^\n]*{name}-narrow-dark[^\n]*\n(?:[^\n]*\n){{4}}<img[^\n]*)\n</picture>",
                              text)
            self.assertIsNotNone(block, name)
            lines = block.group(1).splitlines()
            self.assertEqual([re.search(r'media="([^"]*)"', ln).group(1) for ln in lines[:5]], list(B.MEDIA[:5]))
            self.assertEqual([re.search(r'(?:srcset|src)="assets/([^?]*)', ln).group(1) for ln in lines],
                             [f"{name}-narrow-dark.svg", f"{name}-narrow-light.svg", f"{name}-mid-dark.svg",
                              f"{name}-mid-light.svg", f"{name}-dark.svg", f"{name}-light.svg"])
            self.assertIn('width="100%"', lines[5])
        with self.assertRaises(SystemExit):
            B.check_readme(text.replace('media="(max-width: 600px), ', 'media="(max-width: 900px), ', 1))
        with self.assertRaises(SystemExit):
            B.check_readme(text + '\n<picture><source media="print" srcset="assets/header-dark.svg?v=00000000"></picture>\n')

    def test_each_width_gets_a_twin_drawn_near_its_own_size(self):
        """Which twin a viewport gets, and how much it is scaled in GitHub's README column there."""
        def column(vw):          # GitHub's README column width at a viewport width (Primer layout, approximate)
            if vw < 768:
                return vw - 32
            if vw < 1012:
                return 400 + (vw - 768) * 260 / 243
            return min(580 + (vw - 1012) * 250 / 268, 830)

        def media_ok(cond, vw):
            lo = re.search(r"min-width: (\d+)px", cond)
            hi = re.search(r"max-width: (\d+)px", cond)
            return (not lo or vw >= int(lo.group(1))) and (not hi or vw <= int(hi.group(1)))

        widths = {"narrow": (B.NARROW, B.AN_NARROW), "mid": (B.MID,), "wide": (B.WIDE,)}
        for vw in range(375, 1601):              # from a 375-wide phone (343 column) up
            if any(media_ok(c, vw) for c in B.NARROW_WHEN):
                twin = "narrow"
            elif any(media_ok(c, vw) for c in B.MID_WHEN):
                twin = "mid"
            else:
                twin = "wide"
            for w in widths[twin]:
                scale = column(vw) / w
                self.assertGreaterEqual(scale, 0.85, (vw, twin, w))   # 12-unit text never drawn below about 10 px
                self.assertLessEqual(scale, 1.5, (vw, twin, w))      # no inflated banner beside the cards

    def test_a_viewport_beside_the_sidebar_hands_over_to_the_mid_twin(self):
        def twin(vw):
            def ok(c):
                lo, hi = re.search(r"min-width: (\d+)px", c), re.search(r"max-width: (\d+)px", c)
                return (not lo or vw >= int(lo.group(1))) and (not hi or vw <= int(hi.group(1)))
            return "narrow" if any(map(ok, B.NARROW_WHEN)) else ("mid" if any(map(ok, B.MID_WHEN)) else "wide")
        self.assertEqual([twin(v) for v in (375, 600, 601, 767, 768, 859, 860, 960, 1011, 1199, 1200)],
                         ["narrow", "narrow", "mid", "mid", "narrow", "narrow", "mid", "mid", "mid", "mid", "wide"])

    def test_the_quantum_card_says_its_bars_are_simulated(self):
        q = model()["quantum"]
        for th in B.THEMES:
            drawn = B.drawn_text(art("quantum", th))
            self.assertIn(f"this simulated run {q['run']:.4f}", drawn)
            self.assertIn(f"{q['F'][q['shots']]:.4f}", drawn)
            self.assertIn(f"{q['F'][q['shots']]:.2f} at", drawn)
            # one value, two precisions: four places in the readouts, two on the curve, never three
            self.assertIsNone(re.search(r"\b0\.\d{3}\b", drawn), drawn)

    def test_the_filed_panel_keys_its_hollow_squares(self):
        m = model()
        for th in B.THEMES:
            drawn = B.drawn_text(art("filed", th))
            self.assertEqual("own PR" in drawn, any(x["own"] for x in m["bins"]), th)

    def test_the_phone_constellation_shortens_crowded_labels(self):
        rows = dict(model()["stars"])
        for area, short in B.STAR_LABELS_NARROW.items():
            if area not in rows:
                continue
            for th in B.THEMES:
                narrow, mid = B.drawn_text(art("constellation-narrow", th)), B.drawn_text(art("constellation-mid", th))
                self.assertNotIn(B.STAR_LABELS[area], narrow)
                self.assertIn(f"{short} {len(rows[area])}", narrow)
                self.assertIn(B.STAR_LABELS[area], mid)
                self.assertIn(f"{B.STAR_LABELS[area]} {len(rows[area])}", B.svg_text(art("constellation-narrow", th)))

    def test_the_header_stop_count_is_listed(self):
        checks = (base_build() / "CHECKS.md").read_text()
        k = len(B.HEADER_STOPS)
        self.assertIn(f"| header | stops (desc) | {B.NUMBER_WORDS.get(k, k)} stops | `len(HEADER_STOPS)` |", checks)

    def test_widgets_absent_build_cleanly(self):
        text = (base_build() / "README.md").read_text()
        self.assertNotIn("commit weather", text)
        self.assertNotIn("profile-3d-contrib", text)
        self.assertIn("widgets: not generated yet", (base_build() / "CHECKS.md").read_text())
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty)
        self.assertIsNone(B.read_widgets(empty))


class Widgets(unittest.TestCase):
    def snake(self, theme="light"):
        return (WIDGETS / "assets" / "contrib" / f"snake-{theme}.svg").read_text()

    def three_d(self, theme="light"):
        return (WIDGETS / "profile-3d-contrib" / f"3d-{theme}.svg").read_text()

    def test_snake_patch_is_idempotent_and_finite(self):
        for th in ("light", "dark"):
            raw = self.snake(th)
            self.assertIn("infinite", raw)
            once = B.patch_snake(raw)
            self.assertNotIn("infinite", once)
            self.assertIn(B.MOTION, once)
            self.assertEqual(B.patch_snake(once), once)
            B.check_widget_svg("snake", once)
            with self.assertRaises(SystemExit):
                B.check_widget_svg("snake", raw)

    def test_hostile_widget_files_are_refused(self):
        good = B.patch_snake(self.snake())
        B.check_widget_svg("ok", good)
        B.check_widget_svg("3d", self.three_d())
        B.check_widget_svg("3d", self.three_d("dark"))
        for bad in (good.replace("</svg>", "<script>alert(1)</script></svg>"),
                    good.replace("</svg>", "<foreignObject><div/></foreignObject></svg>"),
                    good.replace("</svg>", '<a href="https://example.com/"><rect/></a></svg>'),
                    good.replace("</svg>", '<rect href="https://example.com/x"/></svg>'),
                    good.replace("</style>", ".c{fill:url(http://example.com/x)}</style>"),
                    good.replace("</style>", "@import 'https://example.com/x.css';</style>"),
                    good.replace("<svg ", '<svg onload="alert(1)" '),
                    self.three_d().replace('repeatCount="1"', 'repeatCount="indefinite"', 1),
                    good + " " * B.WIDGET_MAX):
            with self.assertRaises(SystemExit):
                B.check_widget_svg("bad", bad)
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        shutil.copytree(WIDGETS, root, dirs_exist_ok=True)
        (root / "profile-3d-contrib" / "3d-dark.svg").write_text(self.three_d("dark").replace("</svg>", "<script/></svg>"))
        # a refused widget costs the section, not the run: the build finishes and logs why
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(B.read_widgets(root))
            out = build_with(widgets=root)
        self.addCleanup(shutil.rmtree, out)
        self.assertIn("widgets left out this run", err.getvalue())
        self.assertIn("<script>", err.getvalue())
        text = (out / "README.md").read_text()
        self.assertNotIn("commit weather", text)
        self.assertFalse((out / "profile-3d-contrib").exists())

    def test_light_and_dark_3d_files_must_agree(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        shutil.copytree(WIDGETS, root, dirs_exist_ok=True)
        figs = B.widget_figures(self.three_d())
        (root / "profile-3d-contrib" / "3d-dark.svg").write_text(
            self.three_d("dark").replace(f">{figs[0].split()[-1]}<", ">99999<", 1))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(B.read_widgets(root))

    def test_widget_figures_are_listed(self):
        out = build_with(widgets=WIDGETS)
        self.addCleanup(shutil.rmtree, out)
        checks, text = (out / "CHECKS.md").read_text(), (out / "README.md").read_text()
        self.assertIn("## drawn by an Action, not recomputed", checks)
        figs = B.widget_figures(self.three_d())
        self.assertIn("issues 9", figs)
        for fig in figs:
            self.assertIn(f"| {B.md(fig)} | {B.md(B.CONTRIB_3D_SOURCE)} |", checks)
        self.assertIn("### commit weather", text)
        self.assertIn("the totals in the 3D picture are the calendar's own", text)
        self.assertIn("a picture of the calendar's shape", readme_alts(text)["3d-light.svg"])
        B.check_readme(text)
        for th in ("light", "dark"):          # each theme gets its own file, so the page follows GitHub's theme setting
            data = (out / "profile-3d-contrib" / f"3d-{th}.svg").read_text()
            self.assertEqual(data, self.three_d(th))
            self.assertNotIn("prefers-color-scheme", data)
            v = hashlib.sha1(data.encode()).hexdigest()[:8]
            self.assertIn(f"profile-3d-contrib/3d-{th}.svg?v={v}", text)
        self.assertIn('<source media="(prefers-color-scheme: dark)" srcset="profile-3d-contrib/3d-dark.svg', text)
        written = (out / "assets" / "contrib" / "snake-dark.svg").read_text()
        self.assertEqual(written, B.patch_snake(self.snake("dark")))
        v = hashlib.sha1(written.encode()).hexdigest()[:8]
        self.assertIn(f"assets/contrib/snake-dark.svg?v={v}", text)

    @staticmethod
    def jobs(wf: str) -> dict:
        """The workflow's jobs as {name: text}, split on the two-space job headers under jobs:."""
        body = wf.split("\njobs:\n", 1)[1]
        parts = re.split(r"^  ([a-z][\w-]*):\n", body, flags=re.M)
        return dict(zip(parts[1::2], parts[2::2]))

    def test_workflow_pins_and_permissions(self):
        wf = (ROOT / ".github" / "workflows" / "refresh.yml").read_text()
        uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", wf, re.M)
        self.assertEqual(len(uses), 7)
        for ref, rest in uses:
            self.assertRegex(ref, r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?@[0-9a-f]{40}$")
            self.assertRegex(rest, r"#\s*v\d")
        self.assertRegex(wf, r"(?m)^permissions: \{\}")
        jobs = self.jobs(wf)
        self.assertEqual(sorted(jobs), ["refresh", "widgets"])
        perms = {k: re.findall(r"^    permissions:\n((?:      .*\n)+)", v, re.M) for k, v in jobs.items()}
        self.assertEqual([ln.split("#")[0].strip() for ln in perms["widgets"][0].splitlines()], ["contents: read"])
        self.assertEqual([ln.split("#")[0].strip() for ln in perms["refresh"][0].splitlines()], ["contents: write"])
        # the third-party Actions run only in the read-only job, and no checkout leaves a token behind
        third = [r for r, _ in uses if not r.startswith("actions/")]
        self.assertEqual(len(third), 2)
        for ref in third:
            self.assertIn(ref, jobs["widgets"])
            self.assertNotIn(ref, jobs["refresh"])
        self.assertEqual(wf.count("actions/checkout@"), wf.count("persist-credentials: false"))
        self.assertIn("needs: widgets", jobs["refresh"])
        self.assertIn("!cancelled()", jobs["refresh"])
        commit = jobs["refresh"].split("- name: Commit if changed", 1)[1]
        self.assertIn("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}", commit)
        self.assertIn("::add-mask::", commit)
        # only the four widget files build.py checked are ever staged: no other file the third-party Actions wrote
        self.assertIn("git add -- README.md CHECKS.md data assets ':!assets/contrib'", commit)
        staged = re.search(r'widgets="([^"]+)"', commit).group(1).split()
        self.assertEqual(sorted(staged), sorted(list(B.SNAKE) + ["profile-3d-contrib/3d-light.svg", "profile-3d-contrib/3d-dark.svg"]))
        self.assertNotRegex(commit, r"git add[^\n]*(assets/contrib/?\s|profile-3d-contrib/?\s|profile-3d-contrib$)")
        uploaded = jobs["widgets"].split("path: |", 1)[1].split("if-no-files-found", 1)[0].split("\n")[1:]
        self.assertEqual(sorted(ln.split("#")[0].strip() for ln in uploaded if ln.split("#")[0].strip()), sorted(staged))
        self.assertEqual(set(re.findall(r"secrets\.(\w+)", wf)), {"GITHUB_TOKEN", "PROFILE_EXCLUDE"})
        self.assertIn('git config user.name "github-actions[bot]"', wf)
        self.assertIn("41898282+github-actions[bot]@users.noreply.github.com", wf)
        self.assertIn('[ -n "$PROFILE_EXCLUDE" ] ||', wf)
        self.assertNotRegex(wf, r"echo[^\n]*\$\{?\{?\s*(secrets|GITHUB_TOKEN|PROFILE_EXCLUDE)")
        self.assertNotRegex(wf, r"set -x|ACTIONS_STEP_DEBUG")
        outputs = wf.split("outputs: |", 1)[1].split("- name:", 1)[0].split()
        self.assertEqual([o.split("?")[0] for o in outputs], list(B.SNAKE))
        self.assertIn("SETTING_JSON: .github/contrib3d.json", wf)
        self.assertIn(B.CONTRIB_3D_SOURCE.rsplit(" ", 1)[1], wf)   # the version CHECKS.md names is the pinned one
        cfg = json.loads((ROOT / ".github" / "contrib3d.json").read_text())
        self.assertIsInstance(cfg, list)             # one file per theme: the Action writes one per entry
        self.assertEqual(tuple(f"profile-3d-contrib/{c['fileName']}" for c in cfg), B.CONTRIB_3D)
        for c, th in zip(cfg, ("light", "dark")):
            self.assertNotIn("/", c["fileName"])
            self.assertNotIn("darkMode", c)          # a darkMode entry would bring back the OS-following media query
            self.assertIs(c["growingAnimation"], True)
            self.assertEqual(c["backgroundColor"], B.THEMES[th]["bg"])

    def surfaces(self) -> str:
        """Everything a reader can see: README, CHECKS, alt text and the text inside every generated picture."""
        out = build_with(widgets=WIDGETS)
        self.addCleanup(shutil.rmtree, out)
        surfaces = [(out / "README.md").read_text(), (out / "CHECKS.md").read_text()]
        surfaces += list(readme_alts(surfaces[0]).values())
        for f in sorted((out / "assets").glob("*.svg")):
            root = B.ET.fromstring(f.read_text())
            surfaces.append(" ".join("".join(el.itertext()) for el in root.iter()
                                     if el.tag.rsplit("}", 1)[-1] in ("text", "desc", "title")))
        return "\n".join(surfaces).lower()

    def test_nothing_private_on_any_surface(self):
        hay = self.surfaces()
        for word in ("@", "linkedin", "calendly", "medium.com", "new delhi", "voice", "assistant", "generated by"):
            self.assertNotIn(word, hay, word)
        # product names that must not appear, kept as sha256 digests so this public file does not spell them out
        for k, digest in TOOL_DIGESTS:
            hits = [i for i in range(len(hay) - k + 1) if hashlib.sha256(hay[i:i + k].encode()).hexdigest() == digest]
            self.assertFalse(hits, f"a {k}-character excluded word appears")

    def test_no_private_name_from_the_environment(self):
        """Private names come from PRIVATE_ENV only (a local variable or a secret); the public tree never lists them."""
        private = [w.strip().lower() for w in os.environ.get(PRIVATE_ENV, "").split(",") if w.strip()]
        if not private:
            self.skipTest(f"{PRIVATE_ENV} is unset")
        hay = self.surfaces()
        for i, word in enumerate(private):
            # assertFalse, not assertNotIn: a failure must not print the page, or the name, into a log
            self.assertFalse(word in hay, f"excluded name {i + 1} of {len(private)} from {PRIVATE_ENV} appears")

    def test_links_go_only_to_github_and_his_site(self):
        text = (base_build() / "README.md").read_text()
        for url in re.findall(r"https?://[^\s)\"<>]+", text):
            self.assertTrue(url.startswith("https://github.com/") or url == "https://shauryasingh.com", url)
        self.assertIn(B.SITE, text)
        with self.assertRaises(SystemExit):
            B.check_readme(text + "\n[site](https://example.com)\n")

    def test_two_builds_with_widgets_give_the_same_bytes(self):
        a, b = build_with(widgets=WIDGETS), build_with(widgets=WIDGETS)
        self.addCleanup(shutil.rmtree, a)
        self.addCleanup(shutil.rmtree, b)
        self.assertEqual(RenderGuards.snapshot(a), RenderGuards.snapshot(b))
        again = build_with(widgets=a)           # patching already-patched files changes nothing
        self.addCleanup(shutil.rmtree, again)
        self.assertEqual(RenderGuards.snapshot(a), RenderGuards.snapshot(again))


class StatTiles(unittest.TestCase):
    """The side quest's four numbers, drawn as tiles at three widths."""

    def tiles(self, svg):
        return [(float(x), float(y)) for x, y in re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="[\d.]+" '
                                                          r'height="95" rx="6"', svg)]

    def test_one_row_wide_two_by_two_on_the_twins(self):
        for size, width, rows in (("stats", 830, 1), ("stats-mid", 560, 2), ("stats-narrow", 380, 2)):
            for th in B.THEMES:
                svg = art(size, th)
                self.assertIn(f'width="{width}"', svg.split(">", 1)[0])
                tiles = self.tiles(svg)
                self.assertEqual(len(tiles), 4, size)
                self.assertEqual(len({y for _, y in tiles}), rows, size)
                self.assertIn(f'stroke="{B.THEMES[th]["line"]}"', svg)

    def test_every_number_is_drawn_from_the_data(self):
        st = B.read(FXDATA / "stats.json")
        o, iss = st["outcomes"], st["issues"]
        fixed = o["fixed_by_merged_pr_from_someone_else"] + o["fixed_by_his_own_merged_pr"]
        lag = model()["lag"]
        for size in ("stats", "stats-mid", "stats-narrow"):
            for th in B.THEMES:
                svg = art(size, th)
                drawn = B.drawn_text(svg)
                for want in (f"{iss['total']}issues filed", f"since {iss['first_created_at'][:10]}",
                             f"{iss['distinct_repos']} repos", f"{fixed}fixed",
                             f"{o['fixed_by_merged_pr_from_someone_else']} by others, {o['fixed_by_his_own_merged_pr']} by me",
                             f"{lag['median']}h median", f"{st['prs']['upstream']}PRs upstream",
                             f"{st['queries']['prs_merged']} merged, {st['queries']['prs_open']} open"):
                    self.assertIn(want, drawn, (size, th))
                self.assertIn(f'<tspan class="b a">{fixed}</tspan>', svg)   # accent means fixed, as everywhere

    def test_nothing_fixed_yet_still_draws(self):
        m = dict(model())
        m.update(fixed=0, lag=dict(model()["lag"], n=0, median=None),
                 outcome=[(k, 0 if k in ("others", "own") else c) for k, c in model()["outcome"]])
        drawn = B.drawn_text(B.art_stats(m, B.THEMES["light"], "narrow"))
        self.assertIn("none yet", drawn)
        self.assertIn("no fix by others yet", drawn)
        self.assertIn("—h median", drawn)

    def test_a_line_too_long_for_its_tile_stops_the_build(self):
        long = [("1", "x", "", ["y" * 30, "z"])] * 4
        with mock.patch.object(B, "stat_tiles", lambda m: long), self.assertRaises(SystemExit):
            B.art_stats(model(), B.THEMES["light"], "narrow")
        B.art_stats(model(), B.THEMES["light"], "wide")      # 30 characters fit a wide tile


if __name__ == "__main__":
    unittest.main(verbosity=2)
