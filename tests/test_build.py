"""Offline tests: the network layer against a local mock of the GitHub API, then the stats step and
the renderer. No real API call is made and no token is needed.

    python3 -m unittest discover -s tests -v

tests/fixtures/search.json holds recorded search results; tests/fixtures/rest.json is constructed in
the documented REST shapes (timelines, commit lookups, star counts) and says so in its _note.

The suite never reads the live data/ directory, so a refresh that changes data/ cannot turn it red.
tests/fixtures/data/ is a frozen data directory: the four hand-written inputs (areas, notes, probe,
projects) plus the five files a fetch writes from the two fixtures above. Every fixture-driven test
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
import shutil
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
HAND_WRITTEN = ("areas.json", "notes.json", "probe.json", "projects.json")


def copy_fixture_data(dest, only=None):
    """The frozen data directory into dest. projects.json is written from build.py's own TOOLS list (every package
    unreleased) rather than frozen, so adding or removing a package there needs no fixture edit."""
    for f in FXDATA.iterdir():
        if only is None or f.name in only:
            shutil.copy(f, dest / f.name)
    if only is None or "projects.json" in only:
        names = [n for _, items in B.TOOLS for n, _ in items]
        (dest / "projects.json").write_text(json.dumps({n: {"status": "unreleased"} for n in names}))
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
            self.assertEqual(sorted(f.name for f in data.iterdir()), ["areas.json", "notes.json", "probe.json", "projects.json"])

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
            B.render(ROOT / "data", out)
        for f in ["README.md", "CHECKS.md"] + [f"assets/{p}-{t}.svg" for p in B.PANELS for t in B.THEMES]:
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
        self.assertIn(f"since {since}:", text)       # a year, because "sept 23" reads as 2023
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
                self.assertIn(f"**{n}**", text, n)
                self.assertNotIn(self.url(n), text, n)
        self.assertEqual("none is public yet, so no links" in text, not out)
        self.assertEqual("linked names are out" in text, 0 < len(out) < len(projects))
        self.assertEqual("its first public release is pending" in text, "scoreprobe" not in out)

    def test_an_unreleased_package_is_bold_and_never_linked(self):
        text = self.render()
        for n in self.NAMES:
            self.assertIn(f"**{n}**", text, n)
            self.assertNotIn(self.url(n), text, n)
        self.assertIn("none is public yet, so no links", text)
        self.assertIn("its first public release is pending", text)

    def test_a_released_package_is_linked_everywhere_it_is_named(self):
        sample = self.SAMPLE
        text = self.render(released=(sample,))
        self.assertEqual(text.count(f"[**{sample}**]({self.url(sample)})"), self.SAMPLE_LINKS)   # field guide + tools
        for n in self.NAMES:
            if n != sample:
                self.assertNotIn(self.url(n), text, n)
        self.assertIn("linked names are out", text)
        self.assertNotIn("none is public yet", text)

    def test_with_every_package_released_the_page_says_so_and_scoreprobe_links_in_the_method(self):
        text = self.render(released=self.NAMES)
        for n in self.NAMES:
            self.assertIn(f"[**{n}**]({self.url(n)})", text, n)
        self.assertNotIn("none is public yet", text)
        self.assertNotIn("linked names are out", text)
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
        for needle in ("README side quest", f"{st['issues']['total']} issues in",
                       f"in {st['issues']['distinct_repos']} repositories",
                       f"since {st['issues']['first_created_at'][:10]}:",
                       f"{o['fixed_by_merged_pr_from_someone_else'] + o['fixed_by_his_own_merged_pr']} fixed by a merged",
                       f"{o['fixed_by_merged_pr_from_someone_else']} of those by other people",
                       f"and {o['fixed_by_his_own_merged_pr']} by me",
                       f"{words[len(B.PANELS) - 1]} more panels",
                       f"README defect table | fixes in the table, lead sentence | {words[rows]} of the fixes",
                       f"{words[len(B.read(FXDATA / 'probe.json')['source'])]}-line grader"):
            self.assertIn(needle, checks)

    def test_no_voice_headline_and_no_banned_words(self):
        text = (base_build() / "README.md").read_text().lower()
        for w in ("voice", "passionate", "leverag", "cutting-edge", "enthusiast", "10x", "rockstar", "co-authored-by"):
            self.assertNotIn(w, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
