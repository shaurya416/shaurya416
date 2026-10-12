#!/usr/bin/env python3
"""Regenerate the profile README and its panels.

    python3 build.py                 render data/ into assets/*.svg, README.md and CHECKS.md (no network)
    python3 build.py fetch           read the GitHub API into data/, then run the stats step (needs GITHUB_TOKEN)
    python3 build.py stats           rebuild data/stats.json from the other files in data/ (no network)
    python3 build.py capture-probe --scoreprobe-src PATH [--status v0.1.0] [--url URL]
                                     re-run scoreprobe on the grader its panel shows; rewrites data/probe.json
    python3 build.py capture-trigalign --trigalign-src PATH
                                     re-run trigalign's README example on its CC0 excerpt; rewrites
                                     data/trigalign.json (the brains card)
    python3 build.py --out DIR       render somewhere else (used to prove two builds give the same bytes)
    python3 build.py --widgets DIR   where the Action-drawn files are read from (default: this directory):
                                     assets/contrib/snake-{light,dark}.svg and profile-3d-contrib/3d-{light,dark}.svg.
                                     Each is checked, the snake is made to play once, and the result is
                                     written under --out. Absent or refused files leave the commit-weather
                                     section out (logged, never fatal).

    PROFILE_EXCLUDE="-org:a -user:b" is appended to every author query and its owners are dropped from
    every row (never printed); empty or unset means no exclusion.
    PROFILE_FULL=1 makes fetch re-trace every closed issue and re-read every star count (the monthly
    heartbeat does the same); PROFILE_ALLOW_SHRINK=1 lets a real drop of more than half through.

data/
    issues.json  fetch: one row per issue filed. A closed issue carries merged_prs, the merged pull
                 requests in its own repository that reference it; an open issue is not traced (null)
    prs.json     fetch: one row per pull request opened
    stars.json   fetch: stargazer count per repository; a new repository is added when it first appears
                 and every count is re-read on the monthly heartbeat
    fetch.json   fetch: as_of (the last fetch that changed anything), checked (heartbeat date), the
                 search total_count values, the account
    areas.json   hand-written: repository -> area
    notes.json   hand-written: one line per issue in the "one defect" table
    probe.json   capture-probe: a captured scoreprobe run
    trigalign.json  capture-trigalign: a captured trigalign run (CC0 excerpt) drawn on the brains card
    projects.json  hand-written: which of the packages in TOOLS are public, and their repository url
    stats.json   stats: every number the page shows, derived from the files above

Standard library only, Python 3.12 or later (3.11 cannot parse this file). Requests are serial and paced under GitHub's published
limits. Rendering reads no clock, no randomness and no network, so the same data gives the same bytes.
The illustrations are drawn from data/ or from formulas in this file (a seeded splitmix64 draw is
one of them). A text node that would leave its card or touch another mark fails the build, every
animation stops by itself within 11 s and honours reduced motion, every total is checked against its
parts, every string that did not come from this file is escaped, and the output is checked against an
element allowlist before anything is written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import hashlib
import inspect
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html import escape
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
USER = "shaurya416"

# PROFILE_EXCLUDE (environment; a repository secret in the workflow) is appended verbatim to every
# author query, e.g. "-org:name -user:name". The owners it names are also dropped client-side from every
# returned row. Its value is scrubbed from every log line and error. Empty or unset: no exclusion.
def exclusion() -> str:
    return os.environ.get("PROFILE_EXCLUDE", "").strip()


def excluded_owners() -> tuple[str, ...]:
    return tuple(m.group(1).lower() for t in exclusion().split()
                 if (m := re.fullmatch(r"-(?:org|user):(\S+)", t, re.I)))


def scrub(text: object) -> str:
    """Anything printed or raised passes through here, so no part of the exclusion reaches a log."""
    out = str(text)
    raw = os.environ.get("PROFILE_EXCLUDE", "")
    parts = {raw, raw.strip(), *exclusion().split(), *excluded_owners()} - {""}
    for part in sorted(parts, key=len, reverse=True):
        out = re.sub(re.escape(part), "[excluded]", out, flags=re.I)
    return out


def log(msg: str) -> None:
    print(scrub(msg), file=sys.stderr)


def must(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(scrub(f"input check failed: {msg}"))


def ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def day_of(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


def hours_between(a: str, b: str) -> float:
    return round((ts(b) - ts(a)).total_seconds() / 3600, 1)


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_opt(path: Path, default):
    return read(path) if path.exists() else default


def dump(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def write_if_changed(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == text.encode("utf-8"):
        return False
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


# ============================================================ fetch: network ====
API_VERSION = "2022-11-28"
JSON_TYPE = "application/vnd.github+json"
TIMELINE_TYPE = "application/vnd.github.mockingbird-preview+json"
SEARCH_GAP = 2.5        # seconds between search calls: 24 a minute against the 30-a-minute ceiling
CORE_GAP = 1.0          # seconds between other calls
MAX_WAIT = 900          # never sleep longer than this inside one run; give up instead
RETRIES = 5
PER_PAGE = 100
SEARCH_CAP = 1000       # search returns at most the first 1000 results of a query; larger ones are split
MAX_PAGES = 30          # bound on Link-header pagination of one timeline
STAR_BATCH = 10         # repo: qualifiers per repository search
HEARTBEAT_DAYS = 30     # fetch.json "checked" moves at least this often, so a quiet repository still gets
                        # a commit well inside GitHub's 60-day rule for disabling idle scheduled workflows
CLOSE_SLACK = 60        # seconds: merge and auto-close are separate writes, so a fix may trail the close
GITHUB_START = dt.date(2008, 1, 1)
COUNT_QUERIES = (       # key in fetch.json counts -> qualifiers after author:USER is:public
    ("issues_total", "is:issue"),
    ("issues_open", "is:issue is:open"),
    ("issues_closed", "is:issue is:closed"),
    ("prs_total", "is:pr"),
    ("prs_merged", "is:pr is:merged"),
    ("prs_open", "is:pr is:open"),
    ("prs_closed_unmerged", "is:pr is:closed is:unmerged"),
)


class ApiError(RuntimeError):
    def __init__(self, status: int, where: str, message: str):
        super().__init__(scrub(f"{status} {where}: {message}")[:300])
        self.status = status


class RateLimited(ApiError):
    pass


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only within the API host, so the Authorization header goes nowhere else."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            raise ApiError(code, "redirect", "refused a redirect to another host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _message(raw: bytes) -> str:
    try:
        return str((json.loads(raw.decode("utf-8")) or {}).get("message", ""))
    except (ValueError, AttributeError, UnicodeDecodeError):
        return ""


def _next_link(link: str) -> str:
    for part in link.split(","):
        hit = re.match(r'\s*<([^>]+)>\s*;\s*rel="next"', part)
        if hit:
            return hit.group(1)
    return ""


class Client:
    """Serial GitHub REST client. The token sits in one request header and is never printed.

    403/429 are handled in the documented order: retry-after, then x-ratelimit-reset when
    x-ratelimit-remaining is 0, then a doubling wait from one minute when the message names a rate
    limit. Any other 403 is raised at once. 5xx and network errors back off 2, 4, 8 s (cap 60).
    """

    def __init__(self, token: str, api: str | None = None, *, sleep=time.sleep, clock=time.monotonic,
                 wall=time.time, retries: int = RETRIES, timeout: float = 30, proxies: dict | None = None):
        if not token:
            raise SystemExit("GITHUB_TOKEN is not set (the token Actions provides is enough)")
        self._auth = "Bearer " + token
        self.api = (api or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        self.sleep, self.clock, self.wall = sleep, clock, wall
        self.retries, self.timeout = retries, timeout
        handlers: list = [_SameHostRedirect()]
        if proxies is not None:
            handlers.append(urllib.request.ProxyHandler(proxies))
        self._open = urllib.request.build_opener(*handlers).open
        self._last: dict[str, float] = {}
        self.calls = {"search": 0, "core": 0}
        self.incomplete = 0

    def __repr__(self) -> str:
        return f"Client({self.api!r})"

    def _pace(self, kind: str) -> None:
        wait = self._last.get(kind, -math.inf) + (SEARCH_GAP if kind == "search" else CORE_GAP) - self.clock()
        if wait > 0:
            self.sleep(wait)
        self._last[kind] = self.clock()

    def _limit_wait(self, h, message: str, attempt: int) -> float | None:
        if h.get("retry-after"):
            return float(h["retry-after"]) + 1
        if h.get("x-ratelimit-remaining") == "0" and h.get("x-ratelimit-reset"):
            return max(float(h["x-ratelimit-reset"]) - self.wall(), 0) + 1
        if "rate limit" in message.lower():
            return 60.0 * 2 ** attempt
        return None

    def request(self, url: str, kind: str = "core", accept: str = JSON_TYPE):
        if not url.startswith(self.api + "/"):
            raise ApiError(0, "-", "refused a URL outside the API host")
        where = urllib.parse.urlsplit(url).path
        headers = {"Accept": accept, "X-GitHub-Api-Version": API_VERSION,
                   "User-Agent": f"{USER}-profile-build", "Authorization": self._auth}
        for attempt in range(self.retries + 1):
            self._pace(kind)
            self.calls[kind] += 1
            try:
                with self._open(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                    raw, h = r.read(), r.headers
            except urllib.error.HTTPError as e:
                h = e.headers
                try:
                    raw = e.read()
                except OSError:
                    raw = b""
                message = _message(raw)
                if e.code in (403, 429):
                    wait = self._limit_wait(h, message, attempt)
                    if wait is None:
                        raise ApiError(e.code, where, message or "forbidden") from None
                    if attempt == self.retries or wait > MAX_WAIT:
                        raise RateLimited(e.code, where, f"rate limited; gave up after {attempt + 1} tries") from None
                    self.sleep(wait)
                    continue
                if e.code >= 500 and attempt < self.retries:
                    self.sleep(min(2 * 2 ** attempt, 60))
                    continue
                raise ApiError(e.code, where, message) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == self.retries:
                    raise ApiError(0, where, f"network error ({type(e).__name__})") from None
                self.sleep(min(2 * 2 ** attempt, 60))
                continue
            remaining, reset = h.get("x-ratelimit-remaining"), h.get("x-ratelimit-reset")
            if remaining is not None and reset and int(remaining) <= 1:
                wait = max(float(reset) - self.wall(), 0) + 1
                if wait > MAX_WAIT:
                    raise RateLimited(429, where, f"limit spent; it resets in {wait:.0f} s")
                self.sleep(wait)
            try:
                return (json.loads(raw.decode("utf-8")) if raw else None), h
            except ValueError:
                raise ApiError(0, where, "response is not JSON") from None
        raise AssertionError("unreachable")

    def get(self, path: str, params: dict | None = None, kind: str = "core", accept: str = JSON_TYPE):
        url = self.api + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return self.request(url, kind, accept)[0]

    def pages(self, path: str, params: dict | None = None, accept: str = JSON_TYPE) -> list:
        """A list endpoint, following Link rel="next" exactly as the API gives it."""
        url = self.api + path + ("?" + urllib.parse.urlencode(params) if params else "")
        out: list = []
        for _ in range(MAX_PAGES):
            body, h = self.request(url, "core", accept)
            out += body or []
            url = _next_link(h.get("link") or "")
            if not url:
                return out
        raise ApiError(0, path, f"more than {MAX_PAGES} pages")


def search(client: Client, q: str, today: dt.date, lo: dt.date | None = None, hi: dt.date | None = None) -> list:
    """Every issue/PR search result for q, 100 a page; a query over the 1000 cap is split by date."""
    qq = q if lo is None else f"{q} created:{lo}..{hi}"

    def page(p: int) -> dict:
        body = client.get("/search/issues", {"q": qq, "per_page": PER_PAGE, "page": p,
                                             "sort": "created", "order": "asc"}, "search")
        if body.get("incomplete_results"):
            client.incomplete += 1
        return body

    first = page(1)
    total = int(first["total_count"])
    if total <= SEARCH_CAP:
        items = list(first["items"])
        for p in range(2, math.ceil(total / PER_PAGE) + 1):
            items += page(p)["items"]
        return items
    lo, hi = lo or GITHUB_START, hi or today
    if lo >= hi:
        raise ApiError(0, "/search/issues", f"more than {SEARCH_CAP} results created on one day")
    mid = lo + dt.timedelta(days=(hi - lo).days // 2)
    return search(client, q, today, lo, mid) + search(client, q, today, mid + dt.timedelta(days=1), hi)


def search_count(client: Client, q: str) -> int:
    body = client.get("/search/issues", {"q": q, "per_page": 1}, "search")
    if body.get("incomplete_results"):
        client.incomplete += 1
    return int(body["total_count"])


SCOPE = "is:public"     # every author query: public repositories only, whatever the token could see


def author_query(rest: str) -> str:
    ex = exclusion()
    return f"author:{USER} {SCOPE} {rest}" + (f" {ex}" if ex else "")


def repo_of(item: dict) -> str:
    owner, name = item["repository_url"].rstrip("/").split("/")[-2:]
    return f"{owner}/{name}"


def kept(item: dict) -> bool:
    """Second line of defence behind the PROFILE_EXCLUDE qualifiers, and a check that the row is his."""
    return (repo_of(item).split("/")[0].lower() not in excluded_owners()
            and ((item.get("user") or {}).get("login") or "").lower() == USER.lower())


def issue_row(it: dict) -> dict:
    repo = repo_of(it)
    return {"repo": repo, "owner": repo.split("/")[0], "number": it["number"], "title": it["title"],
            "state": it["state"], "state_reason": it.get("state_reason"), "created_at": it["created_at"],
            "closed_at": it.get("closed_at"), "comments": it.get("comments"), "url": it["html_url"],
            "merged_prs": None}


def pr_row(it: dict) -> dict:
    merged = (it.get("pull_request") or {}).get("merged_at")
    state = "merged" if merged else ("open" if it["state"] == "open" else "closed_unmerged")
    return {"repo": repo_of(it), "number": it["number"], "title": it["title"], "state": state,
            "draft": it.get("draft"), "created_at": it["created_at"], "closed_at": it.get("closed_at"),
            "merged_at": merged, "comments": it.get("comments"), "url": it["html_url"]}


def references(repo: str, n: int):
    return re.compile(rf"(?<![\w/#.-])#{n}(?!\d)|{re.escape(repo)}(?:#|/issues/){n}(?!\d)", re.I)


def trace(client: Client, row: dict, today: dt.date) -> tuple[list, str]:
    """Merged pull requests in the issue's repository that reference it, and how they were found.

    The timeline gives cross-references whose source is a pull request, and the closing commit of a
    `closed` event, resolved to its pull request. When the timeline cannot be read (404/410), a search
    for merged pull requests mentioning the number stands in, kept only if title or body cites it.
    """
    owner, name = row["repo"].split("/")
    n = row["number"]
    found: dict[int, dict] = {}

    def same(repo: str) -> bool:
        return repo.lower() == row["repo"].lower()

    def add(num: int, login: str, merged_at: str) -> None:
        if num not in found:
            found[num] = {"pr": num, "author": login, "merged_at": merged_at,
                          "hours": hours_between(row["created_at"], merged_at)}

    try:
        events = client.pages(f"/repos/{owner}/{name}/issues/{n}/timeline", {"per_page": PER_PAGE}, TIMELINE_TYPE)
    except ApiError as e:
        if e.status not in (404, 410):
            raise
        events = None
    if events is not None:
        shas = set()
        for ev in events:
            if ev.get("event") == "cross-referenced":
                src = (ev.get("source") or {}).get("issue") or {}
                merged = (src.get("pull_request") or {}).get("merged_at")
                if merged and src.get("repository_url") and same(repo_of(src)):
                    add(src["number"], (src.get("user") or {}).get("login", ""), merged)
            elif ev.get("event") == "closed" and ev.get("commit_id"):
                shas.add(ev["commit_id"])
        for sha in sorted(shas):
            try:
                pulls = client.get(f"/repos/{owner}/{name}/commits/{sha}/pulls")
            except ApiError as e:
                if e.status not in (404, 409, 422):
                    raise
                pulls = []
            for p in pulls or []:
                base = ((p.get("base") or {}).get("repo") or {}).get("full_name", "")
                if p.get("merged_at") and same(base):
                    add(p["number"], (p.get("user") or {}).get("login", ""), p["merged_at"])
        how = "timeline"
    else:
        cites = references(row["repo"], n)
        for it in search(client, f"repo:{row['repo']} is:pr is:merged {n}", today):
            merged = (it.get("pull_request") or {}).get("merged_at")
            if merged and same(repo_of(it)) and cites.search(f"{it.get('title') or ''}\n{it.get('body') or ''}"):
                add(it["number"], (it.get("user") or {}).get("login", ""), merged)
        how = "search"
    return sorted(found.values(), key=lambda p: (p["merged_at"], p["pr"])), how


def read_stars(client: Client, repos: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}

    def batch(rs: list[str]) -> None:
        try:
            body = client.get("/search/repositories", {"q": " ".join(f"repo:{r}" for r in rs),
                                                       "per_page": PER_PAGE}, "search")
        except ApiError as e:
            if e.status != 422:
                raise
            if len(rs) > 1:          # one renamed or deleted repository fails the whole query
                for r in rs:
                    batch([r])
            return
        want = {r.lower(): r for r in rs}
        for it in body.get("items") or []:
            r = want.get(str(it.get("full_name", "")).lower())
            if r is not None:
                out[r] = int(it["stargazers_count"])

    for i in range(0, len(repos), STAR_BATCH):
        batch(repos[i:i + STAR_BATCH])
    return out


def fetch(data: Path, client: Client, now: dt.datetime) -> dict:
    """Read everything, check it, and only then write. Returns the summary that is logged."""
    today = now.astimezone(dt.timezone.utc).date()
    old_issues = read_opt(data / "issues.json", [])
    old_prs = read_opt(data / "prs.json", [])
    old_stars = read_opt(data / "stars.json", {"read_at": None, "stars": {}})
    old_meta = read_opt(data / "fetch.json", None)
    due = (old_meta is None or bool(os.environ.get("PROFILE_FULL"))
           or (today - dt.date.fromisoformat(old_meta["checked"])).days >= HEARTBEAT_DAYS)

    counts = {key: search_count(client, author_query(rest)) for key, rest in COUNT_QUERIES}
    raw_issues = search(client, author_query("is:issue"), today)
    raw_prs = search(client, author_query("is:pr"), today)
    if client.incomplete:
        raise SystemExit(f"fetch: {client.incomplete} search page(s) came back incomplete; nothing written")
    issues, prs, ids, dropped = {}, {}, set(), 0
    for it in raw_issues:
        if "pull_request" in it or not kept(it):
            dropped += 1
            continue
        issues[it["html_url"]] = issue_row(it)
        ids.add((it.get("user") or {}).get("id"))
    for it in raw_prs:
        if not kept(it):
            dropped += 1
            continue
        prs[it["html_url"]] = pr_row(it)
        ids.add((it.get("user") or {}).get("id"))
    issues = sorted(issues.values(), key=lambda r: (r["created_at"], r["url"]), reverse=True)
    prs = sorted(prs.values(), key=lambda r: (r["created_at"], r["url"]), reverse=True)
    rows = {"issues_total": len(issues), "issues_open": sum(r["state"] == "open" for r in issues),
            "issues_closed": sum(r["state"] == "closed" for r in issues), "prs_total": len(prs),
            "prs_merged": sum(r["state"] == "merged" for r in prs), "prs_open": sum(r["state"] == "open" for r in prs),
            "prs_closed_unmerged": sum(r["state"] == "closed_unmerged" for r in prs)}
    off = [f"{k} {counts[k]} vs {rows[k]} rows" for k in rows if rows[k] != counts[k]]
    if off:
        raise SystemExit("fetch: search total_count and the rows disagree (" + "; ".join(off) + "); nothing written")
    must(len(ids) == 1 and None not in ids, "rows carry more than one account id")
    for key, was, now_n in (("issues", len(old_issues), len(issues)), ("prs", len(old_prs), len(prs))):
        if was >= 10 and now_n < was / 2 and not os.environ.get("PROFILE_ALLOW_SHRINK"):
            raise SystemExit(f"fetch: {key} fell from {was} to {now_n}; refusing to overwrite "
                             "(set PROFILE_ALLOW_SHRINK=1 if that is real)")

    previous = {r["url"]: r for r in old_issues}
    traced = {"timeline": 0, "search": 0, "kept": 0}
    for row in issues:
        if row["state"] != "closed":
            continue
        prev = previous.get(row["url"]) or {}
        known = prev.get("merged_prs") if prev.get("closed_at") == row["closed_at"] else None
        if known is not None and not due:
            row["merged_prs"] = known
            traced["kept"] += 1
            continue
        found, how = trace(client, row, today)
        traced[how] += 1
        if known is not None and sorted(p["pr"] for p in found) != sorted(p["pr"] for p in known):
            log(f"trace: {row['repo']}#{row['number']} via {how}: found {sorted(p['pr'] for p in found)}, "
                f"kept from before {sorted(p['pr'] for p in known)}; both are kept")
        merged = {p["pr"]: p for p in known or []}
        for p in found:
            merged.setdefault(p["pr"], p)
        row["merged_prs"] = sorted(merged.values(), key=lambda p: (p["merged_at"], p["pr"]))

    repos = sorted({r["repo"] for r in issues}, key=lambda r: (r.lower(), r))
    have = old_stars.get("stars") or {}
    fresh = read_stars(client, repos if due else [r for r in repos if r not in have])
    stars = {r: fresh.get(r, have.get(r)) for r in repos if r in fresh or r in have}
    stars_doc = {"read_at": today.isoformat() if due or not old_stars.get("read_at") else old_stars["read_at"],
                 "stars": stars}
    account = {"login": USER, "user_id": ids.pop()}
    old = old_meta or {}
    excluded = bool(exclusion())
    changed = (issues != old_issues or prs != old_prs or stars != have or counts != old.get("counts")
               or account != old.get("account") or excluded != old.get("exclusion_applied"))
    meta = {"as_of": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ") if changed or not old else old["as_of"],
            "checked": today.isoformat() if changed or due else old["checked"],
            "account": account, "exclusion_applied": excluded, "counts": counts}
    st = derive_stats(issues, prs, stars_doc, read(data / "areas.json"), meta)   # checks before any write
    written = [name for name, obj in (("issues.json", issues), ("prs.json", prs), ("stars.json", stars_doc),
                                      ("fetch.json", meta), ("stats.json", st))
               if write_if_changed(data / name, dump(obj))]
    summary = {"issues": len(issues), "prs": len(prs), "closed": rows["issues_closed"], "dropped": dropped,
               "traced": traced, "stars_read": len(fresh), "stars_missing": [r for r in repos if r not in stars],
               "calls": dict(client.calls), "changed": changed, "heartbeat": due, "written": written}
    log("fetch: " + " ".join(f"{k}={v}" for k, v in summary.items() if k != "stars_missing"))
    for r in summary["stars_missing"]:
        log(f"fetch: no star count for {r} (renamed, deleted or private)")
    return summary


# ===================================================================== stats ====
OTHER = "Other"
# A repository missing from areas.json gets the first area whose pattern matches its owner/name, then
# the first that matches the titles of his issues there, then OTHER. It is listed in stats.json
# (areas_by_rule) and printed, so it can be assigned by hand.
AREA_RULES = (
    ("Speech & audio", r"speech|audio|(?<![a-z])(asr|wer|tts|pesq|stoi)(?![a-z])|diariz|transcri|whisper"),
    ("Autograders & education", r"grader|grading|autograd|classroom|course|(?<![a-z])edx(?![a-z])"),
    ("RL post-training & reward functions", r"(?<![a-z])(rl|rlhf|grpo|ppo|dpo)(?![a-z])|reward|post-?train|-r1(?![0-9])"),
    ("Agent & tool-use benchmarks", r"agent|tool[-_ ]?(use|call)|swe-?bench|web-?arena|browser|osworld"),
    ("Judge, RAG & hallucination scoring", r"judge|(?<![a-z])rag(?![a-z])|halluc|faithful|factual|grounded"),
    ("Code & math answer checking", r"humaneval|mbpp|(?<![a-z])(code|coder|math|sql)(?![a-z])|pass@k"),
    ("Fairness, calibration & uncertainty", r"fairness|(?<![a-z])bias(?![a-z])|calibrat|conformal|uncertain"),
    ("Forecasting, time series & anomaly detection", r"forecast|time[-_ ]?series|anomal|outlier"),
    ("Retrieval, ranking & recommender metrics", r"retriev|rerank|ranking|recommend|ndcg|(?<![a-z])mrr(?![a-z])"),
    ("Explainability", r"explain|(?<![a-z])(shap|lime|xai)(?![a-z])|captum|interpretab"),
    ("Safety, red-teaming & guardrails", r"safety|jailbreak|red[-_ ]?team|guardrail|toxic|moderation"),
    ("Data pipelines & ML monitoring", r"monitor|drift|data[-_ ]?quality|dedup|curat"),
    ("LLM eval platforms & app frameworks", r"observab|tracing|prompt|llmops"),
    ("Classic metric libraries", r"metric|(?<![a-z])(bleu|rouge|meteor|auc)(?![a-z])"),
    ("LLM eval harnesses & benchmarks", r"eval|bench|harness|leaderboard"),
)
SPEECH = re.compile(r"(?<![A-Za-z])(wer|cer|mer|pesq|stoi|asr)(?![a-z])|speech|audio|diariz|transcri", re.I)


def area_of(repo: str, hand: dict[str, str], titles: list[str]) -> tuple[str, bool]:
    """(area, assigned by hand)."""
    if repo.lower() in hand:
        return hand[repo.lower()], True
    for text in (repo, "\n".join(sorted(titles))):
        for area, pattern in AREA_RULES:
            if re.search(pattern, text, re.I):
                return area, False
    return OTHER, False


def derive_stats(issues: list, prs: list, stars_doc: dict, areas: dict, meta: dict) -> dict:
    """Every number the page shows, from the fetched rows and the hand-kept area list."""
    user = meta["account"]["login"]
    stars = stars_doc.get("stars") or {}
    key = lambda i: f"{i['repo']}#{i['number']}"  # noqa: E731
    must(len({i["url"] for i in issues}) == len(issues), "issues.json repeats a url")
    closed = [i for i in issues if i["state"] == "closed"]
    not_planned = [i for i in closed if i.get("state_reason") == "not_planned"]

    # the fix of a closed issue: the last merged PR referencing it that merged before it closed
    closer: dict[str, dict] = {}
    for i in closed:
        must(i.get("merged_prs") is not None, f"{key(i)} is closed but was never traced")
        if i.get("state_reason") == "not_planned":
            continue
        limit = ts(i["closed_at"]) + dt.timedelta(seconds=CLOSE_SLACK)
        cands = [p for p in i["merged_prs"] if ts(p["merged_at"]) <= limit]
        for p in cands:
            must(p["hours"] == hours_between(i["created_at"], p["merged_at"]), f"{key(i)}: stored hours")
        if cands:
            closer[key(i)] = max(cands, key=lambda p: (p["merged_at"], -p["pr"]))
    own = {k: p for k, p in closer.items() if p["author"].lower() == user.lower()}
    others = {k: p for k, p in closer.items() if k not in own}
    by_key = {key(i): i for i in issues}
    completed_nofix = sorted(key(i) for i in closed if i.get("state_reason") != "not_planned" and key(i) not in closer)

    groups: dict[tuple, dict] = {}
    for k, p in sorted(others.items()):
        repo = k.rsplit("#", 1)[0]
        g = groups.setdefault((repo, p["pr"]), dict(
            repo=repo, pr=p["pr"], url=f"https://github.com/{repo}/pull/{p['pr']}", pr_author=p["author"],
            merged_at=p["merged_at"], cites_issues=[], issue_closed_at=[], hours_issue_filed_to_merge=[]))
        g["cites_issues"].append(by_key[k]["number"])
    for g in groups.values():
        g["cites_issues"].sort()
        for n in g["cites_issues"]:
            it = by_key[f"{g['repo']}#{n}"]
            g["issue_closed_at"].append(it["closed_at"])
            g["hours_issue_filed_to_merge"].append(hours_between(it["created_at"], g["merged_at"]))
    fixes = sorted(groups.values(), key=lambda g: (g["merged_at"], g["repo"].lower(), g["pr"]))
    lags = [h for g in fixes for h in g["hours_issue_filed_to_merge"]]

    hand = {r.lower(): a for r, a in areas.items()}
    titles: dict[str, list] = {}
    for i in issues:
        titles.setdefault(i["repo"], []).append(i["title"])
    per_repo = {r: len(t) for r, t in titles.items()}
    assigned = {r: area_of(r, hand, t) for r, t in titles.items()}
    by_rule = sorted(({"repo": r, "area": a} for r, (a, h) in assigned.items() if not h), key=lambda x: x["repo"].lower())
    for x in by_rule:
        log(f"areas: {x['repo']} is not in data/areas.json; placed in {x['area']!r} by rule")
    eco: dict[str, dict] = {}
    for r, (a, _) in assigned.items():
        e = eco.setdefault(a, {"bucket": a, "repos": 0, "issues": 0, "_r": []})
        e["repos"] += 1
        e["issues"] += per_repo[r]
        e["_r"].append(r)
    ecosystems = []
    for e in sorted(eco.values(), key=lambda e: (e["bucket"] == OTHER, -e["issues"], e["bucket"])):
        ex = sorted(e.pop("_r"), key=lambda r: (-(stars.get(r) or 0), r.lower()))[:5]
        ecosystems.append(dict(e, examples=", ".join(r.split("/", 1)[1] for r in ex)))
    audio = [i for i in issues if SPEECH.search(i["title"]) or assigned[i["repo"]][0] == "Speech & audio"]

    upstream = [p for p in prs if p["repo"].split("/")[0].lower() != user.lower()]
    merged = sorted((p for p in prs if p["state"] == "merged"), key=lambda p: (p["merged_at"], p["url"]))
    merged_list = []
    for p in merged:
        closes = sorted((k for k, c in own.items() if c["pr"] == p["number"] and k.rsplit("#", 1)[0] == p["repo"]),
                        key=lambda k: int(k.rsplit("#", 1)[1]))
        merged_list.append(dict(repo=p["repo"], number=p["number"], title=p["title"], merged_at=p["merged_at"],
                                closes_issue=closes,
                                hours=[hours_between(by_key[k]["created_at"], p["merged_at"]) for k in closes]))
    must(sum(len(m["closes_issue"]) for m in merged_list) == len(own), "an own fix is not among his merged PRs")
    daily, monthly = {}, {}
    for i in issues:
        daily[i["created_at"][:10]] = daily.get(i["created_at"][:10], 0) + 1
        monthly[i["created_at"][:7]] = monthly.get(i["created_at"][:7], 0) + 1
    top = sorted(per_repo, key=lambda r: (-per_repo[r], -(stars.get(r) or 0), r.lower()))[:12]
    c = meta["counts"]
    return {
        "as_of": meta["as_of"],
        "account": meta["account"],
        "queries": {k: c[k] for k, _ in COUNT_QUERIES},
        "exclusion_applied": bool(meta.get("exclusion_applied")),
        "issues": {
            "total": len(issues), "open": sum(i["state"] == "open" for i in issues), "closed": len(closed),
            "closed_completed": len(closed) - len(not_planned), "closed_not_planned": len(not_planned),
            "distinct_repos": len(per_repo), "distinct_owner_accounts": len({i["owner"] for i in issues}),
            "max_issues_in_one_repo": max(per_repo.values(), default=0),
            "repos_with_more_than_one": sum(v > 1 for v in per_repo.values()),
            "first_created_at": min(i["created_at"] for i in issues),
            "last_created_at": max(i["created_at"] for i in issues),
            "monthly": dict(sorted(monthly.items())), "daily_utc": dict(sorted(daily.items())),
            "with_comments": sum(1 for i in issues if i.get("comments")),
        },
        "outcomes": {
            "open": sum(i["state"] == "open" for i in issues), "closed": len(closed),
            "fixed_by_merged_pr_from_someone_else": len(others), "fixed_by_his_own_merged_pr": len(own),
            "closed_completed_without_a_fix_merged": len(completed_nofix),
            "closed_completed_without_a_fix": completed_nofix,
            "closed_not_planned": len(not_planned), "not_planned": sorted(key(i) for i in not_planned),
        },
        "fix_lag_hours_filed_to_merge": {
            "n": len(lags), "min": round(min(lags), 1) if lags else None,
            "median": round(statistics.median(lags), 1) if lags else None, "max": round(max(lags), 1) if lags else None,
        },
        "prs": {
            "total": len(prs), "upstream": len(upstream), "in_own_repo": len(prs) - len(upstream),
            "own_repos": sorted({p["repo"] for p in prs} - {p["repo"] for p in upstream}),
            "merged": len(merged), "open": sum(p["state"] == "open" for p in prs),
            "closed_unmerged": sum(p["state"] == "closed_unmerged" for p in prs),
            "distinct_upstream_repos": len({p["repo"] for p in upstream}),
            "first_pr_created_at_upstream": min((p["created_at"] for p in upstream), default=None),
            "closed_unmerged_detail": sorted(f"{p['repo']}#{p['number']}" for p in prs if p["state"] == "closed_unmerged"),
            "merged_list": merged_list,
        },
        "fixes_by_others": fixes,
        "fixes_by_others_summary": {"prs": len(fixes), "issues_fixed": len(others),
                                    "distinct_pr_authors": len({g["pr_author"].lower() for g in fixes})},
        "ecosystems": ecosystems,
        "areas_by_rule": by_rule,
        "speech_audio": {"repo_level_repos": sum(1 for a, _ in assigned.values() if a == "Speech & audio"),
                         "issue_level": len(audio), "issues": [key(i) for i in audio]},
        "top_repos": [{"repo": r, "issues": per_repo[r], "stars": stars.get(r)} for r in top],
        "stars_read_at": stars_doc.get("read_at"),
    }


def run_stats(data: Path) -> dict:
    st = derive_stats(read(data / "issues.json"), read(data / "prs.json"), read(data / "stars.json"),
                      read(data / "areas.json"), read(data / "fetch.json"))
    write_if_changed(data / "stats.json", dump(st))
    return st


# ==================================================================== render ====
CARD, GUT, PAD = 374, 6, 14          # card width, transparent gutter right/below, inner padding
IMG = CARD + GUT                     # 380: two sit side by side in a ~780 px column, stack on a phone
INNER = CARD - 2 * PAD
H = 336                              # one height for every panel, so paired images never stagger
T, BIG = 12, 26                      # the only two text sizes; 12 units is the floor
FONT = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace'
ADV = 0.62                           # worst-case monospace advance, em; used to fail on overflow
EPS = 0.01
MAX_BINS = 23                        # a two-digit count at 12 units needs a 15-unit slot
SHOW_AREAS = 11                      # areas drawn as bars; the rest are summed on one line
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
LOGIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}(\[bot\])?")

# neutrals are Primer's own tokens; one accent, and it always means "fixed" (or ideal, or matched). warn is the
# thing that quietly went wrong, and the colour of every "schematic" label; faint is graph paper and terminals.
THEMES = {
    "light": dict(bg="#ffffff", fg="#1f2328", muted="#59636e", line="#d1d9e0",
                  ink="#6e7781", cell="#d0d7de", accent="#0969da", warn="#bc4c00", faint="#eef1f4"),
    "dark": dict(bg="#0d1117", fg="#f0f6fc", muted="#9198a1", line="#3d444d",
                 ink="#7d8590", cell="#30363d", accent="#3987e5", warn="#db6d28", faint="#161b22"),
}
WIDE, MID, NARROW, AN_NARROW = 830, 560, 380, 400   # a full-width picture, its mid-width twin, the phone twins
SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'   # the name only
MOTION = "@media (prefers-reduced-motion: reduce){*{animation:none!important}}"
SIZES = (12, 13, 14, 16, 22, 26, 30, 40, 52)    # every text size an illustration may use; 12 is the floor
MAX_ANIM = 11.0                                  # seconds: every animation has finished by then
ART = ["header", "proteins", "brains", "quantum", "music", "divider", "shelf", "stats", "constellation", "analyzer"]
NARROW_ART = {"header", "constellation", "analyzer", "shelf", "stats"}   # drawn three times: wide, mid and narrow
SIZES_OF = ("wide", "mid", "narrow")

# area labels shortened for the label column; the key is the area name in areas.json
AREA_LABELS = {
    "LLM eval harnesses & benchmarks": "eval harnesses & benchmarks",
    "Judge, RAG & hallucination scoring": "judge, RAG & hallucination scoring",
    "RL post-training & reward functions": "RL post-training & rewards",
    "Agent & tool-use benchmarks": "agent & tool-use benchmarks",
    "Classic metric libraries": "classic metric libraries",
    "LLM eval platforms & app frameworks": "eval platforms & app frameworks",
    "Fairness, calibration & uncertainty": "fairness, calibration & uncertainty",
    "Code & math answer checking": "code & math answer checking",
    "Data pipelines & ML monitoring": "data pipelines & ML monitoring",
    "Safety, red-teaming & guardrails": "safety, red-teaming & guardrails",
    "Autograders & education": "autograders & education",
    "Forecasting, time series & anomaly detection": "forecasting & anomaly detection",
    "Retrieval, ranking & recommender metrics": "retrieval & recommender metrics",
    "Explainability": "explainability",
    "Speech & audio": "speech & audio",
    OTHER: "other",
}

PANELS = ["filed", "outcome", "areas", "probe"]   # read in pairs: filed|outcome, areas|probe


def n(x: float) -> str:
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def clean(s: object) -> str:
    """One line of text: control characters dropped, whitespace runs collapsed."""
    return re.sub(r"\s+", " ", "".join(ch if ord(ch) >= 32 else " " for ch in str(s))).strip()


def md(s: object) -> str:
    """Markdown text from a string that did not come from this file: HTML characters become
    entities, markdown punctuation is backslash-escaped, so neither can open a tag, link or cell."""
    rep = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
    return "".join(rep.get(ch) or ("\\" + ch if ch in "\\|[]*_`#~!" else ch) for ch in clean(s))


def h(s: object) -> str:
    """Text for HTML (a raw HTML block, an attribute, SVG): escaped, one line, and brackets as
    entities so nothing in it can read as a markdown link even outside the block."""
    return escape(clean(s), quote=True).replace("[", "&#91;").replace("]", "&#93;")


h_ = h   # the escaper under a second name, for code where h is a height


def mmdd(x: dt.date) -> str:
    return x.strftime("%m-%d")


def short(repo: str) -> str:
    return repo.split("/", 1)[1]


def plural(k: int, one: str, many: str | None = None) -> str:
    return f"{k} {one if k == 1 else (many or one + 's')}"


def bins_for(start: dt.date, end: dt.date) -> tuple[str, list[tuple[dt.date, dt.date]]]:
    """Days while they fit the panel, then ISO weeks, then calendar months."""
    span = (end - start).days + 1
    if span <= MAX_BINS:
        return "day", [(start + dt.timedelta(days=i),) * 2 for i in range(span)]
    w = start - dt.timedelta(days=start.weekday())
    weeks = []
    while w <= end:
        weeks.append((w, w + dt.timedelta(days=6)))
        w += dt.timedelta(days=7)
    if len(weeks) <= MAX_BINS:
        return "week", weeks
    months, y, mo = [], start.year, start.month
    while (y, mo) <= (end.year, end.month):
        nxt = dt.date(y + mo // 12, mo % 12 + 1, 1)
        months.append((dt.date(y, mo, 1), nxt - dt.timedelta(days=1)))
        y, mo = nxt.year, nxt.month
    must(len(months) <= MAX_BINS, f"{len(months)} months do not fit the filed panel")
    return "month", months


def derive(d: dict, issues: list, notes: dict, probe: dict) -> dict:
    """Cross-check stats.json against the rows it came from, and lay out what the page needs."""
    iss, out, prs, q = d["issues"], d["outcomes"], d["prs"], d["queries"]
    login = d["account"]["login"]
    must(LOGIN_RE.fullmatch(login) is not None, "account login")
    as_of = d["as_of"]
    must(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\dZ", as_of) is not None, "as_of format")
    start, end = day_of(iss["first_created_at"]), day_of(as_of)
    must(start <= end, "first issue after as_of")
    unit, spans = bins_for(start, end)
    daily = iss["daily_utc"]
    must(all(start <= dt.date.fromisoformat(k) <= end for k in daily), "daily key outside the window")

    def bin_of(day: dt.date) -> int:
        for b, (a, z) in enumerate(spans):
            if a <= day <= z:
                return b
        raise SystemExit(f"input check failed: {day} is outside the filed panel")

    filed = [0] * len(spans)
    for k, v in daily.items():
        filed[bin_of(dt.date.fromisoformat(k))] += v
    must(sum(filed) == iss["total"], "daily counts do not sum to issues.total")
    must(iss["open"] + iss["closed"] == iss["total"], "open + closed != total")
    must((q["issues_total"], q["issues_open"], q["issues_closed"]) == (iss["total"], iss["open"], iss["closed"]),
         "issue total_count values differ from the rows")
    must((q["prs_total"], q["prs_merged"], q["prs_open"], q["prs_closed_unmerged"])
         == (prs["total"], prs["merged"], prs["open"], prs["closed_unmerged"]), "PR total_count values differ from the rows")
    must(len(issues) == iss["total"], "issues.json rows != issues.total")
    must(len({i["url"] for i in issues}) == iss["total"], "issues.json has duplicate urls")
    must(len({i["repo"] for i in issues}) == iss["distinct_repos"], "issues.json repos != distinct_repos")
    must(sum(i["state"] == "open" for i in issues) == iss["open"], "issues.json open count")
    must(all(REPO_RE.fullmatch(i["repo"]) for i in issues), "a repository name has unexpected characters")
    by_key = {f"{i['repo']}#{i['number']}": i for i in issues}

    fixes = []                       # one record per merged PR; each closes one or more issues
    for f in d["fixes_by_others"]:
        must(REPO_RE.fullmatch(f["repo"]) and LOGIN_RE.fullmatch(f["pr_author"]), f"identifiers of {f['url']}")
        must(f["url"] == f"https://github.com/{f['repo']}/pull/{f['pr']}", f"url of {f['repo']}#{f['pr']}")
        fixes.append(dict(repo=f["repo"], pr=f["pr"], url=f["url"], by=f["pr_author"], own=False,
                          merged_at=f["merged_at"], closes=[f"{f['repo']}#{i}" for i in f["cites_issues"]],
                          hours=list(f["hours_issue_filed_to_merge"])))
    for f in prs["merged_list"]:
        if not f["closes_issue"]:
            continue
        fixes.append(dict(repo=f["repo"], pr=f["number"], url=f"https://github.com/{f['repo']}/pull/{f['number']}",
                          by=login, own=True, merged_at=f["merged_at"], closes=list(f["closes_issue"]),
                          hours=list(f["hours"])))
    fixes.sort(key=lambda f: (f["merged_at"], f["repo"].lower(), f["pr"]))
    for f in fixes:
        must(start <= day_of(f["merged_at"]) <= end, f"fix {f['repo']}#{f['pr']} outside the window")
        for k, hrs in zip(f["closes"], f["hours"]):
            must(k in by_key, f"{k} is not in issues.json")
            it = by_key[k]
            must(it["state"] == "closed", f"{k} is fixed but not closed")
            must(ts(it["closed_at"]) + dt.timedelta(seconds=CLOSE_SLACK) >= ts(f["merged_at"]), f"{k} closed before its fix merged")
            must(hrs == hours_between(it["created_at"], f["merged_at"]), f"{k}: hours")
            must(any(p["pr"] == f["pr"] for p in it["merged_prs"] or []), f"{k}: fix not among its merged_prs")
    fix_others, fix_own = [0] * len(spans), [0] * len(spans)
    for f in fixes:
        (fix_own if f["own"] else fix_others)[bin_of(day_of(f["merged_at"]))] += len(f["closes"])
    n_others, n_own = sum(fix_others), sum(fix_own)
    must(n_others == out["fixed_by_merged_pr_from_someone_else"], "fixes by others != outcomes count")
    must(n_own == out["fixed_by_his_own_merged_pr"], "own fixes != outcomes count")
    summary = d["fixes_by_others_summary"]
    must(len([f for f in fixes if not f["own"]]) == summary["prs"], "PRs by others")
    must(len({f["by"].lower() for f in fixes if not f["own"]}) == summary["distinct_pr_authors"], "distinct PR authors")
    nofix = out["closed_not_planned"] + out["closed_completed_without_a_fix_merged"]
    must(len(out["not_planned"]) == out["closed_not_planned"], "not_planned list length")
    must(n_others + n_own + nofix == iss["closed"], "closed issues do not add up")
    must(n_others + n_own + nofix + out["open"] == iss["total"], "outcomes do not add up to total")
    must(prs["merged"] + prs["open"] + prs["closed_unmerged"] == prs["total"], "PR states do not add up")
    must(len(prs["merged_list"]) == prs["merged"], "merged_list length")

    hours = [h_ for f in fixes if not f["own"] for h_ in f["hours"]]
    lag = d["fix_lag_hours_filed_to_merge"]
    must(len(hours) == lag["n"] == n_others, "lag sample size")
    if hours:
        must(round(min(hours), 1) == lag["min"] and round(max(hours), 1) == lag["max"], "lag min/max")
        must(round(statistics.median(hours), 1) == lag["median"], "lag median")

    areas = list(d["ecosystems"])
    must(sum(a["issues"] for a in areas) == iss["total"], "area issues != total")
    must(sum(a["repos"] for a in areas) == iss["distinct_repos"], "area repos != distinct_repos")
    must(all(a["bucket"] in AREA_LABELS for a in areas), "an area has no short label")
    must(areas == sorted(areas, key=lambda a: (a["bucket"] == OTHER, -a["issues"], a["bucket"])), "area order")
    speech = d["speech_audio"]
    must(len(speech["issues"]) == speech["issue_level"], "speech_audio issue list length")
    must(all(k in by_key for k in speech["issues"]), "a speech_audio issue is not in issues.json")

    fixed_keys = {k: f for f in fixes for k in f["closes"]}
    rows = []
    for r in notes["rows"]:
        must(r["issue"] in fixed_keys, f"notes.json names {r['issue']}, which no merged fix closed")
        rows.append(dict(issue=r["issue"], what=r["what"], fix=fixed_keys[r["issue"]]))
    must(len(rows) == len({r["issue"] for r in rows}), "notes.json repeats an issue")
    count = NUMBER_WORDS.get(len(rows), str(len(rows)))
    must(notes["lead"].startswith(f"{count} of the fixes"),
         f"notes.json: the lead must start with {count + ' of the fixes'!r}, because the table has {len(rows)} rows")

    must(len(probe["runs"]) == 2, "probe: expected the grader as shown and as fixed")
    for run in probe["runs"]:
        must(len(run["findings"]) <= len(run["checks_run"]), "probe: more findings than checks")
        must(all(f["n"] >= 1 for f in run["findings"]), "probe: a finding with no example")
    if probe.get("url"):
        must(re.fullmatch(r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+", probe["url"]) is not None, "probe url")

    labels = {"day": mmdd, "week": mmdd, "month": lambda x: x.strftime("%Y-%m")}[unit]
    descs = {"day": mmdd, "week": lambda x: "week of " + mmdd(x), "month": lambda x: x.strftime("%Y-%m")}[unit]
    bins = [dict(tick=labels(a), desc=descs(a), filed=c, others=o, own=w)
            for (a, _), c, o, w in zip(spans, filed, fix_others, fix_own)]
    return dict(as_of=as_of, start=start, end=end, unit=unit, bins=bins, d=d,
                total=iss["total"], repos=iss["distinct_repos"], areas=areas, speech=speech,
                outcome=[("others", n_others), ("own", n_own), ("nofix", nofix), ("open", out["open"])],
                hours=hours, lag=lag, fixed=n_others + n_own, fixes=fixes, prs=prs, q=q, closed=iss["closed"],
                summary=summary, login=login, notes=notes, rows=rows, probe=probe,
                excluded=bool(d.get("exclusion_applied")),
                by_rule=d.get("areas_by_rule") or [])


# ------------------------------------------------------------------- svg ----
def _hit(a, b) -> bool:
    return a[0] < b[1] - EPS and b[0] < a[1] - EPS and a[2] < b[3] - EPS and b[2] < a[3] - EPS


class Svg:
    """One picture. Every text node and every registered mark is a box; a text box that leaves the text area or
    touches another box fails the build. The defaults draw the 380 x 342 card the four panels use."""

    def __init__(self, t: dict, title: str, desc: str, w: float = IMG, h: float = H + GUT, frame: bool = True,
                 css: str = "", area: tuple | None = None, card_h: float = H):
        self.t, self.w, self.h = t, w, h
        self.area = area or (PAD, CARD - PAD, 0, card_h)      # x0, x1, y0, y1 that every text box must stay inside
        self.texts: list[tuple] = []
        self.marks: list[tuple] = []
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n(w)} {n(h)}" width="{n(w)}" height="{n(h)}" '
            f'role="img" aria-labelledby="t d">',
            f'<title id="t">{h_(title)}</title>',
            f'<desc id="d">{h_(desc)}</desc>',
            "<style>"
            f"text{{font-family:{FONT};font-size:{T}px;fill:{t['fg']}}}"
            f".m{{fill:{t['muted']}}}.a{{fill:{t['accent']}}}.b{{font-size:{BIG}px}}"
            ".e{text-anchor:end}.c{text-anchor:middle}"
            + css + (MOTION if "@keyframes" in css else "") +
            "</style>",
        ]
        if frame:
            self.parts.append(f'<rect x=".5" y=".5" width="{CARD - 1}" height="{n(card_h - 1)}" rx="6" fill="{t["bg"]}" '
                              f'stroke="{t["line"]}"/>')

    def add(self, s: str) -> None:
        self.parts.append(s)

    @staticmethod
    def box(x: float, y: float, s: str, size: float = T, anchor: str = "start") -> tuple:
        w = len(s) * size * ADV
        x0 = {"end": x - w, "middle": x - w / 2}.get(anchor, x)
        return (x0, x0 + w, y - 0.78 * size, y + 0.22 * size, s)

    def _inside(self, b: tuple) -> bool:
        x0, x1, y0, y1 = self.area
        return b[0] >= x0 - EPS and b[1] <= x1 + EPS and b[2] >= y0 - EPS and b[3] <= y1 + EPS

    def _others(self, layer):
        """Boxes a new box must not touch: those on no layer, and those on its own layer. Two layers that are never
        shown at once (quantum's frames) may reuse the same place."""
        return [o for o in self.texts + self.marks if o[5] is None or layer is None or o[5] == layer]

    def free(self, b: tuple, gap: float = 0.0, layer=None) -> bool:
        """Whether a text box fits inside the text area, `gap` units clear of everything placed."""
        wide = (b[0] - gap, b[1] + gap, b[2], b[3], b[4])
        return self._inside(b) and not any(_hit(wide, o) for o in self._others(layer))

    def _place(self, b: tuple, layer=None) -> None:
        if not self._inside(b):
            x0, x1, y0, y1 = self.area
            raise SystemExit(f"overflow: {b[4]!r} spans {b[0]:.0f}..{b[1]:.0f} x {b[2]:.0f}..{b[3]:.0f}; "
                             f"the text area is {n(x0)}..{n(x1)} x {n(y0)}..{n(y1)}")
        for o in self._others(layer):
            if _hit(b, o):
                raise SystemExit(f"collision: {b[4]!r} overlaps {o[4]!r}")
        self.texts.append((*b[:5], layer))

    def text(self, x: float, y: float, s: str, cls: str = "", size: int = T, layer=None, extra: str = "",
             body: str | None = None) -> None:
        """One line of text at (x, y). body, when given, is the element's content as built by the caller from
        this file's own strings (tspans); the box is still measured on s."""
        c = cls.split()
        must(size in SIZES, f"text size {size} is not one of {SIZES}")
        self._place(self.box(x, y, s, size, "end" if "e" in c else ("middle" if "c" in c else "start")), layer)
        if size != T:
            cls = (cls + " " + ("b" if size == BIG else f"s{size}")).strip()
        if body is None:
            body = escape("".join(ch for ch in s if ord(ch) >= 32), quote=False)   # spaces kept: code is shown
            if "  " in s or s.startswith(" "):
                body = body.replace(" ", "\u00a0")   # SVG collapses runs of spaces; code keeps its indent
        attr = f' class="{cls}"' if cls else ""
        self.add(f'<text{attr} x="{n(x)}" y="{n(y)}"{extra}>{body}</text>')

    def mark(self, x0: float, y0: float, x1: float, y1: float, what: str = "mark", layer=None) -> None:
        """Register an area no text may touch (a drawn shape)."""
        b = (x0, x1, y0, y1, what)
        for o in self.texts:
            if (o[5] is None or layer is None or o[5] == layer) and _hit(b, o):
                raise SystemExit(f"collision: {what} overlaps {o[4]!r}")
        self.marks.append((*b, layer))

    def rect(self, x, y, w, hh, fill, rx=0.0, what="mark", extra="") -> None:
        self.mark(x, y, x + w, y + hh, what)
        r = f' rx="{n(rx)}"' if rx else ""
        self.add(f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(hh)}"{r} fill="{fill}"{extra}/>')

    def circle(self, cx: float, cy: float, r: float, fill: str = "none", stroke: str | None = None,
               sw: float | None = None, cls: str = "", what: str | None = None, extra: str = "") -> None:
        if what:
            pad = (sw or 0) / 2
            self.mark(cx - r - pad, cy - r - pad, cx + r + pad, cy + r + pad, what)
        c = f' class="{cls}"' if cls else ""
        st = f' stroke="{stroke}"' if stroke else ""
        w = f' stroke-width="{n(sw)}"' if sw is not None else ""
        self.add(f'<circle{c} cx="{n(cx)}" cy="{n(cy)}" r="{n(r)}" fill="{fill}"{st}{w}{extra}/>')

    def path(self, d: str, cls: str = "", extra: str = "") -> None:
        c = f' class="{cls}"' if cls else ""
        self.add(f'<path{c} d="{d}"{extra}/>')

    def poly(self, pts: list[tuple[float, float]], cls: str = "", extra: str = "") -> None:
        c = f' class="{cls}"' if cls else ""
        self.add(f'<polyline{c} points="{" ".join(f"{n(x)},{n(y)}" for x, y in pts)}"{extra}/>')

    def group(self, cls: str = "", transform: str = "", extra: str = "") -> None:
        c = f' class="{cls}"' if cls else ""
        tr = f' transform="{transform}"' if transform else ""
        self.add(f"<g{c}{tr}{extra}>")

    def end(self) -> None:
        self.add("</g>")

    def readout(self, x: float, big: str, unit: str, y: float = 56, size: int = BIG, gap: float = 7,
                ucls: str = "m") -> None:
        b1 = self.box(x, y, big, size)
        self._place(b1)
        self._place(self.box(b1[1] + gap, y, unit))
        bc = "b" if size == BIG else f"s{size}"
        self.add(f'<text x="{n(x)}" y="{n(y)}"><tspan class="{bc}">{h(big)}</tspan>'
                 f'<tspan class="{ucls}" dx="{n(gap)}">{h(unit)}</tspan></text>')

    def rule(self, y: float) -> None:
        self.add(f'<path d="M{PAD} {n(y + .5)}H{CARD - PAD}" stroke="{self.t["line"]}" fill="none"/>')

    def done(self) -> str:
        self.parts.append("</svg>")
        return "\n".join(self.parts) + "\n"


def glyph(s: Svg, kind: str, x: float, y: float, size: float, what: str) -> None:
    """One issue. Solid accent: fixed by someone else's PR. Accent ring: fixed by own PR.
    Grey ring: closed without a fix. Pale solid: open."""
    t, r = s.t, min(1.6, size / 3)
    if kind in ("others", "open"):
        s.rect(x, y, size, size, t["accent"] if kind == "others" else t["cell"], r, what)
    else:
        col = t["accent"] if kind == "own" else t["ink"]
        s.rect(x + .7, y + .7, size - 1.4, size - 1.4, "none", r, what,
               f' stroke="{col}" stroke-width="1.4"')


def panel_filed(m: dict, t: dict) -> str:
    """Filings as bars standing on a baseline, fixes as squares by merge date."""
    b, unit = m["bins"], m["unit"]
    k = len(b)
    desc = (f"issues filed per {unit}, UTC, {m['start']} to {m['end']}: "
            + ", ".join(f"{x['desc']} {x['filed']}" for x in b)
            + f". Issues closed by a merged PR, by merge {unit}: "
            + ", ".join(f"{x['desc']} {x['others'] + x['own']}" for x in b if x["others"] + x["own"]) + ".")
    s = Svg(t, f"issues filed and fixed per {unit}", desc)
    s.text(PAD, 22, f"issues per {unit}, utc", "m")
    s.text(CARD - PAD, 22, f"{m['start']}/{m['end']}", "m e")
    s.rect(PAD, 42, 8, 14, t["ink"], 4, "filed key")
    s.readout(PAD + 16, str(m["total"]), "filed")
    x2 = PAD + 150
    s.rect(x2, 47, 9, 9, t["accent"], 1.6, "fixed key")
    s.readout(x2 + 16, str(m["fixed"]), "fixed")
    if any(x["own"] for x in b):
        x3 = CARD - PAD - len("own PR") * T * ADV
        glyph(s, "own", x3 - 15, 47, 9, "own key")
        s.text(x3, 56, "own PR", "m")

    slot = INNER / k
    cx = [PAD + slot * (i + .5) for i in range(k)]
    base = H - 38
    stack = max(x["others"] + x["own"] for x in b)
    pitch = min(11.0, 99 / max(stack, 1), slot - 2)
    sq = pitch - 2
    must(sq >= 2, f"{stack} fixes in one {unit} do not fit the panel")
    sq_top = base - max(33.0, stack * pitch)
    wave_top, wave_bot = 96, sq_top - 16
    peak = max(x["filed"] for x in b) or 1
    bw = min(8.0, slot - 4)
    tops = []
    s.path(f"M{PAD} {n(wave_bot + .5)}H{CARD - PAD}", extra=f' stroke="{t["line"]}" fill="none"')
    for i, x in enumerate(b):
        c = x["filed"]
        hh = max(2.0, (wave_bot - wave_top) * c / peak)
        tops.append(wave_bot - hh)
        s.rect(cx[i] - bw / 2, wave_bot - hh, bw, hh, t["ink"] if c else t["cell"], min(bw / 2, hh / 2, 3),
               f"bar {x['tick']}")
    # numbers over bars: the peak first, then left to right, each only where it has room
    order = sorted(range(k), key=lambda i: (b[i]["filed"] != peak, i))
    for i in order:
        c = b[i]["filed"]
        if c and s.free(s.box(cx[i], tops[i] - 5, str(c), T, "middle"), 2):
            s.text(cx[i], tops[i] - 5, str(c), "m c")
    s.rule(base)
    for i, x in enumerate(b):
        a, o = x["others"], x["own"]
        if a + o == 0:
            s.rect(cx[i] - bw / 2, base - 3, bw, 2, t["cell"], 1, f"no fix {x['tick']}")
        for j in range(a + o):
            glyph(s, "others" if j < a else "own", cx[i] - sq / 2, base - 2 - sq - j * pitch, sq, f"fix {x['tick']}")
        s.add(f'<path d="M{n(cx[i])} {base + 1}v3" stroke="{t["line"]}" fill="none"/>')
    tick_w = len(b[0]["tick"]) * T * ADV
    step = 5 if unit == "day" else max(1, math.ceil((tick_w + 8) / slot))
    for i in [0, k - 1] + [i for i in range(step, k - 1, step)]:
        anchor, x = ("start", PAD) if i == 0 else (("end", CARD - PAD) if i == k - 1 else ("middle", cx[i]))
        if s.free(s.box(x, base + 18, b[i]["tick"], T, anchor), 6):
            s.text(x, base + 18, b[i]["tick"], "m" + {"start": "", "end": " e", "middle": " c"}[anchor])
    return s.done()


def waffle(total: int, width: float, height: float) -> tuple[float, int]:
    """(pitch, rows) for the largest square cell that fits total cells in the box."""
    best = (0.0, 1)
    for rows in range(1, 41):
        pitch = min(width / math.ceil(total / rows), height / rows)
        if pitch > best[0] + 1e-9:
            best = (pitch, rows)
    return best


def panel_outcome(m: dict, t: dict) -> str:
    cats, total, lag = m["outcome"], m["total"], m["lag"]
    names = {"others": "fixed, PR by someone else", "own": "fixed, own PR",
             "nofix": "closed, no merged PR", "open": "open"}
    desc = (f"state of the {total} issues: " + ", ".join(f"{names[k]} {c}" for k, c in cats)
            + f". Hours from report to merged fix, {lag['n']} fixes by others: "
            f"min {lag['min']}, median {lag['median']}, max {lag['max']}.")
    s = Svg(t, "state of each issue", desc)
    s.text(PAD, 22, "state of each issue", "m")
    s.text(CARD - PAD, 22, "1 square = 1 issue", "m e")
    s.readout(PAD, str(m["fixed"]), f"of {total} fixed")
    pitch, rows = waffle(total, INNER, 78)
    seq = [k for k, c in cats for _ in range(c)]
    for idx, kind in enumerate(seq):
        cx, ry = divmod(idx, rows)
        glyph(s, kind, PAD + cx * pitch, 72 + ry * pitch, pitch - 2.4, "issue square")
    y0 = 72 + rows * pitch + 22
    for i, (kind, c) in enumerate(cats):
        y = y0 + i * 17
        glyph(s, kind, PAD, y - 9, 9, f"key {kind}")
        s.text(PAD + 17, y, names[kind])
        s.text(CARD - PAD - 52, y, str(c), "e")
        s.text(CARD - PAD, y, f"{100 * c / total:.1f}%", "m e")
    base = H - 32
    ly = base - 56
    must(y0 + 3 * 17 + 6 <= ly, "the outcome key runs into the hours strip")
    s.rule(ly)
    s.text(PAD, ly + 19, "hours, report to merged fix by others", "m")
    s.text(CARD - PAD, ly + 19, f"n {lag['n']}", "m e")
    s.rule(base)
    if m["hours"]:
        top = max(m["hours"])
        xs = lambda v: PAD + INNER * v / top  # noqa: E731
        for v in m["hours"]:
            s.add(f'<rect x="{n(xs(v) - .8)}" y="{base - 15}" width="1.6" height="15" fill="{t["accent"]}"/>')
        med = lag["median"]
        s.add(f'<rect x="{n(xs(med) - .8)}" y="{base - 21}" width="1.6" height="21" fill="{t["fg"]}"/>')
        lo, hi, mid = f"{lag['min']}", f"{lag['max']}", f"median {med}"
        s.text(PAD, base + 16, lo, "m")
        s.text(CARD - PAD, base + 16, hi, "m e")
        w = len(mid) * T * ADV
        left, right = PAD + len(lo) * T * ADV + 6 + w / 2, CARD - PAD - len(hi) * T * ADV - 6 - w / 2
        must(left <= right, "no room for the median label")
        s.text(min(max(xs(med), left), right), base + 16, mid, "c")
    return s.done()


def area_label(a: dict) -> str:
    return AREA_LABELS[a["bucket"]]


def panel_areas(m: dict, t: dict) -> str:
    areas = m["areas"]
    shown = areas if len(areas) <= SHOW_AREAS + 1 else areas[:SHOW_AREAS]
    rest = areas[len(shown):]
    desc = (f"{m['total']} issues in {m['repos']} repositories, each repository in one area: "
            + ", ".join(f"{area_label(a)} {a['issues']}" for a in areas)
            + ".")
    lines = len(shown) + (1 if rest else 0)
    y0 = 86
    pitch = min(18.0, (H - 30 - y0) / max(lines - 1, 1))
    card_h = y0 + (lines - 1) * pitch + 16          # the card ends one line below its last line, as the others do
    s = Svg(t, "issues by area", desc, h=card_h + GUT, card_h=card_h)
    s.text(PAD, 22, "issues by area", "m")
    s.text(CARD - PAD, 22, plural(len(areas), "area"), "m e")
    s.readout(PAD, str(m["repos"]), "repositories")
    label_w = max(len(area_label(a)) for a in shown) * T * ADV
    num_w = max(len(str(a["issues"])) for a in shown) * T * ADV
    bar_x, bar_end = PAD + label_w + 10, CARD - PAD - num_w - 8
    must(bar_end - bar_x >= 40, "area labels leave no room for the bars")
    top = max(a["issues"] for a in shown)
    for i, a in enumerate(shown):
        y = y0 + i * pitch
        s.text(PAD, y, area_label(a), "m")
        s.rect(bar_x, y - 8, max(2.0, (bar_end - bar_x) * a["issues"] / top), 7, t["ink"], 2, f"bar {a['bucket']}")
        s.text(CARD - PAD, y, str(a["issues"]), "e")
    if rest:
        y = y0 + len(shown) * pitch
        ri, rr = sum(a["issues"] for a in rest), sum(a["repos"] for a in rest)
        for line in (f"and {plural(len(rest), 'more area')}: {plural(ri, 'issue')}, "
                     f"{plural(rr, 'repository', 'repositories')}",
                     f"and {len(rest)} more: {plural(ri, 'issue')}, {rr} repos",
                     f"+{len(rest)} areas, {ri} issues"):
            if s.free(s.box(PAD, y, line)):
                s.text(PAD, y, line, "m")
                break
        else:
            raise SystemExit("overflow: no summary line for the folded areas fits")
    return s.done()


def panel_probe(m: dict, t: dict) -> str:
    p = m["probe"]
    broken, fixed = p["runs"]
    desc = (f"scoreprobe {p['version']}, {p['status']}. A grader written as: "
            + " ".join(x.strip() for x in p["source"])
            + f". probe(grader=grade): {len(broken['findings'])} of {len(broken['checks_run'])} checks reproduce: "
            + "; ".join(f"{f['check']}, e.g. answer {f['answer']} against reference {f['reference']}, "
                        f"{f['n']} inputs earned credit" for f in broken["findings"])
            + f". With the line changed to {p['fixed_line'].strip()}: "
              f"{len(fixed['findings'])} of {len(fixed['checks_run'])} reproduce.")
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    s = Svg(t, f"scoreprobe on a {words.get(len(p['source']), str(len(p['source'])))}-line grader", desc)
    s.text(PAD, 22, "scoreprobe", "")
    s.text(CARD - PAD, 22, p["status"], "m e")
    y = 50
    for line in p["source"]:
        s.text(PAD, y, line, "m")
        y += 16

    def verdict(y, run, cls):
        s.text(PAD, y, "probe(grader=grade)", "")
        s.text(CARD - PAD, y, f"{len(run['findings'])} of {len(run['checks_run'])} checks reproduce", (cls + " e").strip())

    verdict(94, broken, "")
    xa = PAD + max(len(x) for x in ["check"] + [f["check"] for f in broken["findings"]]) * T * ADV + 8
    s.text(PAD, 116, "check", "m")
    s.text(xa, 116, "answer", "m")
    s.text(CARD - PAD, 116, "reference", "m e")
    for i, f in enumerate(broken["findings"]):
        yy = 134 + i * 17
        s.text(PAD, yy, f["check"])
        s.text(xa, yy, f["answer"])
        s.text(CARD - PAD, yy, f["reference"], "e")
    yd = 134 + max(len(broken["findings"]) - 1, 0) * 17 + 10
    s.rule(yd)
    s.text(PAD, yd + 24, "-" + p["source"][-1][1:], "m")
    s.text(PAD, yd + 40, "+" + p["fixed_line"][1:], "")
    verdict(yd + 66, fixed, "a")
    s.text(PAD, H - 14, "rows: answers the grader marked correct", "m")
    return s.done()


PANEL_FN = dict(filed=panel_filed, outcome=panel_outcome, areas=panel_areas, probe=panel_probe)


# ------------------------------------------------------------ illustrations ----
# The eight pictures between the prose. Each is drawn from data/ (the same rows the tables use) or from a formula
# in this section; the two schematics and the header's icons say so on the image. Light and dark come from the
# same function with a different token dict, so the geometry is identical.

GREP = ('$ grep -rl "same field" ~/built/', "no matches")     # the joke from his site's sessions log
# (label on the map, icon, keyword, where the keyword must appear): the route follows the intro sentence, music last
HEADER_STOPS = (
    ("proteins", "proteins", "proteins", "intro"),
    ("brains", "brains", "brains", "intro"),
    ("quantum", "quantum", "quantum", "intro"),
    ("classrooms", "classrooms", "classrooms", "intro"),
    ("street safety", "street safety", "street safety", "intro"),
    ("buildings", "buildings", "buildings", "intro"),
    ("underwater robot", "underwater robot", "underwater robot", "intro"),
    ("graders", "graders", "grades", "intro"),
    ("music", "music", "music", "off the clock"),
)
# one label per area for the constellation, at most 14 characters; an area missing here stops the build
STAR_LABELS = {
    "LLM eval harnesses & benchmarks": "eval harnesses",
    "Judge, RAG & hallucination scoring": "judges & RAG",
    "RL post-training & reward functions": "RL rewards",
    "Agent & tool-use benchmarks": "agent evals",
    "Classic metric libraries": "metric libs",
    "LLM eval platforms & app frameworks": "eval platforms",
    "Fairness, calibration & uncertainty": "fairness & UQ",
    "Code & math answer checking": "code & math",
    "Data pipelines & ML monitoring": "data pipelines",
    "Safety, red-teaming & guardrails": "safety",
    "Autograders & education": "autograders",
    "Forecasting, time series & anomaly detection": "forecasting",
    "Retrieval, ranking & recommender metrics": "retrieval",
    "Explainability": "explainability",
    "Speech & audio": "speech & audio",
    OTHER: "other",
}
STAR_LABEL_MAX = 14
# the phone twin's three columns sit 117 apart, so two 14-character labels side by side read as one; these are
# drawn there instead (the description and alt text keep the full label)
STAR_LABELS_NARROW = {"Speech & audio": "speech"}
# textbook backbone geometry, angstroms and degrees: an alpha helix, a loop, a turn and two antiparallel strands
PROTEIN = dict(helix=18, loop=4, strand=8, turn=3, rise=1.5, radius=2.3, deg=100, strand_step=3.3, pleat=0.9)
# shotfloor's example: 8 qubits (256 outcomes), uniform target, 1,024 shots; one simulated flawless run, seed 0
QUANTUM = dict(K=256, shots=1024, frames=(128, 256, 512), seed=0, clip=4, axis=(64, 65536))
GAP_S = 10.0          # brains: a gap this long between triggers breaks the residual trace
STAR_STEP, STAR_TURN = 7.5, 137.508               # golden-angle spiral: radius step per sqrt(i), degrees per star


def is_dark(t: dict) -> bool:
    return t["bg"] == THEMES["dark"]["bg"]


def art_css(t: dict, extra: str = "") -> str:
    """The text classes every illustration shares, after the panels' own: warn, the sans name, and the sizes."""
    sizes = "".join(f".s{z}{{font-size:{z}px}}" for z in SIZES if z not in (T, BIG))
    return f".w{{fill:{t['warn']}}}.nm{{font-family:{SANS};font-weight:700}}" + sizes + extra


def frame(s: "Svg", w: float, hh: float) -> None:
    """The card edge of a full-width picture: one stroke, half a unit in, in both themes."""
    s.add(f'<rect x=".5" y=".5" width="{n(w - 1)}" height="{n(hh - 1)}" rx="8" fill="{s.t["bg"]}" stroke="{s.t["line"]}"/>')


def delay(sec: float) -> str:
    return f' style="animation-delay:{sec:.2f}s"'


# ---------------------------------------------------------------- math ----
def golden(i: int, step: float = STAR_STEP) -> tuple[float, float]:
    """Position of the i-th point on a golden-angle spiral: radius step*sqrt(i), angle i*137.508 degrees."""
    r, th = step * math.sqrt(i), math.radians(i * STAR_TURN)
    return r * math.cos(th), r * math.sin(th)


def catmull_rom(pts: list[tuple[float, float]]) -> str:
    """A smooth path through every point (Catmull-Rom, written as cubic Beziers with /6 control points)."""
    d = f"M{n(pts[0][0])} {n(pts[0][1])}"
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, len(pts) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{n(c1[0])} {n(c1[1])} {n(c2[0])} {n(c2[1])} {n(p2[0])} {n(p2[1])}"
    return d


@functools.lru_cache(maxsize=None)
def e_sqrt_binom(s: int, p: float) -> float:
    """E[sqrt X] for X ~ Binomial(s, p), summed term by term from the log-pmf. Terms more than 40 standard
    deviations from the mean are below e^-700 and are left out; that changes no printed digit."""
    mu, sd = s * p, math.sqrt(s * p * (1 - p))
    lo, hi = max(1, math.floor(mu - 40 * sd - 40)), min(s, math.ceil(mu + 40 * sd + 40))
    lc, lp, lq = math.lgamma(s + 1), math.log(p), math.log1p(-p)
    return sum(math.exp(lc - math.lgamma(k + 1) - math.lgamma(s - k + 1) + k * lp + (s - k) * lq) * math.sqrt(k)
               for k in range(lo, hi + 1))


def fidelity_floor(s: int, k: int = QUANTUM["K"]) -> float:
    """shotfloor's closed form for a flawless device against a uniform target over k outcomes after s shots:
    E[BC]^2 with E[BC] = sqrt(k/s) * E[sqrt X], X ~ Binomial(s, 1/k). By Jensen it is a lower bound on the mean
    Hellinger fidelity E[BC^2], so the page labels it E[BC]² and never calls it the expected fidelity."""
    bc = math.sqrt(k / s) * e_sqrt_binom(s, 1 / k)
    return bc * bc


def shots_for(target: float, k: int = QUANTUM["K"]) -> int:
    """The fewest shots whose E[BC]^2 reaches target, by bisection on [1, 2^16] (shotfloor's answer)."""
    lo, hi = 1, 1 << 16
    must(fidelity_floor(hi, k) >= target, f"{target} is not reached within 2^16 shots")
    while lo < hi:
        mid = (lo + hi) // 2
        if fidelity_floor(mid, k) >= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def splitmix64(seed: int):
    """Steele, Lea and Flood's splitmix64: specified by its own arithmetic, so the draw does not depend on Python."""
    x = seed & (2 ** 64 - 1)
    while True:
        x = (x + 0x9E3779B97F4A7C15) & (2 ** 64 - 1)
        z = x
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & (2 ** 64 - 1)
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & (2 ** 64 - 1)
        yield z ^ (z >> 31)


def shot_draw(seed: int, k: int, shots: int) -> list[int]:
    """One outcome per shot: the top log2(k) bits of each splitmix64 value."""
    bits = k.bit_length() - 1
    must(1 << bits == k, "the number of outcomes must be a power of two")
    g = splitmix64(seed)
    return [next(g) >> (64 - bits) for _ in range(shots)]


def counts_of(draw: list[int], k: int) -> list[int]:
    c = [0] * k
    for x in draw:
        c[x] += 1
    return c


def bc2(counts: list[int], s: int, k: int) -> float:
    """Hellinger fidelity of one run against the uniform target: (sum sqrt(c_i/s * 1/k))^2."""
    return sum(math.sqrt(c / s / k) for c in counts) ** 2


def backbone() -> list[tuple[float, float, float]]:
    """A C-alpha trace from textbook geometry (schematic): helix along x, a loop down, strand 1 back toward the
    start, a tight turn, strand 2 antiparallel. Angstroms."""
    P = PROTEIN
    pts = []
    for i in range(P["helix"]):
        a = math.radians(P["deg"] * i)
        pts.append((P["rise"] * i, P["radius"] * math.cos(a), P["radius"] * math.sin(a)))
    x0, y0, z0 = pts[-1]
    for i in range(1, P["loop"] + 1):
        a = math.pi / 2 * i / P["loop"]
        pts.append((x0 + 3.2 * math.sin(a), y0 - 3.2 * (1 - math.cos(a)) - 1.2 * i, z0))
    x1, y1, z1 = pts[-1]
    for i in range(1, P["strand"] + 1):
        pts.append((x1 - P["strand_step"] * i, y1 - 1.0 + (P["pleat"] if i % 2 else -P["pleat"]), z1))
    x2, y2, z2 = pts[-1]
    for i in range(1, P["turn"] + 1):
        a = math.pi * i / P["turn"]
        pts.append((x2 - 2.4 * math.sin(a), y2 - 2.4 * (1 - math.cos(a)), z2))
    x3, y3, z3 = pts[-1]
    for i in range(1, P["strand"] + 1):
        pts.append((x3 + P["strand_step"] * i, y3 + (P["pleat"] if i % 2 else -P["pleat"]), z3))
    return pts


def wave(i: int, k: int) -> float:
    """Schematic waveform bar i of k, 0..1: a few incommensurate sines under a breathing envelope."""
    x = i / (k - 1)
    env = math.sin(math.pi * x) ** 0.6 * (0.55 + 0.45 * math.sin(6 * math.pi * x) ** 2)
    v = abs(0.6 * math.sin(37 * x) + 0.3 * math.sin(91 * x + 1) + 0.25 * math.sin(173 * x + 2)) * env
    return min(1.0, v)


# ------------------------------------------------------------ facts ----
def protein_facts() -> dict:
    P = PROTEIN
    pts = backbone()
    must(len(pts) == P["helix"] + P["loop"] + 2 * P["strand"] + P["turn"], "backbone length")
    return dict(residues=len(pts), per_turn=f"{360 / P['deg']:.1f}", rise=f"{P['rise']:.1f}",
                step=f"{P['strand_step']:.1f}", bar=10)


def quantum_facts() -> dict:
    Q = QUANTUM
    k, s = Q["K"], Q["shots"]
    draw = shot_draw(Q["seed"], k, s)
    frames = list(Q["frames"]) + [s]
    must(frames == sorted(frames) and frames[-1] == s, "quantum frames")
    counts = {f: counts_of(draw[:f], k) for f in frames}
    lo, hi = Q["axis"]
    return dict(K=k, shots=s, seed=Q["seed"], clip=Q["clip"], frames=frames, counts=counts,
                F={f: fidelity_floor(f, k) for f in frames}, run=bc2(counts[s], s, k),
                empty=counts[s].count(0), s95=shots_for(0.95, k), axis=(lo, hi),
                F_lo=fidelity_floor(lo, k), F_hi=fidelity_floor(hi, k))


def check_trigalign(doc: dict) -> dict:
    """data/trigalign.json: the drawn fields of one captured trigalign run, checked against themselves."""
    must(isinstance(doc, dict) and doc.get("logs"), "trigalign.json: no logs")
    must("ds004621" in str(doc.get("source", "")) and "CC0" in str(doc.get("source", "")),
         "trigalign.json: source must name OpenNeuro ds004621 and its CC0 licence")
    log0 = doc["logs"][0]
    pairs, unmatched, seg = log0["pairs"], log0["unmatched"], log0["segments"][0]
    must(log0["n_paired"] == len(pairs), "trigalign.json: n_paired != len(pairs)")
    must(log0["n_events"] - log0["n_paired"] == len(unmatched), "trigalign.json: unmatched count")
    must(len(pairs) >= 2, "trigalign.json: too few pairs to draw")
    res = [p["residual_ms"] for p in pairs]
    must(abs(statistics.pstdev(res) - seg["residual_sd_ms"]) <= 0.01, "trigalign.json: residual sd does not recompute")
    must(abs(max(abs(r) for r in res) - seg["residual_max_ms"]) <= 0.01, "trigalign.json: residual max does not recompute")
    must(all(a["time"] < b["time"] and a["trigger_time"] < b["trigger_time"] for a, b in zip(pairs, pairs[1:])),
         "trigalign.json: pairs are not in time order")
    return doc


def brains_facts(doc: dict) -> dict:
    log0 = doc["logs"][0]
    pairs, seg = log0["pairs"], log0["segments"][0]
    miss = log0["unmatched"][0] if log0["unmatched"] else None
    orphans = doc.get("unpaired_triggers") or []
    lo_log = math.floor(min(p["time"] for p in pairs) / 10) * 10
    lo_eeg = math.floor((lo_log + seg["offset_s"]) / 10) * 10
    top_log = max([p["time"] for p in pairs] + ([miss["time"]] if miss else []))
    top_eeg = max([p["trigger_time"] for p in pairs] + [o["time"] for o in orphans]
                  + ([miss["expected_trigger_time"]] if miss else []))
    span = math.ceil(max(top_log - lo_log, top_eeg - lo_eeg) / 10) * 10
    return dict(pairs=pairs, miss=miss, orphans=orphans, n_events=log0["n_events"], n_paired=log0["n_paired"],
                lost=log0["n_events"] - log0["n_paired"], sd=f"{seg['residual_sd_ms']:.2f}",
                mx=f"{seg['residual_max_ms']:.2f}", drift=f"{seg['drift_ppm']:.0f}", offset=f"{seg['offset_s']:.1f}",
                axis=f"{math.ceil(seg['residual_max_ms'] * 10) / 10:.1f}", lo_log=lo_log, lo_eeg=lo_eeg, span=span,
                expected=f"{miss['expected_trigger_time']:.2f}" if miss else None,
                log_time=f"{miss['time']:.3f}" if miss else None,
                paused=bool(miss and miss.get("on_marker") == "New Segment"))


def area_map(issues: list, areas_doc: dict) -> dict[str, str]:
    """Repository -> area, by the same rule the stats step uses."""
    hand = {r.lower(): a for r, a in areas_doc.items()}
    titles: dict[str, list] = {}
    for i in issues:
        titles.setdefault(i["repo"], []).append(i["title"])
    return {r: area_of(r, hand, t)[0] for r, t in titles.items()}


def star_rows(m: dict, issues: list) -> list[tuple[str, list[dict]]]:
    """(area, stars in filing order), largest area first, each star one issue: its state and fix."""
    fixed = {k: f for f in m["fixes"] for k in f["closes"]}
    order = {k: i for i, k in enumerate(k for f in m["fixes"] for k in f["closes"])}   # merge order
    by_area: dict[str, list] = {a["bucket"]: [] for a in m["areas"]}
    for filed, it in enumerate(sorted(issues, key=lambda i: (i["created_at"], i["repo"].lower(), i["number"]))):
        key = f"{it['repo']}#{it['number']}"
        f = fixed.get(key)
        kind = ("own" if f["own"] else "others") if f else ("nofix" if it["state"] == "closed" else "open")
        must(m["area_of"][it["repo"]] in by_area, f"{key}: its area is not among the ecosystems")
        by_area[m["area_of"][it["repo"]]].append(dict(key=key, kind=kind, rank=order.get(key), order=filed))
    rows = [(a["bucket"], by_area[a["bucket"]]) for a in m["areas"]]
    for (area, stars), a in zip(rows, m["areas"]):
        must(area in STAR_LABELS, f"constellation: area {area!r} has no entry in STAR_LABELS")
        must(len(STAR_LABELS[area]) <= STAR_LABEL_MAX, f"constellation: label for {area!r} is too long")
        must(len(stars) == a["issues"], f"constellation: {area} has {len(stars)} stars, ecosystems says {a['issues']}")
    kinds = [s["kind"] for _, st in rows for s in st]
    o = dict(m["outcome"])
    must(len(kinds) == m["total"], "constellation: stars != issues.total")
    must(all(kinds.count(k) == o[k] for k in o), "constellation: star kinds != outcomes")
    must(sum(1 for _, st in rows for s in st if s["rank"] is not None) == m["fixed"], "constellation: lit != fixed")
    return rows


def fix_rows(m: dict, issues: list) -> list[dict]:
    """One row per fixed issue, in filing order, its hours re-derived from created_at and merged_at."""
    by_key = {f"{i['repo']}#{i['number']}": i for i in issues}
    rows = []
    for f in m["fixes"]:
        for k, table_hours in zip(f["closes"], f["hours"]):
            created = by_key[k]["created_at"]
            hrs = hours_between(created, f["merged_at"])
            must(f"{hrs:.1f}" == f"{table_hours:.1f}", f"analyzer: {k} re-derives to {hrs} h, the table says {table_hours}")
            rows.append(dict(key=k, label=f"{short(k.rsplit('#', 1)[0])}#{k.rsplit('#', 1)[1]}", created=created,
                             merged=f["merged_at"], hours=hrs, own=f["own"]))
    rows.sort(key=lambda r: (r["created"], r["key"].lower()))
    others = [r["hours"] for r in rows if not r["own"]]
    if others:
        must(round(statistics.median(others), 1) == m["lag"]["median"], "analyzer: median does not re-derive")
    daily: dict[str, int] = {}
    for i in issues:
        daily[i["created_at"][:10]] = daily.get(i["created_at"][:10], 0) + 1
    must(daily == m["d"]["issues"]["daily_utc"], "analyzer: per-day filings differ from issues.daily_utc")
    must(sum(daily.values()) == m["total"], "analyzer: CH0 != issues.total")
    return rows


# ------------------------------------------------------------ header ----
def picto(kind: str, t: dict) -> str:
    """A legend symbol for one stop, drawn about the origin in a 40-unit box. It draws no data."""
    s0 = f'fill="none" stroke="{t["fg"]}" stroke-linecap="round" stroke-linejoin="round"'
    s = s0 + ' stroke-width="2"'
    a = f'stroke="{t["accent"]}"'
    x, cy, cx = -16, 0, 0
    if kind == "proteins":
        d = "M" + " L".join(f"{n(x + 32 * i / 40)} {n(9 * math.sin(i / 40 * 4 * math.pi) * (0.6 + 0.4 * math.cos(i / 40 * 4 * math.pi + 1)))}"
                            for i in range(41))
        return f'<path {s} d="{d}"/>'
    if kind == "brains":
        return (f'<path {s} d="M{x} {cy}h5l3-9 4 17 3-12 3 4h6"/>'
                f'<path fill="none" {a} stroke-width="2" stroke-dasharray="2 2.5" d="M{x + 28} {cy - 10}v20"/>')
    if kind == "quantum":
        hs = [12, 20, 9, 16, 22, 11]
        d = "".join(f"M{n(x + 2 + i * 5.6)} {cy + 13}v{-hh}" for i, hh in enumerate(hs))
        return f'<path {s} d="{d}"/><path fill="none" {a} stroke-width="1.6" stroke-dasharray="2.5 2" d="M{x} {cy - 3}h32"/>'
    if kind == "classrooms":
        dots = "".join(f'<circle cx="{n(x + 4 + 8 * (i % 4))}" cy="{n(cy - 6 + 9 * (i // 4))}" r="2.3" fill="{t["fg"]}"/>'
                       for i in range(8))
        return f'<path {s} d="M{x} {cy - 14}h32"/>{dots}'
    if kind == "street safety":                             # a shield whose middle is one shell plate: TurtleShell
        hexa = " ".join(f"{n(cx + 5.5 * math.cos(math.radians(60 * j + 30)))},"
                        f"{n(cy + 5.5 * math.sin(math.radians(60 * j + 30)))}" for j in range(6))
        return (f'<path {s} d="M{cx} {cy - 15}L{cx + 12} {cy - 10}V{cy}C{cx + 12} {cy + 8} {cx + 6} {cy + 13} {cx} {cy + 16}'
                f'C{cx - 6} {cy + 13} {cx - 12} {cy + 8} {cx - 12} {cy}V{cy - 10}Z"/>'
                f'<polygon {s0} stroke-width="1.6" points="{hexa}"/>'
                f'<path {s0} stroke-width="1.2" d="M{cx} {cy - 5.5}V{cy - 14}M{cx} {cy + 5.5}V{cy + 15}'
                f'M{cx + 4.8} {cy - 2.8}L{cx + 11} {cy - 6}M{cx - 4.8} {cy - 2.8}L{cx - 11} {cy - 6}'
                f'M{cx + 4.8} {cy + 2.8}L{cx + 10} {cy + 6}M{cx - 4.8} {cy + 2.8}L{cx - 10} {cy + 6}"/>')
    if kind == "buildings":
        return f'<path {s} d="M{x + 2} {cy + 13}V{cy - 1}L{cx} {cy - 15}L{x + 30} {cy - 1}V{cy + 13}ZM{cx - 4} {cy + 13}v-9h8v9"/>'
    if kind == "underwater robot":
        return (f'<path {s} d="M{x + 4} {cy - 5}h18a5 5 0 0 1 0 10h-18a5 5 0 0 1 0-10ZM{x + 12} {cy - 5}v-5h5v5'
                f'M{x + 27} {cy}h4M{x + 31} {cy - 5}v10"/><path {s0} stroke-width="1.4" d="M{x + 1} {cy}h3"/>'
                f'<circle cx="{x + 6}" cy="{cy - 13}" r="1.6" {s0} stroke-width="1.2"/>'
                f'<circle cx="{x + 2}" cy="{cy - 17}" r="1.1" {s0} stroke-width="1"/>')
    if kind == "graders":
        return f'<path {s} d="M{x + 2} {cy}l8 9 18-20"/><path fill="none" {a} stroke-width="2" d="M{x + 22} {cy + 4}l8 8m0-8l-8 8"/>'
    if kind == "music":
        return (f'<path {s} d="M{x + 8} {cy + 10}V{cy - 12}l16-4v18"/><circle cx="{x + 5}" cy="{cy + 10}" r="3.5" {s}/>'
                f'<circle cx="{x + 21}" cy="{cy + 14}" r="3.5" {s}/>')
    raise SystemExit(f"header: no icon for {kind!r}")


def who() -> dict:
    """Name, city and class year, from WHO: the header is the one place the page states them."""
    return dict(WHO)


def art_header(m: dict, t: dict, size: str = "wide") -> str:
    me = who()
    narrow, mid = size == "narrow", size == "mid"
    W, Hh = {"narrow": (NARROW, 540), "mid": (MID, 342), "wide": (WIDE, 390)}[size]
    cmd, out = GREP
    css = art_css(t, (
        f".rt{{fill:none;stroke:{t['ink']};stroke-width:1.6;stroke-dasharray:1;stroke-dashoffset:0;"
        "animation:draw 2.4s ease-in-out .4s both}@keyframes draw{from{stroke-dashoffset:1}}"
        ".st{animation:pop .5s cubic-bezier(.3,1.6,.5,1) both}@keyframes pop{from{opacity:0;transform:scale(.4)}}"
        ".lb{animation:fade .5s ease-out both}@keyframes fade{from{opacity:0}}"
        ".k{animation:key .01s step-end backwards}@keyframes key{from,to{opacity:0}}"
        ".cur{opacity:0;animation:blink 1s step-end 5.94s 4}@keyframes blink{0%{opacity:1}50%{opacity:0}}"))
    s = Svg(t, me["name"], alt("header", m), w=W, h=Hh, frame=False, css=css,
            area=(14, W - 14, 0, Hh - 4))
    s.add(f'<rect width="{W}" height="{Hh}" rx="10" fill="{t["faint"]}"/>')      # the paper
    grid = "".join(f"M{x} 0V{Hh}" for x in range(40, W, 60)) + "".join(f"M0 {y}H{W}" for y in range(30, Hh, 60))
    s.path(grid, extra=f' stroke="{t["line"]}" stroke-opacity=".45" stroke-width=".8"')
    sub = f"{me['city'].lower()} · cs + data science at UW, {me['year']}"
    if narrow:
        s.text(20, 54, me["name"], "nm", 40)
        s.text(20, 80, sub, "m", 14)
        xs, top, cell = [80, 190, 300], 96, 110
        st = []
        for i, stop in enumerate(HEADER_STOPS):
            row, col = divmod(i, 3)
            col = col if row % 2 == 0 else 2 - col          # the route snakes: left to right, back, and again
            st.append((xs[col], top + row * cell + 44, stop, xs[col], top + row * cell + 89, 13))
        d = f"M{st[0][0]} {st[0][1]}"
        for (x0, y0, *_), (x1, y1, *_) in zip(st, st[1:]):
            if y0 == y1:
                d += f" H{x1}"
            else:                                           # a half-loop at the end of a row
                bend = 56 if x0 > 190 else -56
                d += f" C{x0 + bend} {y0} {x1 + bend} {y1} {x1} {y1}"
    else:
        if mid:
            s.text(28, 64, me["name"], "nm", 40)
            s.text(30, 90, sub, "m", 16)
        else:
            s.text(36, 80, me["name"], "nm", 52)
            s.text(38, 114, sub, "m", 22)
        st = []
        edge, y0, lsize = (50, 166, 12) if mid else (62, 196, 16)
        for i, stop in enumerate(HEADER_STOPS):
            x = edge + i * (W - 2 * edge) / (len(HEADER_STOPS) - 1)
            y = y0 + (28 if i % 2 else 0)
            st.append((x, y, stop, x, y + 50 if i % 2 else y - 38, lsize))   # labels alternate above and below
        d = f"M{n(st[0][0])} {n(st[0][1])}"
        for (x0, y0, *_), (x1, y1, *_) in zip(st, st[1:]):
            mx = (x0 + x1) / 2
            d += f" C{n(mx)} {n(y0)} {n(mx)} {n(y1)} {n(x1)} {n(y1)}"
    s.path(d, "rt", ' pathLength="1"')
    for i, (x, y, stop, lx, ly, size) in enumerate(st):
        when = 0.5 + 0.25 * i
        s.mark(x - 27.75, y - 27.75, x + 27.75, y + 27.75, f"station {stop[0]}")
        s.group(transform=f"translate({n(x)} {n(y)})")
        s.group("st", extra=delay(when))
        s.add(f'<circle r="27" fill="{t["bg"]}" stroke="{t["line"]}" stroke-width="1.5"/>')
        s.add(picto(stop[1], t))
        s.end()
        s.end()
        s.text(lx, ly, stop[0], "m c lb", size, extra=delay(when))
    if narrow:
        bx, by, bw, bh, fs, line2 = 20, 430, 340, 64, 14, 26
    elif mid:
        bx, by, bw, bh, fs, line2 = 24, 260, 380, 66, 16, 28
    else:
        bx, by, bw, bh, fs, line2 = 28, 296, 600, 84, 22, 32
    s.add(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="{6 if narrow else 8}" fill="{t["bg"]}" '
          f'stroke="{t["line"]}"/>')
    tx, ty = bx + (14 if narrow or mid else 20), by + (24 if narrow else (26 if mid else 34))
    step = 2.24 / len(cmd)
    body = "".join(f'<tspan class="k"{delay(3.1 + step * (i + 1))}>{escape(ch if ch != ' ' else chr(0xa0), quote=False)}</tspan>'
                   for i, ch in enumerate(cmd))
    s.text(tx, ty, cmd, "", fs, body=body)
    s.text(tx, ty + line2, out, "a k", fs, extra=delay(3.1 + 2.24 + 0.5))
    adv = 0.6 * fs
    s.add(f'<rect class="cur" x="{n(tx + len(out) * adv + 6)}" y="{n(ty + line2 - fs * .78)}" width="{n(fs * .55)}" '
          f'height="{n(fs)}" fill="{t["accent"]}"/>')
    if narrow:
        s.text(W - 20, by + bh + 26, "icons, not data", "m e")
    else:
        s.text(W - (24 if mid else 28), by + bh - 8, "icons, not data", "m e")
    return s.done()


# ------------------------------------------------------------ cards ----
def card_head(s: Svg, kicker: str, big: str, unit: str, line: str, line_cls: str = "m") -> None:
    s.text(PAD, 24, kicker, "m")
    if unit:
        s.readout(PAD, big, unit)
    else:
        s.text(PAD, 56, big, "", BIG)
    s.text(PAD, 76, line, line_cls)


def art_proteins(m: dict, t: dict) -> str:
    pf = m["protein"]
    pts = backbone()
    L, R = PAD, CARD - PAD
    xs_ = [q[0] + 0.9 * q[2] for q in pts]                 # oblique view: depth shifts x, so the helix reads as a coil
    ys_ = [-q[1] for q in pts]
    top, bot = 96, 226
    sx = min((R - L - 40) / (max(xs_) - min(xs_)), (bot - top - 24) / (max(ys_) - min(ys_)))
    cx0 = (L + R) / 2 - (max(xs_) + min(xs_)) / 2 * sx
    cy0 = (top + bot) / 2 - (max(ys_) + min(ys_)) / 2 * sx
    P = [(cx0 + x * sx, cy0 + y * sx) for x, y in zip(xs_, ys_)]
    o1, o2, o3 = (.10, .14, .20) if is_dark(t) else (.05, .07, .10)
    css = art_css(t, (
        f".bl{{fill:{t['ink']}}}.r1{{opacity:{n(o1)}}}.r2{{opacity:{n(o2)}}}.r3{{opacity:{n(o3)}}}"
        f".tr{{fill:none;stroke:{t['accent']};stroke-width:2.2;stroke-linejoin:round;stroke-linecap:round;"
        "stroke-dasharray:1;stroke-dashoffset:0;animation:draw 2.6s ease-in-out 1.2s both}"
        "@keyframes draw{from{stroke-dashoffset:1}}"
        ".ca{animation:pop .3s ease-out both}@keyframes pop{from{opacity:0}}"
        ".hz{animation:sharpen 1.2s ease-out both}@keyframes sharpen{from{opacity:.25}}"))
    s = Svg(t, "proteins: a backbone drawn out of a blur (schematic)", alt("proteins", m), css=css)
    card_head(s, "proteins · DAIS lab, DeepTracer", "map → trace", "", "cryo-EM map in, 3D backbone out")
    s.mark(min(x for x, _ in P) - 15, min(y for _, y in P) - 15, max(x for x, _ in P) + 15,
           max(y for _, y in P) + 15, "density")
    s.group("hz")
    for r, cls in ((15, "r1"), (10, "r2"), (6, "r3")):
        s.add(f'<g class="bl {cls}">' + "".join(f'<circle cx="{n(x)}" cy="{n(y)}" r="{r}"/>' for x, y in P) + "</g>")
    s.end()
    s.path(catmull_rom(P), "tr", ' pathLength="1"')
    for i, (x, y) in enumerate(P):
        s.circle(x, y, 2.1, t["bg"], t["accent"], 1.2, "ca", extra=delay(1.2 + 2.6 * i / len(P)))
    yb = 250
    bar = pf["bar"] * sx
    s.path(f"M{L} {yb - 4}h{n(bar)}", extra=f' stroke="{t["fg"]}" stroke-width="1.5"')
    s.mark(L, yb - 6, L + bar, yb - 2, "scale bar")
    s.text(L + bar + 6, yb, f"{pf['bar']} Å", "m")
    s.text(R, yb, "helix · loop · hairpin", "m e")
    s.text(L, 270, f"{pf['per_turn']} residues/turn, {pf['rise']} Å rise,", "m")
    s.text(L, 286, f"{pf['step']} Å strand step", "m")
    s.text(L, 308, "schematic, not data: textbook geometry,", "w")
    s.text(L, 324, "a pretend map, no real structure", "w")
    return s.done()


def art_brains(m: dict, t: dict) -> str:
    b = m["brains"]
    L, R = PAD, CARD - PAD
    xl = lambda v: L + (v - b["lo_log"]) / b["span"] * (R - L)      # noqa: E731  two clocks, equal spans
    xe = lambda v: L + (v - b["lo_eeg"]) / b["span"] * (R - L)      # noqa: E731
    yt, yb = 108, 186
    css = art_css(t, (
        f".th{{stroke:{t['accent']};stroke-opacity:.55;stroke-width:.7;fill:none;stroke-dasharray:1;"
        "stroke-dashoffset:0;animation:draw .5s ease-out both}@keyframes draw{from{stroke-dashoffset:1}}"
        ".gh{animation:blink .45s step-end 3.2s 4}@keyframes blink{50%{opacity:.15}}"))
    s = Svg(t, "brains: one trigger short", alt("brains", m), css=css)
    lost = NUMBER_WORDS.get(b["lost"], str(b["lost"]))
    card_head(s, "brains · trigalign", f"{b['n_paired']} of {b['n_events']}", "events paired",
              f"a public EEG session, {lost} trigger{'s' if b['lost'] != 1 else ''} lost")
    s.text(L, yt - 9, "stimulus log clock", "m")
    s.text(L, yb + 20, "EEG recorder clock", "m")
    s.path(f"M{L} {yt}H{R}M{L} {yb}H{R}", extra=f' stroke="{t["line"]}"')
    ticks_t, ticks_b = [], []
    for i, pr in enumerate(b["pairs"]):
        a, c = xl(pr["time"]), xe(pr["trigger_time"])
        ticks_t.append(f"M{n(a)} {yt - 5}v5")
        ticks_b.append(f"M{n(c)} {yb}v5")
        s.path(f"M{n(a)} {yt}L{n(c)} {yb}", "th", ' pathLength="1"' + delay(0.3 + 2.4 * i / len(b["pairs"])))
    s.path("".join(ticks_t), extra=f' stroke="{t["fg"]}"')
    s.path("".join(ticks_b), extra=f' stroke="{t["fg"]}"')
    for o in b["orphans"]:                                  # a trigger with no log event behind it
        s.circle(xe(o["time"]), yb + 2.5, 3, "none", t["ink"], 1.2)
    if b["orphans"]:                                        # its key, on the image as well as in the alt text
        k = len(b["orphans"])
        s.circle(L + 3, yb + 30, 3, "none", t["ink"], 1.2, what="extra-trigger key")
        s.text(L + 11, yb + 34, f"{k} extra trigger{'s' if k != 1 else ''}", "m")
    if b["miss"]:
        mx, gx = xl(b["miss"]["time"]), xe(b["miss"]["expected_trigger_time"])
        s.group("gh")
        s.path(f"M{n(mx)} {yt - 7}v7", extra=f' stroke="{t["warn"]}" stroke-width="2"')
        s.path(f"M{n(mx)} {yt}L{n(gx)} {yb}", extra=f' stroke="{t["warn"]}" stroke-width="1.2" stroke-dasharray="3 3" fill="none"')
        s.circle(gx, yb + 2.5, 3.5, t["bg"], t["warn"], 1.6)
        s.end()
        s.text(R, yb + 20, f"no trigger at {b['expected']} s", "w e")
        if b["paused"]:
            s.text(R, yb + 34, "(the recording paused)", "w e")
    rt, rb = 248, 292
    mid, ax = (rt + rb) / 2, float(b["axis"])
    runs, cur = [], []
    for a, c in zip([None] + b["pairs"], b["pairs"]):
        if a is not None and c["trigger_time"] - a["trigger_time"] > GAP_S:
            runs.append(cur)
            cur = []
        cur.append(c)
    runs.append(cur)
    s.path(f"M{L} {n(mid)}H{R}", extra=f' stroke="{t["line"]}" stroke-dasharray="2 3"')
    for run in runs:
        s.poly([(xe(p["trigger_time"]), mid - p["residual_ms"] / ax * (rb - rt) / 2) for p in run],
               extra=f' fill="none" stroke="{t["accent"]}" stroke-width="1.1" stroke-linejoin="round"')
    s.text(L, rt - 6, f"not a brainwave: each pair's miss, ±{b['axis']} ms", "m")
    s.text(L, rb + 14, f"sd {b['sd']} ms · max {b['mx']} · drift {b['drift']} ppm", "m")
    s.text(L, H - 10, "real markers: OpenNeuro ds004621 (CC0)", "m")
    return s.done()


def art_quantum(m: dict, t: dict) -> str:
    q = m["quantum"]
    k, S = q["K"], q["shots"]
    L, R = PAD, CARD - PAD
    css = art_css(t, f".bar{{fill:{t['accent']}}}.fq{{opacity:0}}"
                  "@keyframes on{0%,100%{opacity:1}}@keyframes off{0%,100%{opacity:0}}")
    dur = 1.1
    for i, f in enumerate(q["frames"][:-1]):
        css += f".f{f}{{animation:on {n(dur)}s step-end {n(0.4 + i * dur)}s 1}}"
    rest = 0.4 + (len(q["frames"]) - 1) * dur
    css += f".f{S}{{animation:off {n(rest)}s step-end 0s 1}}"
    s = Svg(t, "a flawless quantum computer, 1,024 shots", alt("quantum", m), css=css)
    card_head(s, "quantum · shotfloor", f"{q['F'][S]:.4f}", "not 1", "a flawless device, 8 qubits, uniform")
    top, base = 120, 196
    hgt, clip = base - top, q["clip"]
    bw = (R - L) / k
    s.mark(L, top, R, base, "histogram")
    for f in q["frames"]:
        ideal = f / k
        resting = f == S
        s.group(f"f{f}" + ("" if resting else " fq"))
        d = []
        for i, c in enumerate(q["counts"][f]):
            r = min(c / ideal, clip)
            if r > 0:
                d.append(f"M{n(L + i * bw)} {n(base)}V{n(base - r / clip * hgt)}h{n(bw * 0.78)}V{n(base)}z")
        s.path("".join(d), "bar")
        if resting:
            s.text(R, 98, f"{f:,} shots · this simulated run {q['run']:.4f}", "m e", layer=f)
        else:
            s.text(R, 98, f"{f:,} shots so far", "m e", layer=f)
        s.text(R, 113, f"E[BC]² {q['F'][f]:.4f}", "a e", layer=f)
        s.end()
    yi = base - 1 / clip * hgt
    s.path(f"M{L} {n(yi)}H{R}", extra=f' stroke="{t["warn"]}" stroke-width="1.2" stroke-dasharray="3 3"')
    s.path(f"M{L} {base + .5}H{R}", extra=f' stroke="{t["line"]}"')
    s.path(f"M{L} 109h18", extra=f' stroke="{t["warn"]}" stroke-width="1.2" stroke-dasharray="3 3"')
    s.text(L + 24, 113, "ideal: all equal", "w")
    s.text(L, base + 15, f"{k} outcomes · bar = count / ideal count", "m")
    lo, hi = q["axis"]
    ct, cb = 234, 290
    l2lo, l2hi = math.log2(lo), math.log2(hi)
    xs = lambda v: L + (math.log2(v) - l2lo) / (l2hi - l2lo) * (R - L)   # noqa: E731
    ys = lambda v: cb - (v - 0.2) / 0.8 * (cb - ct)                       # noqa: E731
    must(q["F_lo"] >= 0.2, "quantum: the curve starts below its axis")
    steps = 8 * round(l2hi - l2lo)
    curve = [(xs(2 ** (l2lo + i / 8)), ys(fidelity_floor(round(2 ** (l2lo + i / 8)), k))) for i in range(steps + 1)]
    s.path(f"M{L} {n(ys(1))}H{R}", extra=f' stroke="{t["line"]}" stroke-dasharray="2 3"')
    s.text(R, ys(1) - 4, "1.0", "m e")
    s.poly(curve, extra=f' fill="none" stroke="{t["accent"]}" stroke-width="1.6"')
    for v in (S, q["s95"]):
        s.circle(xs(v), ys(fidelity_floor(v, k)), 3, t["bg"], t["accent"], 1.6)
    s.text(xs(S) + 8, ys(q["F"][S]) + 17, f"{q['F'][S]:.2f} at {S:,}", "a")
    s.text(xs(q["s95"]) + 8, ys(q["F"][S]) + 33, f"0.95 needs {q['s95']:,}", "a")
    s.text(L, cb + 15, f"{lo:,}", "m")
    s.text(R, cb + 15, f"{hi:,} shots (log)", "m e")
    s.text(L, H - 14, f"bars: seed {q['seed']} run · curve: E[BC]² ≤ mean F", "m")
    return s.done()


def art_music(m: dict, t: dict) -> str:
    L, R = PAD, CARD - PAD
    css = art_css(t, (
        f".wv{{fill:{t['accent']};opacity:.85;animation:breathe 1.6s ease-in-out .3s 3}}"
        "@keyframes breathe{50%{transform:scaleY(.55)}}"
        ".cur{opacity:0;animation:blink 1s step-end 1s 5}@keyframes blink{0%{opacity:1}50%{opacity:0}}"))
    s = Svg(t, "music: made often, released never", alt("music", m), css=css)
    card_head(s, "off the clock · music", "made often", "", "released never.")
    mid, amp, k = 140, 48, 120
    bw = (R - L) / k
    s.mark(L, mid - amp, R, mid + amp, "waveform")
    d = []
    for i in range(k):
        hh = max(1.5, wave(i, k) * amp)
        d.append(f"M{n(L + i * bw)} {n(-hh)}h{n(bw * 0.6)}V{n(hh)}h{n(-bw * 0.6)}z")
    s.group(transform=f"translate(0 {mid})")
    s.path("".join(d), "wv")
    s.end()
    s.text(L, 208, "schematic: drawn from a formula,", "w")
    s.text(L, 223, "not a recording", "w")
    ty = 240
    s.add(f'<rect x="{L}" y="{ty}" width="{R - L}" height="76" rx="6" fill="{t["faint"]}" stroke="{t["line"]}"/>')
    s.text(L + 12, ty + 24, "$ ls ~/music/released/", "", 13)
    s.text(L + 12, ty + 44, "(empty)", "m", 13)
    s.text(L + 12, ty + 64, "$", "", 13)
    s.add(f'<rect class="cur" x="{n(L + 12 + 2 * 0.6 * 13)}" y="{ty + 53}" width="8" height="14" fill="{t["accent"]}"/>')
    return s.done()


def art_divider(m: dict, t: dict) -> str:
    stars = sorted((st for _, row in m["stars"] for st in row), key=lambda x: x["order"])
    s = Svg(t, "the issues in the order filed", alt("divider", m), w=WIDE, h=18, frame=False)
    step = (WIDE - 28) / len(stars)
    for i, st in enumerate(stars):
        lit = st["rank"] is not None
        s.circle(14 + (i + 0.5) * step, 9, 4 if lit else 1.8, t["accent"] if lit else t["ink"])
    return s.done()


# ------------------------------------------------------------ stats ----
STAT_GAP, STAT_PAD, STAT_H = 8, 12, 96     # gap between tiles, padding inside one, one tile's height


def stat_tiles(m: dict) -> list[tuple[str, str, str, list[str]]]:
    """The side quest's four numbers as (big, unit, class of the big number, detail lines); every value is checked."""
    o, lag, p, q = dict(m["outcome"]), m["lag"], m["prs"], m["q"]
    return [
        (str(m["total"]), "issues filed", "",
         [f"since {m['start']}", f"{m['repos']} repos, {plural(len(m['areas']), 'area')}"]),
        (str(m["fixed"]), "fixed", "a",
         ["by a merged PR", f"{o['others']} by others, {o['own']} by me" if m["fixed"] else "none yet"]),
        (str(lag["median"]) if lag["median"] is not None else "—", "h median", "",
         ["filed to merged PR", plural(lag["n"], "fix", "fixes") + " by others" if lag["n"] else "no fix by others yet"]),
        (str(p["upstream"]), "PRs upstream", "",
         ["to others' repos", f"{q['prs_merged']} merged, {q['prs_open']} open"]),
    ]


def art_stats(m: dict, t: dict, size: str = "wide") -> str:
    """Four stat tiles: one row on the wide picture, two by two on the mid and phone twins."""
    W, cols = {"wide": (WIDE, 4), "mid": (MID, 2), "narrow": (NARROW, 2)}[size]
    tiles = stat_tiles(m)
    rows = math.ceil(len(tiles) / cols)
    tw = (W - (cols - 1) * STAT_GAP) / cols
    Hh = rows * STAT_H + (rows - 1) * STAT_GAP
    s = Svg(t, "the side quest in four numbers", alt("stats", m), w=W, h=Hh, frame=False, css=art_css(t),
            area=(0, W, 0, Hh))
    for i, (big, unit, cls, lines) in enumerate(tiles):
        r, c = divmod(i, cols)
        x, y = c * (tw + STAT_GAP), r * (STAT_H + STAT_GAP)
        s.add(f'<rect x="{n(x + .5)}" y="{n(y + .5)}" width="{n(tw - 1)}" height="{STAT_H - 1}" rx="6" '
              f'fill="{t["bg"]}" stroke="{t["line"]}"/>')
        room = tw - 2 * STAT_PAD
        need = max([len(big) * BIG * ADV + 7 + len(unit) * T * ADV] + [len(ln) * T * ADV for ln in lines])
        must(need <= room + EPS, f"stats: tile {i + 1} needs {need:.0f} units, has {room:.0f} ({size})")
        b1 = s.box(x + STAT_PAD, y + 38, big, BIG)
        s._place(b1)
        s._place(s.box(b1[1] + 7, y + 38, unit))
        bc = "b" + (f" {cls}" if cls else "")
        s.add(f'<text x="{n(x + STAT_PAD)}" y="{n(y + 38)}"><tspan class="{bc}">{h(big)}</tspan>'
              f'<tspan class="m" dx="7">{h(unit)}</tspan></text>')
        for j, ln in enumerate(lines):
            s.text(x + STAT_PAD, y + 62 + 18 * j, ln, "m")
    return s.done()


# ------------------------------------------------------------ shelf ----
SHELF_GLYPH = 24        # each tool's icon sits in a 24-unit box left of its name


def tool_icon(name: str, t: dict) -> str:
    """A small symbol for one package, drawn about the origin in a 24-unit box. Icons, not data."""
    s = f'fill="none" stroke="{t["fg"]}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
    a = f'fill="none" stroke="{t["accent"]}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
    if name == "tolwatch":          # a value inside a band far wider than it needs
        return (f'<path {s} d="M-10 -7H10M-10 7H10"/><path {a} stroke-dasharray="2 2" d="M-10 -2H10M-10 2H10"/>'
                f'<circle cx="0" cy="0" r="1.6" fill="{t["accent"]}"/>')
    if name == "ziptrace":          # a zipper whose right side runs out of teeth
        teeth = "".join(f"M-6 {y}h4" for y in (-8, -3, 2, 7)) + "".join(f"M2 {y}h4" for y in (-5.5, -0.5))
        return f'<path {s} d="M-2 -11V11M2 -11V11{teeth}"/><path {a} d="M3 5l4 4m0-4l-4 4"/>'
    if name == "unadded":           # a file that git does not track
        return (f'<path {s} stroke-dasharray="3 2.2" d="M-7 -10H3L8 -5V10H-7Z"/>'
                f'<path {a} d="M-2 -1a2.6 2.6 0 1 1 3 2.5V4M1 7.4v.2"/>')
    if name == "whymodified":       # a file marked modified with nothing inside it changed
        return (f'<path {s} d="M-7 -10H3L8 -5V10H-7Z"/><path {s} d="M-3 -1h7M-3 4h7"/>'
                f'<circle cx="6" cy="-8" r="3.2" fill="{t["warn"]}" stroke="{t["bg"]}" stroke-width="1"/>')
    if name == "shotfloor":         # shot-noise bars under an ideal line
        hs = (9, 14, 6, 12, 16, 8)
        d = "".join(f"M{-9 + i * 3.6:.1f} 10v{-hh}" for i, hh in enumerate(hs))
        return f'<path {s} d="{d}"/><path {a} stroke-dasharray="2.4 2" d="M-11 -1H11"/>'
    if name == "trigalign":         # two clocks and the lines that pair them
        thin = a.replace('stroke-width="1.6"', 'stroke-width="1.2"')
        return (f'<path {s} d="M-11 -8H11M-11 8H11"/>'
                f'<path {thin} d="M-8 -8L-6 8M-3 -8L-1 8M2 -8L4 8M7 -8L9 8"/>')
    if name == "scoreprobe":        # a lens over a check mark that should not be there
        return (f'<circle cx="-2" cy="-2" r="7" {s}/><path {s} d="M3 3l7 7"/>'
                f'<path {a} d="M-5.5 -2l2.5 2.5 4.5-5"/>')
    if name == "normladder":        # a ladder of answer-matching rules
        return f'<path {s} d="M-6 -11V11M6 -11V11"/><path {a} d="M-6 -6H6M-6 0H6M-6 6H6"/>'
    if name == "mcqlint":           # four options, one marked twice
        dots = "".join(f'<circle cx="-6" cy="{y}" r="2.4" {s}/><path {s} d="M-1 {y}H10"/>' for y in (-8, -2.7, 2.7))
        return dots + f'<circle cx="-6" cy="8" r="2.4" fill="{t["accent"]}"/><path {a} d="M-1 8H10"/>'
    if name == "tabverify":         # a results table and the one cell that does not add up
        return (f'<path {s} d="M-10 -9H10V9H-10ZM-10 -3H10M-10 3H10M-3 -9V9M4 -9V9"/>'
                f'<path fill="{t["warn"]}" d="M4 3H10V9H4Z"/>')
    raise SystemExit(f"shelf: no icon for {name!r}")


def tool_lines(desc: str, width: float) -> list[str]:
    """A description wrapped to width at 12 units; a `code` span never breaks across lines."""
    chars = int(width // (T * ADV))
    lines, cur = [], ""
    for tok in re.findall(r"`[^`]*`\S*|\S+", desc):
        trial = f"{cur} {tok}" if cur else tok
        if cur and len(trial.replace("`", "")) > chars:
            lines.append(cur)
            cur = tok
        else:
            cur = trial
    lines.append(cur)
    must(all(len(ln.replace("`", "")) <= chars for ln in lines), f"shelf: a word is wider than {width:g} units")
    return lines


def shelf_layout(size: str) -> dict:
    """Card geometry for one width: columns, card width, the text width inside a card."""
    W = {"wide": WIDE, "mid": MID, "narrow": NARROW}[size]
    cols = 1 if size == "narrow" else 2
    gap, edge = 12, 14
    cw = (W - 2 * edge - (cols - 1) * gap) / cols
    return dict(W=W, cols=cols, gap=gap, edge=edge, cw=cw, text_w=cw - 28)


def art_shelf(m: dict, t: dict, size: str = "wide") -> str:
    """The packages from TOOLS as cards under their three headings: an icon, the name, the line from TOOLS."""
    L = shelf_layout(size)
    W, cols, gap, edge, cw = L["W"], L["cols"], L["gap"], L["edge"], L["cw"]
    line_h, name_h, pad_top, pad_bot = 16, 30, 14, 12
    # first pass: the height of every row of cards, so a row's cards share one height
    plan, y = [], 6.0
    for group, items in TOOLS:
        plan.append(("head", group, y + 12))
        y += 26
        for r in range(0, len(items), cols):
            row = items[r:r + cols]
            wrapped = [tool_lines(d, L["text_w"]) for _, d in row]
            hh = pad_top + name_h + max(len(w) for w in wrapped) * line_h + pad_bot - 4
            plan.append(("row", [(nm, w) for (nm, _), w in zip(row, wrapped)], y, hh))
            y += hh + gap
        y += 6
    Hh = y - gap - 6 + 2                         # the last card's frame, and nothing below it
    css = art_css(t, ".cd{animation:rise .5s ease-out both}@keyframes rise{from{opacity:0;transform:translateY(6px)}}")
    s = Svg(t, "things i made", alt("shelf", m), w=W, h=Hh, frame=False, css=css, area=(edge, W - edge, 0, Hh - 2))
    k = 0
    for item in plan:
        if item[0] == "head":
            s.text(edge + 2, item[2], item[1], "m", 13)
            s.path(f"M{n(edge + 2 + len(item[1]) * 13 * ADV + 10)} {n(item[2] - 4.5)}H{n(W - edge)}",
                   extra=f' stroke="{t["line"]}" fill="none"')
            continue
        _, row, top, hh = item
        for c, (name, lines) in enumerate(row):
            x = edge + c * (cw + gap)
            s.group("cd", extra=delay(0.15 + 0.12 * k))
            s.add(f'<rect x="{n(x + .5)}" y="{n(top + .5)}" width="{n(cw - 1)}" height="{n(hh - 1)}" rx="6" '
                  f'fill="{t["bg"]}" stroke="{t["line"]}"/>')      # a frame for its own text, not a mark
            gx, gy = x + 14 + SHELF_GLYPH / 2, top + pad_top + SHELF_GLYPH / 2 - 2
            s.add(f'<g transform="translate({n(gx)} {n(gy)})">{tool_icon(name, t)}</g>')
            s.mark(gx - 12, gy - 12, gx + 12, gy + 12, f"icon {name}")
            s.text(x + 14 + SHELF_GLYPH + 10, top + pad_top + 15, name, "nm", 16)
            for i, ln in enumerate(lines):
                yy = top + pad_top + name_h + 12 + i * line_h
                body = re.sub(r"`([^`]*)`", r'<tspan class="a">\1</tspan>', escape(ln, quote=False))
                s.text(x + 14, yy, ln.replace("`", ""), "", T, body=body)
            s.end()
            k += 1
    return s.done()


# ------------------------------------------------------------ constellation ----
def sparkle(cx: float, cy: float, r: float) -> str:
    k = r * 0.28
    return (f"M{n(cx)} {n(cy - r)}Q{n(cx + k)} {n(cy - k)} {n(cx + r)} {n(cy)}Q{n(cx + k)} {n(cy + k)} {n(cx)} {n(cy + r)}"
            f"Q{n(cx - k)} {n(cy + k)} {n(cx - r)} {n(cy)}Q{n(cx - k)} {n(cy - k)} {n(cx)} {n(cy - r)}Z")


def art_constellation(m: dict, t: dict, size: str = "wide") -> str:
    rows, o = m["stars"], dict(m["outcome"])
    narrow = size != "wide"                      # mid and narrow share the stacked layout, at two widths
    cols, cw, ch, head, size = {"narrow": (3, 117, 156, 138, 13), "mid": (4, 130, 156, 138, 13),
                                "wide": (5, 160, 160, 96, 14)}[size]
    step = 6.5 if narrow else STAR_STEP          # the stacked twins pack each cluster a little tighter
    nrows = math.ceil(len(rows) / cols)
    W = {3: NARROW, 4: MID, 5: WIDE}[cols]
    legend = 76 if narrow else 64
    Hh = head + nrows * ch + legend
    x_off = (W - cols * cw) / 2
    css = art_css(t, (
        f".op{{fill:{t['ink']}}}.ln{{fill:none;stroke:{t['line']};stroke-width:1}}"
        ".sky{animation:fade 1.2s ease-out both}@keyframes fade{from{opacity:0}}"
        ".lit{animation:lit 1.4s ease-out both}"
        "@keyframes lit{0%{opacity:0;transform:scale(.2)}60%{opacity:1;transform:scale(1.35)}100%{transform:scale(1)}}"))
    s = Svg(t, f"{m['total']} issues as stars", alt("constellation", m), w=W, h=Hh,
            frame=False, css=css, area=(14, W - 14, 0, Hh - 4))
    frame(s, W, Hh)
    lit_line = f"lit = fixed by a merged PR: {m['fixed']}"
    where = f"{plural(m['repos'], 'repository', 'repositories')} in {plural(len(rows), 'area')};"
    if W == MID:
        s.readout(18, str(m["total"]), "issues, one star each", y=44, size=30, gap=8)
        s.text(18, 70, lit_line, "m")
        s.text(18, 94, where, "m", 13)
        s.text(18, 112, "lines join an area's issues in the order filed", "m", 13)
    elif narrow:
        s.readout(18, str(m["total"]), "issues, one star each", y=44, size=30, gap=8)
        s.text(18, 70, lit_line, "m")
        s.text(18, 94, where, "m", 13)
        s.text(18, 112, "lines join an area's issues in", "m", 13)
        s.text(18, 130, "the order filed", "m", 13)
    else:
        s.readout(28, str(m["total"]), "issues, one star each", y=50, size=30, gap=10)
        s.text(W - 28, 50, lit_line, "m e", 14)
        s.text(28, 76, f"{where[:-1]}; lines join an area's issues in the order filed", "m", 14)
    sky, lit = [], []
    for idx, (area, stars) in enumerate(rows):
        r_, c_ = divmod(idx, cols)
        cx = x_off + cw * (c_ + 0.5)
        cy = head + ch * r_ + (58 if narrow else 70)
        pos = [(cx + dx, cy + dy) for dx, dy in (golden(i, step) for i in range(len(stars)))]
        sky.append(f'<path class="ln" d="M{" L".join(f"{n(x)} {n(y)}" for x, y in pos)}"/>')
        for (x, y), st in zip(pos, stars):
            rr = 12.5 if st["kind"] == "own" else (11 if st["kind"] == "others" else 3.2)
            s.mark(x - rr, y - rr, x + rr, y + rr, f"star {st['key']}")
            if st["kind"] == "open":
                sky.append(f'<circle class="op" cx="{n(x)}" cy="{n(y)}" r="2.2"/>')
            elif st["kind"] == "nofix":
                sky.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="3.2" fill="{t["bg"]}" stroke="{t["ink"]}" stroke-width="1.3"/>')
            else:
                ring = (f'<circle r="12.5" fill="none" stroke="{t["accent"]}" stroke-width="1.3"/>'
                        if st["kind"] == "own" else "")
                lit.append(f'<g transform="translate({n(x)} {n(y)})"><g class="lit"{delay(1.2 + 0.22 * st["rank"])}>'
                           f'<circle r="11" fill="{t["accent"]}" fill-opacity=".16"/>'
                           f'<path d="{sparkle(0, 0, 7.5)}" fill="{t["accent"]}"/>{ring}</g></g>')
        label = STAR_LABELS_NARROW.get(area, STAR_LABELS[area]) if W == NARROW else STAR_LABELS[area]
        yl = head + ch * (r_ + 1) - 14
        if narrow:
            sky.append(("text", cx, yl - 16, label, "c m", size))
            sky.append(("text", cx, yl, str(len(stars)), "c", size))
        else:
            sky.append(("text", cx, yl, f"{label} {len(stars)}", "c m", size))
    s.group("sky")
    for item in sky:
        if isinstance(item, tuple):
            s.text(item[1], item[2], item[3], item[4], item[5])
        else:
            s.add(item)
    s.end()
    for g in lit:
        s.add(g)
    # legend: one mark and one count per kind
    items = [("open", f"open {o['open']}"), ("nofix", f"closed, no fix {o['nofix']}"),
             ("others", f"fixed by others {o['others']}"), ("own", f"fixed by me {o['own']}")]
    lines = [items[:2], items[2:]] if narrow else [items]
    ly0 = Hh - legend + (28 if narrow else 38)
    for li, line in enumerate(lines):
        x, y = (22 if narrow else 30), ly0 + li * 28
        for kind, label in line:
            gx = x + 8
            if kind == "open":
                s.circle(gx, y - 5, 2.2, t["ink"])
            elif kind == "nofix":
                s.circle(gx, y - 5, 3.2, t["bg"], t["ink"], 1.3)
            else:
                s.path(sparkle(gx, y - 5, 7), extra=f' fill="{t["accent"]}"')
                if kind == "own":
                    s.circle(gx, y - 5, 10.5, "none", t["accent"], 1.3)
            s.mark(gx - 12, y - 17, gx + 12, y + 7, f"legend {kind}")
            s.text(gx + 16, y, label, "m", size)
            x = gx + 16 + len(label) * size * ADV + (22 if narrow else 34)
    return s.done()


# ------------------------------------------------------------ analyzer ----
def art_analyzer(m: dict, t: dict, size: str = "wide") -> str:
    rows, lag = m["fixrows"], m["lag"]
    narrow, mid = size == "narrow", size == "mid"       # mid: the wide rows under the narrow head, 560 across
    W = {"narrow": AN_NARROW, "mid": MID, "wide": WIDE}[size]
    t0 = dt.datetime.combine(m["start"], dt.time(), dt.timezone.utc)
    t1 = dt.datetime.combine(m["end"] + dt.timedelta(days=1), dt.time(), dt.timezone.utc)
    span = (t1 - t0).total_seconds()
    if narrow:
        top, row_h, px0, px1, ch0 = 112, 34, 14, W - 14, 40
    elif mid:
        top, row_h, px0, px1, ch0 = 92, 20, 196, W - 82, 30
    else:
        top, row_h, px0, px1, ch0 = 76, 20, 210, W - 84, 30
    rows_top = top + ch0
    axis_y = rows_top + len(rows) * row_h + 8
    Hh = axis_y + (60 if size == "wide" else 72)
    X = lambda s_: px0 + (ts(s_) - t0).total_seconds() / span * (px1 - px0)   # noqa: E731
    sweep = px1 - px0
    # the cover shrinks toward the plot's right edge instead of sliding, so it never leaves the plot or hides the frame
    css = art_css(t, (
        f".hl{{stroke:{t['bg']};stroke-width:4px;stroke-linejoin:round;paint-order:stroke}}"   # text over grid lines
        f".sw{{transform-origin:{n(px1)}px 0;transform:scaleX(0);animation:shrink 4.2s linear .3s both}}"
        "@keyframes shrink{from{transform:scaleX(1)}to{transform:scaleX(0)}}"
        f".cu{{transform:translateX({n(sweep)}px);opacity:0;animation:sweep 4.2s linear .3s both}}"
        f"@keyframes sweep{{from{{transform:translateX(0);opacity:1}}98%{{opacity:1}}"
        f"to{{transform:translateX({n(sweep)}px);opacity:0}}}}"))
    s = Svg(t, "report to fix, as a logic analyzer", alt("analyzer", m), w=W, h=Hh, frame=False, css=css,
            area=(14, W - 14, 0, Hh - 4))
    frame(s, W, Hh)
    med = lag["median"]
    summary = f"{m['total']} filed · {m['fixed']} fixed" + (f" · median wait {med} h" if med is not None else "")
    if narrow:
        s.text(18, 30, "report → fix", "", 16)
        s.text(18, 50, "high = waiting: from the report until", "m")
        s.text(18, 66, "a merged PR closed it.", "m")
        s.text(18, 86, summary, "m")
        ly = 104
        s.path(f"M18 {ly - 4}h16", extra=f' stroke="{t["accent"]}" stroke-width="1.6"')
        s.text(40, ly, "fixed by someone else", "m")
        s.circle(W - 112, ly - 4, 3.6, "none", t["fg"], 1.4)
        s.text(W - 104, ly, "by my own PR", "m")
    elif mid:
        s.text(20, 30, "report → fix", "", 16)
        s.text(W - 20, 30, summary, "m e")
        s.text(20, 54, "high = waiting: from the report until a merged PR closed it.", "m")
        ly = 76
        s.path(f"M20 {ly - 4}h16", extra=f' stroke="{t["accent"]}" stroke-width="1.6"')
        s.text(42, ly, "fixed by someone else", "m")
        s.circle(220, ly - 4, 3.6, "none", t["fg"], 1.4)
        s.text(228, ly, "by my own PR", "m")
    else:
        s.text(20, 30, "report → fix", "", 16)
        s.text(W - 20, 30, summary, "m e")
        s.text(20, 54, "high = waiting: from the report until a merged PR closed it.", "m")
        own_w = len("by my own PR") * T * ADV
        s.text(W - 20, 54, "by my own PR", "m e")
        s.circle(W - 20 - own_w - 10, 50, 3.6, "none", t["fg"], 1.4)
        lab = "fixed by someone else"
        x2 = W - 20 - own_w - 26
        s.text(x2, 54, lab, "m e")
        s.path(f"M{n(x2 - len(lab) * T * ADV - 24)} 50h16", extra=f' stroke="{t["accent"]}" stroke-width="1.6"')
    # traces first, then the sweep cover, then everything that must never be hidden
    y = top + 4
    tick_top = y + (16 if narrow else 8)
    ticks = "".join(f"M{n(X(c))} {n(y + ch0 - 8)}V{n(tick_top)}" for c in m["created"])
    s.path(ticks, extra=f' stroke="{t["ink"]}" stroke-width="1"')
    s.path(f"M{px0} {n(y + ch0 - 7.5)}H{px1}", extra=f' stroke="{t["line"]}"')
    for i, r in enumerate(rows):
        ry = rows_top + i * row_h
        hi_y, lo_y = (ry + 14, ry + 28) if narrow else (ry + 4, ry + 15)
        col = t["fg"] if r["own"] else t["accent"]
        xa, xb = X(r["created"]), X(r["merged"])
        s.path(f"M{px0} {n(lo_y)}H{n(xa)}V{n(hi_y)}H{n(xb)}V{n(lo_y)}H{px1}",
               extra=f' stroke="{col}" stroke-width="1.6" fill="none"')
        if r["own"]:
            s.circle(xb, lo_y, 3.6, t["bg"], col, 1.4)
        else:
            s.circle(xb, lo_y, 2.4, col)
    cover_top, cover_bot = top - 2, rows_top + len(rows) * row_h
    s.add(f'<rect class="sw" x="{px0}" y="{cover_top}" width="{n(px1 - px0)}" height="{n(cover_bot - cover_top)}" '
          f'fill="{t["bg"]}"/>')
    s.path(f"M{px0} {cover_top}V{n(cover_bot)}", "cu", f' stroke="{t["accent"]}" stroke-width="2"')
    # day (or week, or month) graticule, labels and hours sit above the cover
    unit, spans = m["unit"], m["spans"]
    starts = [X(a.isoformat() + "T00:00:00Z") for a, _ in spans]
    grid = "".join(f"M{n(x)} {top - 2}V{n(axis_y)}" for x in starts if px0 <= x <= px1)
    s.path(grid + f"M{px1} {top - 2}V{n(axis_y)}", extra=f' stroke="{t["line"]}" stroke-opacity=".6"')
    xs_asof = X(m["as_of"].replace("Z", ":00Z"))
    s.path(f"M{n(xs_asof)} {top - 2}V{n(axis_y)}", extra=f' stroke="{t["muted"]}" stroke-dasharray="2 3"')
    if narrow:
        s.text(px0, y + 9, "CH0 every report", "m hl")
    else:
        s.text(20, y + ch0 - 10, "CH0 every report", "m hl", 13)
    for i, r in enumerate(rows):
        ry = rows_top + i * row_h
        cls = "hl" if r["own"] else "m hl"
        if narrow:
            s.text(px0, ry + 9, r["label"], cls)
            s.text(min(px1, xs_asof) - 6, ry + 9, f"{r['hours']:.1f} h", cls + " e")   # left of the as-of line
        else:
            s.text(20, ry + 15, r["label"], cls, 13)
            s.text(W - 20, ry + 15, f"{r['hours']:.1f} h", cls + " e", 13)
    fmt = {"day": mmdd, "week": mmdd, "month": lambda x: x.strftime("%Y-%m")}[unit]
    slot = (px1 - px0) / len(spans)
    lab_w = len(fmt(spans[0][0])) * T * ADV
    every = max(1, math.ceil((lab_w + 8) / slot))
    for i in range(0, len(spans), every):
        a, z = spans[i]
        cx = starts[i] + slot / 2 if unit == "day" else max(px0, starts[i])
        anchor = "c" if unit == "day" else ""
        if s.free(s.box(cx, axis_y + 14, fmt(a), T, "middle" if anchor else "start"), 4):
            s.text(cx, axis_y + 14, fmt(a), ("m " + anchor).strip())
    by = axis_y + 38
    if med is not None:
        xm = px0 + med * 3600 / span * (px1 - px0)
        s.path(f"M{px0} {by - 7}v14M{n(xm)} {by - 7}v14M{px0} {by}H{n(xm)}", extra=f' stroke="{t["accent"]}" fill="none"')
        s.text(xm + 8, by + 4, f"Δt median {med} h", "a")
    stamp = m["as_of"][5:16].replace("T", " ")
    foot = f"utc, {unit}s · dotted line: as of {stamp}"
    if narrow:
        s.text(px0, Hh - 10, foot, "m")
    elif mid:
        s.text(20, Hh - 10, foot, "m")
    else:
        s.text(W - 20, by + 4, foot, "m e")
    return s.done()


ART_FN = dict(header=art_header, proteins=art_proteins, brains=art_brains, quantum=art_quantum, music=art_music,
              divider=art_divider, shelf=art_shelf, stats=art_stats, constellation=art_constellation,
              analyzer=art_analyzer)


def render_art(m: dict) -> dict:
    """Every illustration in both themes, plus the mid and narrow twins; keyed (name, theme) like the panels."""
    out = {}
    for name in ART:
        for th, t in THEMES.items():
            out[(name, th)] = ART_FN[name](m, t)
            if name in NARROW_ART:
                for size in SIZES_OF[1:]:
                    out[(f"{name}-{size}", th)] = ART_FN[name](m, t, size=size)
    return out


# ---------------------------------------------------------------- readme ----
FIRST_COL = "25%"   # width hint for the defect table's first column, so the description gets the room


def alt(name: str, m: dict) -> str:
    """The text alternative for one picture, generated from the same values the picture and CHECKS.md read."""
    base = re.sub(r"-(mid|narrow)$", "", name)
    if base in ART:
        return art_alt(base, m)
    if name == "filed":
        return (f"Issues filed per {m['unit']} in UTC, {m['start']} to {m['end']}: "
                + " ".join(str(x["filed"]) for x in m["bins"]) + f". {m['total']} filed, {m['fixed']} fixed by a merged PR.")
    if name == "outcome":
        o = dict(m["outcome"])
        return (f"State of each of the {m['total']} issues: fixed by someone else's PR {o['others']}, "
                f"by own PR {o['own']}, closed without a merged PR {o['nofix']}, open {o['open']}. "
                f"Median {m['lag']['median']} hours from report to a merged fix by someone else.")
    if name == "areas":
        a = m["areas"][0]
        return (f"{m['total']} issues across {m['repos']} repositories in {plural(len(m['areas']), 'area')}; "
                f"largest: {area_label(a)}, {a['issues']}.")
    p = m["probe"]
    b, f = p["runs"]
    body = p["source"][-1].strip().removeprefix("return ")
    fixed = p["fixed_line"].strip().removeprefix("return ")
    ex = next((x for x in b["findings"] if x["check"] == "substring_containment"), b["findings"][0] if b["findings"] else None)
    eg = f", for example {ex['answer']} earns credit against {ex['reference']}" if ex else ""
    return (f"scoreprobe on a grader that returns {body}: {len(b['findings'])} of {len(b['checks_run'])} checks "
            f"reproduce{eg}. With {fixed} instead: {len(f['findings'])} of {len(f['checks_run'])}.")


def art_alt(name: str, m: dict) -> str:
    words = lambda k: NUMBER_WORDS.get(k, str(k))   # noqa: E731
    if name == "header":
        me = who()
        stops = [x[0] for x in HEADER_STOPS]
        return (f"{me['name']}, {me['city']}, cs + data science at UW, class of {me['year']}. A route through "
                f"{words(len(stops))} stops, drawn as icons: {', '.join(stops)}. A terminal: {GREP[0]} prints {GREP[1]}.")
    if name == "proteins":
        pf, P = m["protein"], PROTEIN
        return (f"Schematic, not data: a {pf['residues']}-residue protein backbone from textbook geometry (a helix of "
                f"{P['helix']} residues at {pf['per_turn']} residues/turn and {pf['rise']} Å rise, a loop, and a two-strand "
                f"hairpin at {pf['step']} Å strand step) drawn out of a blurred pretend density map, with a {pf['bar']} Å "
                "scale bar. It stands for DeepTracer's job in UW's DAIS lab: cryo-EM map in, 3D backbone out.")
    if name == "brains":
        b = m["brains"]
        out = (f"trigalign on a public EEG session (OpenNeuro ds004621, CC0): {b['n_paired']} of {b['n_events']} "
               f"stimulus-log events paired with an EEG trigger; clock offset {b['offset']} s, drift {b['drift']} ppm, "
               f"pairing residuals sd {b['sd']} ms, max {b['mx']} ms, drawn on an axis of ±{b['axis']} ms.")
        if b["miss"]:
            which = "The last event" if b["miss"]["event"] == b["n_events"] - 1 else "One event"
            out += (f" {which}, at {b['log_time']} s on the log clock, has no trigger: one was expected at "
                    f"{b['expected']} s" + (", where the recording paused." if b["paused"] else "."))
        if b["orphans"]:
            k = len(b["orphans"])
            out += (f" Hollow circle on the recorder axis, labelled {k} extra trigger{'s' if k != 1 else ''}: "
                    f"{'a trigger' if k == 1 else 'triggers'} with no log event.")
        return out
    if name == "quantum":
        q = m["quantum"]
        S, K, fr = q["shots"], q["K"], q["frames"]
        lo, hi = q["axis"]
        return (f"A flawless {K.bit_length() - 1}-qubit device sampling a uniform target: one simulated run of {S:,} "
                f"shots (splitmix64, seed {q['seed']}) as {K} bars against the ideal of {n(S / K)} each, bars clipped at "
                f"{q['clip']} times the ideal. This run scores {q['run']:.4f} and leaves {q['empty']} outcomes empty. "
                "The curve is shotfloor's closed form E[BC]², a lower bound on the mean Hellinger fidelity: "
                + ", ".join(f"{q['F'][f]:.4f}" for f in fr[:-1])
                + " at " + ", ".join(f"{f:,}" for f in fr[:-1]) + f" shots; {q['F'][S]:.4f} at {S:,} shots "
                f"({q['F'][S]:.2f} at {S:,} on the curve); by that bound, shotfloor puts 0.95 at {q['s95']:,} "
                f"shots; 1.0 only at infinite shots. The curve runs from {lo:,} to {hi:,} shots.")
    if name == "shelf":
        count = sum(len(items) for _, items in TOOLS)
        return (f"{count} small python tools as cards on a shelf, each with an icon, under "
                f"{words(len(TOOLS))} headings. "
                + " ".join(f"{group}: " + "; ".join(f"{nm}, {d.replace('`', '')}" for nm, d in items) + "."
                           for group, items in TOOLS))
    if name == "music":
        return ("Schematic, not a recording: a waveform drawn from a formula, over a terminal where ls ~/music/released/ "
                "lists nothing. Music: made often, released never.")
    if name == "stats":
        o, lag, p, q = dict(m["outcome"]), m["lag"], m["prs"], m["q"]
        fixed = (f"{m['fixed']} fixed by a merged pull request, {o['others']} by other people and {o['own']} by me"
                 if m["fixed"] else "none fixed by a merged pull request yet")
        hours = (f"median {lag['median']} hours from filing to the merged pull request, over "
                 f"{plural(lag['n'], 'fix', 'fixes')} by others" if lag["n"] else "no fix by others yet")
        return (f"Since {m['start']}: {m['total']} issues filed in {plural(m['repos'], 'repository', 'repositories')}, "
                f"{plural(len(m['areas']), 'area')}; {fixed}; {hours}; "
                f"{plural(p['upstream'], 'pull request')} to other people's repositories, "
                f"{q['prs_merged']} merged and {q['prs_open']} open.")
    if name == "divider":
        return (f"{m['total']} dots, one per issue in the order filed; the {m['fixed']} fixed by a merged pull request "
                "are lit.")
    if name == "constellation":
        o = dict(m["outcome"])
        rows = m["stars"]
        return (f"{m['total']} issues drawn as stars in {len(rows)} clusters, one per area: "
                + ", ".join(f"{STAR_LABELS[a]} {len(st)}" for a, st in rows)
                + f". Lit: {m['fixed']} fixed by a merged pull request, {o['others']} by other people and {o['own']} by me "
                f"(ringed). Rings: {o['nofix']} closed without a fix. Dots: {o['open']} open. "
                f"{plural(m['repos'], 'repository', 'repositories')} in {plural(len(rows), 'area')}.")
    if name == "analyzer":
        rows, lag = m["fixrows"], m["lag"]
        mine = [r for r in rows if r["own"]]
        out = (f"Report to fix, drawn as a logic analyzer. Top channel: one edge per issue filed, {m['total']} in all; "
               f"filed per {m['unit']}: " + ", ".join(f"{x['desc']} {x['filed']}" for x in m["bins"])
               + f". Below, one channel per fixed issue ({len(rows)}), high from the report until the merged pull "
               "request that closed it: " + ", ".join(f"{r['label']} {r['hours']:.1f} h" for r in rows) + ".")
        if mine:
            out += (f" {words(len(mine)).capitalize()} {'is' if len(mine) == 1 else 'are'} mine: "
                    + ", ".join(f"{r['label']} {r['hours']:.1f} h" for r in mine) + ".")
        if lag["median"] is not None:
            out += f" Median wait for fixes by others: {lag['median']} h."
        return out + f" As of {m['as_of'][5:16].replace('T', ' ')} utc."
    raise SystemExit(f"no alt text for {name!r}")


def versions(svgs: dict, name: str) -> dict:
    return {th: hashlib.sha1(svgs[(name, th)].encode()).hexdigest()[:8] for th in THEMES}


def picture(name: str, svgs: dict, m: dict, width: int | str = IMG) -> str:
    """The two-source picture: the dark file when the reader's theme is dark, the light one otherwise."""
    v = versions(svgs, name)
    return (
        "<picture>\n"
        f'<source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg?v={v["dark"]}">\n'
        f'<source media="(prefers-color-scheme: light)" srcset="assets/{name}-light.svg?v={v["light"]}">\n'
        f'<img alt="{h(alt(name, m))}" src="assets/{name}-light.svg?v={v["light"]}" width="{width}">\n'
        "</picture>"
    )


# Which twin a viewport gets, by the width of GitHub's README column there: about the viewport minus 32 below 768,
# about 400 to 660 beside the profile sidebar from 768 to 1011, about 580 to 770 from 1012 to 1199, and about 830
# from 1200 up. The narrow twin (380 or 400 across) serves columns up to about 570, the mid twin (560) from there to
# about 770 (beside the sidebar from a column of about 500), the wide one the rest, so every twin is drawn at
# between 0.85 and 1.5 times its own size and a banner never towers over the 380 cards beside it.
NARROW_WHEN = ("(max-width: 600px)", "(min-width: 768px) and (max-width: 859px)")
MID_WHEN = ("(min-width: 601px) and (max-width: 767px)", "(min-width: 860px) and (max-width: 1199px)")
DARK = "(prefers-color-scheme: dark)"


def _either(conds: tuple[str, ...], dark: bool) -> str:
    return ", ".join(f"{c} and {DARK}" if dark else c for c in conds)


MEDIA = (_either(NARROW_WHEN, True), _either(NARROW_WHEN, False), _either(MID_WHEN, True), _either(MID_WHEN, False),
         DARK, "(prefers-color-scheme: light)")


def picture_narrow(name: str, svgs: dict, m: dict) -> str:
    """The six-source picture for a wide image with mid and phone twins. Sources match in order; a browser that
    ignores the width queries shows the wide image scaled, and the alt text carries everything either way. That
    GitHub's sanitizer keeps these compound media values as written is checked on the live page, at phone and
    desktop width in both themes, after each change to them."""
    v, vm, vn = versions(svgs, name), versions(svgs, name + "-mid"), versions(svgs, name + "-narrow")
    return (
        "<picture>\n"
        f'<source media="{MEDIA[0]}" srcset="assets/{name}-narrow-dark.svg?v={vn["dark"]}">\n'
        f'<source media="{MEDIA[1]}" srcset="assets/{name}-narrow-light.svg?v={vn["light"]}">\n'
        f'<source media="{MEDIA[2]}" srcset="assets/{name}-mid-dark.svg?v={vm["dark"]}">\n'
        f'<source media="{MEDIA[3]}" srcset="assets/{name}-mid-light.svg?v={vm["light"]}">\n'
        f'<source media="{MEDIA[4]}" srcset="assets/{name}-dark.svg?v={v["dark"]}">\n'
        f'<img alt="{h(alt(name, m))}" src="assets/{name}-light.svg?v={v["light"]}" width="100%">\n'
        "</picture>"
    )


def issue_url(key: str) -> str:
    repo, num = key.rsplit("#", 1)
    return f"https://github.com/{repo}/issues/{num}"


def defect_table(m: dict) -> list[str]:
    """A raw HTML table (markdown cannot carry a width hint). Nothing inside it is parsed as
    markdown, so every value is HTML-escaped and the block has no blank line."""
    out = [md(m["notes"]["lead"]), "", "<table>",
           f'<tr><th align="left" width="{FIRST_COL}">report, fixed by</th><th align="left">what was wrong</th></tr>']
    for r in m["rows"]:
        f = r["fix"]
        repo, num = r["issue"].rsplit("#", 1)
        out.append(f'<tr><td width="{FIRST_COL}"><a href="{h(issue_url(r["issue"]))}">{h(short(repo))}<wbr>#{h(num)}</a>'
                   f'<br><sub>{h(f["by"])} <a href="{h(f["url"])}">#{f["pr"]}</a></sub></td><td>{h(r["what"])}</td></tr>')
    out.append("</table>")
    return out


def fixes_table(m: dict) -> list[str]:
    years = sorted({f["merged_at"][:4] for f in m["fixes"]})
    one = len(years) == 1
    out = [f"| merged {years[0] + ', ' if one else ''}utc | pull request | by | closes | hours |", "|:--|:--|:--|:--|--:|"]
    for f in m["fixes"]:
        closes = ", ".join(f"[#{k.rsplit('#', 1)[1]}]({issue_url(k)})" for k in f["closes"])
        hrs = " / ".join(f"{x:.1f}" for x in f["hours"])
        out.append(f"| {f['merged_at'][5:10] if one else f['merged_at'][:10]} | [{md(f['repo'])}#{f['pr']}]({f['url']}) | {md(f['by'])} "
                   f"| {closes} | {hrs} |")
    return out


# ------------------------------------------------------------ page prose ----
# Hand-written prose: trusted text from this file, so it is not escaped; check_readme() still vets every tag and
# link in it. A package name is written {name} and rendered by proj(): a link only when data/projects.json says
# its repository is public, plain bold otherwise, so the page never links a repository that does not exist.
# name, city and class year: the header draws them and its alt text says them, so the page states them once
WHO = dict(name="Shaurya Singh", city="Seattle", year="'27")
SITE = "[shauryasingh.com](https://shauryasingh.com)"   # his own site, the one link that is not GitHub
INTRO_TEXT = [
    "i find what hurts, then build at it. so far: proteins, brains, quantum noise, classrooms, street safety, "
    "buildings, an underwater robot, and the code that grades things.",
]
# the grep joke under the intro now lives in the header picture (GREP), its description and its alt text
FIELD_GUIDE = [
    "- **proteins** · undergrad research in UW's DAIS lab: preprocessing, training runs and renders for DeepTracer, "
    "cryo-EM maps to 3D protein structures. no byline, and that's fine.",
    "- **brains** · four essays, taught to myself in public, optogenetics to connectomics (2022–23). now {trigalign}, "
    "for EEG recordings that dropped a trigger or two.",
    "- **quantum** · {shotfloor}: the score a perfect quantum computer gets from shot noise alone. 8 qubits, uniform "
    "target, 1,024 shots: about 0.92 hellinger fidelity, not 1.",
    "- **classrooms** · co-founded SkillTern, its CTO (2022–23): computer science for 350+ students, built to run "
    "without me.",
    "- **street safety** · TurtleShell: K-means over 10,000+ LAPD crime datapoints and an iOS SOS app in Swift. "
    "Microsoft for Startups, then shut down on purpose (oct 2023).",
    "- **buildings** · a cabin designer that has to pass the Seattle residential code: rule engine, NSGA-II over "
    "cost, space and comfort, IFC export. runs locally, so no link.",
    "- **earlier** · H2OAquatics, an autonomous underwater vehicle aimed at ocean acidification; a co-written policy "
    "paper on phishing, runner-up at WatGov (Waterloo, 2023).",
    "- **off the clock** · music. made often, released never.",
]
TOOLS = [
    ("tests and repos", [
        ("tolwatch", "pytest plugin: flags `allclose`, `isclose` and `approx` checks that can't fail, or are far "
                     "looser than they need to be"),
        ("ziptrace", "names the `zip()` and `map()` calls that silently dropped data to a length mismatch"),
        ("unadded", "finds the untracked or gitignored files a passing test run quietly depends on, before CI does"),
        ("whymodified", "`git status` says modified and nothing changed: says why, and the one command that clears it"),
    ]),
    ("science data", [
        ("shotfloor", "the score a flawless quantum computer gets at a given shot count, and the shots it needs to "
                      "reach a target"),
        ("trigalign", "pairs a stimulus log with an EEG trigger list when triggers dropped, doubled, or the clocks "
                      "drifted"),
    ]),
    ("grading code", [
        ("scoreprobe", 'feeds a grader the inputs known to slip through (a blank answer, "not Paris" against "Paris", '
                       "4200 against 42) and reports which earned credit"),
        ("normladder", 'is "1,000" the same answer as "1000"? 8 of 14 answer-matching rules from lm-eval, HELM and '
                       "SQuAD say yes; it shows which, and why"),
        ("mcqlint", "lints multiple-choice eval sets: keys that name no option, duplicate options, leaked answers, "
                    "position bias"),
        ("tabverify", "recomputes the averages, deltas and bold in results tables at the printed precision, and flags "
                      "what no rounding explains"),
    ]),
]
# the side-quest sentence names four kinds of code; each must still be an area holding at least one issue
SIDE_AREAS = {"eval harnesses": "LLM eval harnesses & benchmarks", "classroom autograders": "Autograders & education",
              "forecasting": "Forecasting, time series & anomaly detection",
              "fairness metrics": "Fairness, calibration & uncertainty"}
# Figures the prose takes from elsewhere (the packages' own READMEs, his resume, his site). The build cannot recompute
# them from data/, so CHECKS.md lists each with where it comes from, and the build fails if the page stops showing
# one. (where on the page, a phrase on that README line, the figure as shown, source)
QUOTED = (
    ("README field guide, quantum", "**quantum**", "8 qubits, uniform target, 1,024 shots: about 0.92 hellinger fidelity",
     "shotfloor README.md, lines 9-20: the example for uniform:8 at 1024 shots prints a hellinger fidelity of 0.9239"),
    ("things i made shelf and its alt text, normladder", "the same answer as", "8 of 14 answer-matching rules",
     'normladder README.md, line 9: the example for "1,000" against "1000" prints 8 of 14 rules match'),
    ("things i made shelf and its alt text, scoreprobe", "feeds a grader", "4200 against 42",
     "scoreprobe README.md, lines 4-5: the list of inputs it feeds in"),
    ("README field guide, classrooms", "**classrooms**", "350+ students",
     "his resume, SkillTern entry (a count he reports himself)"),
    ("README field guide, street safety", "**street safety**", "10,000+ LAPD crime datapoints",
     "his resume, TurtleShell entry"),
    ("README field guide, brains", "**brains**", "four essays",
     "his personal site, writing page: four neuroscience essays, Feb 2022 to Jul 2023"),
)
SIDE_ANCHOR = "the habit:"
NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}


PROBE_PENDING = "first release pending"   # probe.json status until scoreprobe is public; any other status needs a url


def check_projects(projects: dict, login: str, probe: dict) -> dict:
    """data/projects.json: {name: {"status": "unreleased"} | {"status": "released", "url": ".../<login>/<name>"}}."""
    names = [n for _, items in TOOLS for n, _ in items]
    must(len(names) == len(set(names)), "TOOLS repeats a name")
    must(sorted(projects) == sorted(names), "projects.json must list exactly the packages in TOOLS")
    for n, p in projects.items():
        must(set(p) <= {"status", "url"} and p.get("status") in ("unreleased", "released"), f"projects.json: {n}")
        if p["status"] == "released":
            must(p.get("url") == f"https://github.com/{login}/{n}", f"projects.json: {n} url")
        else:
            must("url" not in p, f"projects.json: {n} is unreleased and has a url")
    must(probe.get("url") == projects["scoreprobe"].get("url"), "probe.json url and projects.json scoreprobe disagree")
    out = bool(projects["scoreprobe"].get("url"))
    must(out != (probe.get("status") == PROBE_PENDING),
         "scoreprobe is " + ("released in projects.json but probe.json still says " + repr(PROBE_PENDING)
                             if out else "unreleased in projects.json but probe.json status is " + repr(probe.get("status"))
                             + ", not " + repr(PROBE_PENDING))
         + "; set both together (build.py capture-probe --status ... --url ...)")
    return projects


def proj(name: str, projects: dict) -> str:
    url = projects[name].get("url")
    return f"[**{name}**]({url})" if url else f"**{name}**"


def field_guide(projects: dict, cards: list[str]) -> list:
    """The field guide: four illustrated cards, then one line per world."""
    names = {n: proj(n, projects) for _, items in TOOLS for n, _ in items}
    out = ["### field guide", ""]
    for pair in cards:
        out += [pair, ""]
    out += ["one line per world i've wandered into.", ""]
    return out + [line.format(**names) for line in FIELD_GUIDE]


def tools(projects: dict, shelf: str) -> list:
    """The tools as a drawn shelf (shelf is its <picture>); a released package is linked on the line under it."""
    out = ["### things i made", ""]
    released = [n for _, items in TOOLS for n, _ in items if projects[n]["status"] == "released"]
    lead = "small python tools, each about one thing that quietly goes wrong."
    if not released:
        lead += " none is public yet, so no links: each name becomes one the day its repository is."
    elif len(released) < len(projects):
        lead += (" the linked names under the shelf are out; the rest become links the day their repositories are "
                 "public.")
    out += [lead, "", "<p>\n" + shelf + "\n</p>"]
    if released:
        out += ["", "out now: " + " · ".join(proj(n, projects) for n in released)]
    return out


def side_quest(m: dict) -> list:
    have = {a["bucket"]: a["issues"] for a in m["areas"]}
    must(all(have.get(v, 0) >= 1 for v in SIDE_AREAS.values()), "the side-quest sentence names an empty area")
    kinds = ", ".join(list(SIDE_AREAS)[:-1]) + " and " + list(SIDE_AREAS)[-1]
    lines = len(m["probe"]["source"])
    word = NUMBER_WORDS.get(lines, str(lines))
    return [
        "### grading the graders",
        "",
        f"{SIDE_ANCHOR} i read the code that decides whether an answer is right ({kinds}) and file what i find.",
        "",
        "{stats}",
        "",
        "{constellation}",
        "",
        f"one example, small enough to read: scoreprobe on a {word}-line grader, before and after a one-line fix.",
        "",
        CENTER + "\n" + "{probe}" + "\n</p>",
    ]


CENTER = '<p align="center">'   # the 380-wide cards sit centred in the column, under full-width pictures


def readme(m: dict, svgs: dict, widgets: dict | None = None) -> str:
    stamp = m["as_of"].replace("T", " ").replace("Z", " utc")
    s, p, q = m["summary"], m["prs"], m["q"]
    o = dict(m["outcome"])
    login = md(m["login"])
    others = (f"the {plural(s['prs'], 'pull request')} by others "
              f"{'comes' if s['prs'] == 1 else 'come'} from {plural(s['distinct_pr_authors'], 'person', 'people')}.")
    if m["by_rule"]:
        area = (f"- areas: {m['repos'] - len(m['by_rule'])} of the {m['repos']} repositories are put in one of "
                f"{plural(len(m['areas']), 'area')} by hand, {len(m['by_rule'])} newer ones by a keyword rule until they are.")
    else:
        area = f"- areas: each of the {m['repos']} repositories is put in one of {plural(len(m['areas']), 'area')} by hand."
    probe = m["probe"]
    tool = f"[scoreprobe]({probe['url']})" if probe.get("url") else "scoreprobe"
    scope = f"{login} {SCOPE}"
    excl = ", excluding the owner's own organisations" if m["excluded"] else ""
    unit = {"day": "- days are utc. a day with nothing is drawn as a mark, not left blank.",
            "week": "- weeks start on monday, utc. a week with nothing is drawn as a mark, not left blank.",
            "month": "- months are utc. a month with nothing is drawn as a mark, not left blank."}[m["unit"]]
    method = [
        f"- counts are `total_count` from GitHub search at {stamp}: `author:{scope} is:issue` "
        f"({q['issues_total']}: {q['issues_open']} open, {q['issues_closed']} closed) and `author:{scope} is:pr` "
        f"({q['prs_total']}: {q['prs_merged']} merged, {q['prs_open']} open, {q['prs_closed_unmerged']} closed unmerged; "
        f"{p['upstream']} to other people's repositories){excl}.",
        f"- fixed means the issue is closed and a pull request in its repository that references it was merged "
        f"before it closed; an issue closed as not planned never counts. all {m['closed']} closed issues were traced: "
        f"{m['fixed']} fixed, {o['nofix']} closed without a merged pull request. " + others,
        "- an open issue whose fix did not close it is not counted, so fixed is a lower bound.",
        "- hours run from the issue being filed to the pull request merging.",
        area + " that, the four kinds of code the side-quest sentence names, the sentence above the defect table and its "
        "one line per row are the hand-written inputs to the side quest.",
        f"- the scoreprobe panel is a captured run of {tool} on the code it shows. "
        + ("" if probe.get("url") else "its first public release is pending; ")
        + "with its source, `python3 build.py capture-probe --scoreprobe-src PATH` reruns the panel.",
        unit,
        "- regenerate (python 3.12 or newer): `python3 build.py fetch` reads the api (it needs `GITHUB_TOKEN`), then "
        "`python3 build.py` renders. same input, same bytes.",
    ]
    projects = m["projects"]

    def link(name: str) -> str:
        url = projects[name].get("url")
        return f"[{name}]({url})" if url else name

    method += [
        f"- the brains card is a captured run of {link('trigalign')} on a public EEG excerpt (OpenNeuro ds004621, CC0) "
        "that ships with it; with its source, `python3 build.py capture-trigalign --trigalign-src PATH` reruns it.",
        f"- the quantum card is computed, not measured: the curve is {link('shotfloor')}'s closed form E[BC]², a lower "
        f"bound on the mean hellinger fidelity, and the bars one simulated flawless run (splitmix64, seed "
        f"{QUANTUM['seed']}).",
        "- the proteins and music drawings are schematics and say so on the image; the header's and the shelf's "
        "icons are icons.",
        "- the constellation, divider and report-to-fix pictures are drawn from the same data as the tables, and every "
        "number on them is in CHECKS.md.",
    ]
    if widgets:
        method.append("- the 3D graph and the snake are drawn by two GitHub Actions pinned to full commit SHAs, from the "
                      "public profile calendar; their totals are the calendar's.")
    rest = [k for k in PANELS if k != "probe"]
    grid = CENTER + "\n" + "\n".join(picture(k, svgs, m) for k in rest) + "\n</p>"
    side = [x.replace("{probe}", picture("probe", svgs, m))
             .replace("{stats}", "<p>\n" + picture_narrow("stats", svgs, m) + "\n</p>")
             .replace("{constellation}", "<p>\n" + picture_narrow("constellation", svgs, m) + "\n</p>")
            for x in side_quest(m)]
    cards = [CENTER + "\n" + picture("proteins", svgs, m) + "\n" + picture("brains", svgs, m) + "\n</p>",
             CENTER + "\n" + picture("quantum", svgs, m) + "\n" + picture("music", svgs, m) + "\n</p>"]
    divider = "<p>\n" + picture("divider", svgs, m, "100%") + "\n</p>"
    return "\n".join([
        "<p>\n" + picture_narrow("header", svgs, m) + "\n</p>",
        "",
        SITE,
        "",
        *INTRO_TEXT,
        "",
        *side,                  # numbers first, as the live page had them: the stat tiles, the habit, the probe
        "",
        "<details>",
        f"<summary>{NUMBER_WORDS.get(len(rest), len(rest))} more panels and the one-defect table</summary>",
        "",
        grid,
        "",
        *defect_table(m),
        "",
        "</details>",
        "",
        "<details>",
        f"<summary>{plural(len(m['fixes']), 'merged pull request')} closed {m['fixed']} of the issues</summary>",
        "",
        "<p>\n" + picture_narrow("analyzer", svgs, m) + "\n</p>",
        "",
        *fixes_table(m),
        "",
        "</details>",
        "",
        divider,
        "",
        *field_guide(projects, cards),
        "",
        divider,
        "",
        *tools(projects, picture_narrow("shelf", svgs, m)),
        "",
        *widget_section(widgets, m),
        "<details>",
        "<summary>method</summary>",
        "",
        *method,
        "",
        "</details>",
        "",
        f"<sub>side-quest numbers: github api, as of {stamp}.</sub>",
        "",
    ])


# ---------------------------------------------------------------- widgets ----
# Two pictures are drawn by GitHub Actions in the refresh workflow, not by this file: a contribution snake and a 3D
# contribution graph, each in a light and a dark file. This build reads them, refuses anything that could run or load
# something, makes the snake play once, and lists every figure the 3D picture prints as the Action's, not its own.
# A file that fails those checks is not fatal: the section is left out for that run and the reason is logged, so a
# bad widget never holds back the day's data.
SNAKE = ("assets/contrib/snake-light.svg", "assets/contrib/snake-dark.svg")
CONTRIB_3D = ("profile-3d-contrib/3d-light.svg", "profile-3d-contrib/3d-dark.svg")
CONTRIB_3D_SOURCE = "GitHub's public profile calendar, via yoshi389111/github-profile-3d-contrib v0.9.3"
WIDGET_MAX = 400_000
WIDGET_BANNED = {"script", "foreignobject", "image", "use", "a", "iframe"}


def patch_snake(svg: str) -> str:
    """Play once instead of forever, and stop for reduced motion. Patching twice gives the same bytes."""
    styles = re.findall(r"<style>(.*?)</style>", svg, re.S)
    must(len(styles) == 1, "snake: expected exactly one <style>")
    body = styles[0].replace("infinite", "1")
    if MOTION not in body:
        body += MOTION
    return svg.replace(f"<style>{styles[0]}</style>", f"<style>{body}</style>", 1)


def check_widget_svg(name: str, svg: str) -> None:
    """A file an Action drew: well-formed, small, nothing that runs or loads, every animation finite."""
    must(len(svg.encode("utf-8")) < WIDGET_MAX, f"widget {name}: larger than {WIDGET_MAX} bytes")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        raise SystemExit(f"guard: widget {name} is not well-formed ({e})") from None
    styles = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        must(tag not in WIDGET_BANNED, f"guard: widget {name} has a <{tag}>")
        if tag == "style":
            styles.append(el.text or "")
        for k, v in el.attrib.items():
            k = k.rsplit("}", 1)[-1].lower()
            must(not k.startswith("on"), f"guard: widget {name} has an {k} attribute")
            must(k != "href" or v.startswith("#"), f"guard: widget {name} links to {v!r}")
            must(not (k == "repeatcount" and v.strip() == "indefinite"), f"guard: widget {name} repeats forever")
            if k == "style":
                styles.append(v)
    css = "\n".join(styles)
    must("@import" not in css, f"guard: widget {name} imports a stylesheet")
    must(all(u.startswith("#") for u in re.findall(r"url\(\s*['\"]?([^)'\"]*)", css)), f"guard: widget {name} loads a url")
    must("infinite" not in css, f"guard: widget {name} animates forever")


def widget_figures(svg: str) -> list[str]:
    """Every <text> in the 3D picture that holds a digit, in document order, with its tooltip when it has one."""
    out = []
    for el in ET.fromstring(svg).iter():
        if el.tag.rsplit("}", 1)[-1] != "text":
            continue
        own = clean(el.text or "")
        tip = " ".join(clean("".join(c.itertext())) for c in el if c.tag.rsplit("}", 1)[-1] == "title")
        fig = own if not tip or tip == own else f"{own} {tip}".strip()
        if re.search(r"\d", fig):
            out.append(fig)
    return out


def read_widgets(root: Path | None) -> dict | None:
    """The Action-drawn files under root, checked and patched; None when any of the four is absent or fails a check
    (logged, so the run goes on without the section)."""
    if root is None:
        return None
    rels = (*SNAKE, *CONTRIB_3D)
    if not all((root / rel).is_file() for rel in rels):
        return None
    files = {}
    for rel in rels:
        svg = (root / rel).read_text(encoding="utf-8")
        try:
            if rel in SNAKE:
                svg = patch_snake(svg)
            check_widget_svg(rel, svg)
        except SystemExit as e:
            log(f"widgets left out this run: {e}")
            return None
        files[rel] = svg
    if widget_figures(files[CONTRIB_3D[0]]) != widget_figures(files[CONTRIB_3D[1]]):
        log("widgets left out this run: the light and dark 3D files print different figures")
        return None
    return files


def widget_picture(pair: tuple[str, str], widgets: dict, text: str) -> str:
    v = {th: hashlib.sha1(widgets[f].encode()).hexdigest()[:8] for th, f in zip(("light", "dark"), pair)}
    return ("<p>\n<picture>\n"
            f'<source media="(prefers-color-scheme: dark)" srcset="{pair[1]}?v={v["dark"]}">\n'
            f'<source media="(prefers-color-scheme: light)" srcset="{pair[0]}?v={v["light"]}">\n'
            f'<img alt="{h(text)}" src="{pair[0]}?v={v["light"]}" width="100%">\n'
            "</picture>\n</p>")


def widget_section(widgets: dict | None, m: dict) -> list[str]:
    if not widgets:
        return []
    alt3 = ("A 3D contribution calendar for the past year, drawn by a GitHub Action from the public profile calendar, "
            "with a radar of commits, issues, pull requests, reviews and repositories and a language chart. On a phone "
            "it is a picture of the calendar's shape; its small labels are not meant to be read there. Its totals are "
            "the calendar's own.")
    alts = "A snake eats the public profile calendar of the past year, once, and leaves the grid as it found it."
    return [
        "### commit weather",
        "",
        widget_picture(CONTRIB_3D, widgets, alt3),
        widget_picture(SNAKE, widgets, alts),
        "",
        "<sub>drawn daily by two GitHub Actions from the public profile calendar: the shape of the year, not "
        "numbers to read. the totals in the 3D picture are the calendar's own.</sub>",
        "",
    ]


# ---------------------------------------------------------------- guards ----
SVG_TAGS = {"svg", "title", "desc", "style", "rect", "path", "text", "tspan", "g", "circle", "polyline", "polygon", "line"}
README_TAGS = {"p": {"align"}, "br": set(), "picture": set(), "source": {"media", "srcset"},
               "img": {"alt", "src", "width"}, "table": set(), "tr": set(), "th": {"align", "width"},
               "td": {"width"}, "a": {"href"}, "sub": set(), "wbr": set(), "details": set(), "summary": set()}
# Links go to GitHub and his own site only, so the page never links anywhere a reader did not expect from a profile.
URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9][A-Za-z0-9._/-]*|https://shauryasingh\.com(?:/[A-Za-z0-9._/-]*)?")
ASSET_RE = re.compile(r"assets/(contrib/)?[a-z]+(-mid|-narrow)?-(light|dark)\.svg\?v=[0-9a-f]{8}"
                      r"|profile-3d-contrib/3d-(light|dark)\.svg\?v=[0-9a-f]{8}")


def check_svg(name: str, svg: str) -> None:
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        raise SystemExit(f"guard: {name} is not well-formed ({e})") from None
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        must(tag in SVG_TAGS, f"guard: {name} has a <{tag}>")
        must(not any(a.lower().startswith("on") or "href" in a.lower() for a in el.attrib), f"guard: {name} attribute")
    style = "".join(el.text or "" for el in root.iter() if el.tag.endswith("style"))
    style += "".join(el.get("style", "") for el in root.iter())
    must("url(" not in style and "@import" not in style, f"guard: {name} style loads something")


def css_rules(css: str) -> list[tuple[str, dict]]:
    """(selector, declarations) for each plain rule; @keyframes and @media blocks are skipped."""
    rules, i = [], 0
    while i < len(css):
        j = css.find("{", i)
        if j < 0:
            break
        sel = css[i:j].strip()
        depth, k = 1, j + 1
        while depth:
            must(k < len(css), "css: unbalanced braces")
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        if not sel.startswith("@"):
            decls = {}
            for part in css[j + 1:k - 1].split(";"):
                if ":" in part:
                    key, val = part.split(":", 1)
                    decls[key.strip()] = val.strip()
            rules.append((sel, decls))
        i = k
    return rules


def seconds(tok: str) -> float:
    return float(tok[:-2]) / 1000 if tok.endswith("ms") else float(tok[:-1])


def animation(value: str) -> tuple[float, float, float]:
    """(duration, delay, iteration count) of one animation shorthand."""
    must("," not in re.sub(r"\([^)]*\)", "", value), f"art: one animation per rule, not {value!r}")
    toks = re.sub(r"\([^)]*\)", "()", value).split()
    times = [seconds(x) for x in toks if re.fullmatch(r"-?[\d.]+m?s", x)]
    counts = [x for x in toks if re.fullmatch(r"[\d.]+|infinite", x)]
    must(len(times) >= 1 and len(counts) <= 1, f"art: animation {value!r} is not dur [delay] [count]")
    must(not counts or counts[0] != "infinite", f"art: animation {value!r} never stops")
    return times[0], times[1] if len(times) > 1 else 0.0, float(counts[0]) if counts else 1.0


def check_art(name: str, svg: str) -> None:
    """check_svg, plus the motion and type rules every illustration keeps."""
    check_svg(name, svg)
    root = ET.fromstring(svg)
    styles = [el.text or "" for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "style"]
    must(len(styles) == 1, f"art: {name} has {len(styles)} <style> elements")
    css = styles[0]
    attrs = " ".join(el.get("style", "") for el in root.iter())
    must("transform-box" not in css + attrs, f"art: {name} uses transform-box")
    must("infinite" not in css + attrs and 'repeatCount="indefinite"' not in svg, f"art: {name} animates forever")
    if "@keyframes" in css:
        must(css.endswith(MOTION), f"art: {name} has keyframes but does not end with the reduced-motion rule")
    for size in re.findall(r"font-size:\s*([\d.]+)", css + attrs):
        must(float(size) >= 12, f"art: {name} has {size}-unit text")
    for fam in re.findall(r"font-family:([^;}]+)", css + attrs):
        must(fam.strip() in (FONT, SANS), f"art: {name} uses font-family {fam.strip()!r}")
    timed = {}
    for sel, decls in css_rules(css):
        for k, v in decls.items():
            must(k in ("animation", "transform", "opacity") or not k.startswith("animation"),
                 f"art: {name} sets {k}; use the animation shorthand")
            if k == "animation":
                dur, dly, count = animation(v)
                must(count <= 5, f"art: {name} {sel} runs {count:g} times")
                must(dly + dur * count <= MAX_ANIM + EPS, f"art: {name} {sel} runs past {MAX_ANIM:g} s")
                must(re.fullmatch(r"\.[\w-]+", sel) is not None, f"art: {name} animates {sel!r}; use one class")
                timed[sel[1:]] = (dur, count)
    for el in root.iter():
        st = el.get("style")
        if not st:
            continue
        mo = re.fullmatch(r"animation-delay:(-?[\d.]+s)", st)
        must(mo is not None, f"art: {name} has an inline style other than a delay: {st!r}")
        runs = [timed[c] for c in el.get("class", "").split() if c in timed]
        must(len(runs) == 1, f"art: {name} has a delay on an element with no single animated class")
        dur, count = runs[0]
        must(seconds(mo.group(1)) + dur * count <= MAX_ANIM + EPS, f"art: {name} element runs past {MAX_ANIM:g} s")


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.seen: list[tuple[str, list]] = []

    def handle_starttag(self, tag, attrs):
        self.seen.append((tag, attrs))

    handle_startendtag = handle_starttag


def check_readme(text: str) -> None:
    must(all(ord(c) >= 32 or c == "\n" for c in text), "guard: README.md has a control character")
    parser = _Tags()
    parser.feed(text)
    parser.close()
    for tag, attrs in parser.seen:
        must(tag in README_TAGS, f"guard: README.md would carry <{tag}>")
        for k, v in attrs:
            must(k in README_TAGS[tag], f"guard: <{tag} {k}> is not allowed")
            if k == "href":
                must(URL_RE.fullmatch(v or "") is not None, f"guard: link to {v!r}")
            if k in ("src", "srcset"):
                must(ASSET_RE.fullmatch(v or "") is not None, f"guard: image source {v!r}")
            if k == "width":
                must(re.fullmatch(r"\d+%?", v or "") is not None, f"guard: width {v!r}")
            if k == "align" and tag == "p":
                must(v == "center", f"guard: <p align={v!r}>")
            if k == "media":
                must(v in MEDIA, f"guard: <source media={v!r}> is not one of the allowed queries")
    for target in re.findall(r"(?<!\\)\]\(([^)]*)\)", text):   # an escaped \] opens no link
        must(URL_RE.fullmatch(target) is not None, f"guard: markdown link to {target!r}")
    head = None
    for line in text.splitlines():
        if line.startswith("|"):
            cells = len(re.findall(r"(?<!\\)\|", line))
            head = head or cells
            must(cells == head, f"guard: a table row has {cells - 1} cells, the header {head - 1}")
        else:
            head = None


# ---------------------------------------------------------------- checks ----
def svg_text(svg: str) -> str:
    root = ET.fromstring(svg)
    return "\n".join("".join(el.itertext()) for el in root.iter() if el.tag.rsplit("}", 1)[-1] in ("text", "desc"))


def drawn_text(svg: str) -> str:
    """The words a picture draws, its <text> lines joined by spaces (a wrapped sentence reads as one)."""
    root = ET.fromstring(svg)
    return " ".join("".join(el.itertext()) for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "text")


def art_checks(m: dict) -> list[tuple[str, str, str, str, list[str]]]:
    """(where, what, value as shown, field or formula, pictures to find it in) for every number the illustrations
    print or describe. The value is looked up in each picture's text and description, light and dark."""
    o, pf, q, b = dict(m["outcome"]), m["protein"], m["quantum"], m["brains"]
    rows = []

    def add(where, what, value, field, keys):
        rows.append((where, what, str(value), field, keys))

    me = who()
    add("header", "class year", me["year"], "WHO.year", ["header", "header-mid", "header-narrow"])
    k = len(HEADER_STOPS)
    add("header", "stops (desc)", f"{NUMBER_WORDS.get(k, k)} stops", "len(HEADER_STOPS)",
        ["header", "header-mid", "header-narrow"])
    card = ["proteins"]
    add("proteins card", "residues per turn", f"{pf['per_turn']} residues/turn", "360 / PROTEIN.deg", card)
    add("proteins card", "rise", f"{pf['rise']} Å rise", "PROTEIN.rise", card)
    add("proteins card", "strand step", f"{pf['step']} Å strand step", "PROTEIN.strand_step", card)
    add("proteins card", "scale bar", f"{pf['bar']} Å", "constant", card)
    add("proteins card", "residues (desc)", f"{pf['residues']}-residue", "len(backbone())", card)
    add("proteins card", "helix length (desc)", f"helix of {PROTEIN['helix']} residues", "PROTEIN.helix", card)
    card = ["brains"]
    add("brains card", "events paired", f"{b['n_paired']} of {b['n_events']}",
        "trigalign.json logs[0].n_paired, logs[0].n_events", card)
    if b["miss"]:
        add("brains card", "lost trigger, expected", f"{b['expected']} s", "logs[0].unmatched[0].expected_trigger_time", card)
        add("brains card", "lost event, log time (desc)", f"{b['log_time']} s", "logs[0].unmatched[0].time", card)
    add("brains card", "triggers lost", f"{NUMBER_WORDS.get(b['lost'], b['lost'])} trigger",
        "logs[0].n_events - logs[0].n_paired", card)
    if b["orphans"]:
        k = len(b["orphans"])
        add("brains card", "triggers with no log event", f"{k} extra trigger", "len(trigalign.json unpaired_triggers)",
            card)
    add("brains card", "residual sd", f"sd {b['sd']} ms", "logs[0].segments[0].residual_sd_ms (recomputed from pairs)", card)
    add("brains card", "residual max", f"max {b['mx']}", "logs[0].segments[0].residual_max_ms (recomputed from pairs)", card)
    add("brains card", "drift", f"{b['drift']} ppm", "logs[0].segments[0].drift_ppm", card)
    add("brains card", "offset (desc)", f"{b['offset']} s", "logs[0].segments[0].offset_s", card)
    add("brains card", "residual axis", f"±{b['axis']} ms", "ceil(residual_max_ms × 10) / 10", card)
    card, S = ["quantum"], q["shots"]
    add("quantum card", f"E[BC]² at {S:,} shots, a lower bound on mean fidelity", f"{q['F'][S]:.4f}",
        f"fidelity_floor({S}) = (√(K/s)·Σ pmf(k;s,1/K)√k)², K={q['K']}", card)
    add("quantum card", "as the field guide prints it", f"{q['F'][S]:.2f} at {S:,}", f"round(fidelity_floor({S}), 2)", card)
    add("quantum card", "shots for 0.95, by the E[BC]² bound", f"0.95 needs {q['s95']:,}", "shots_for(0.95), bisection",
        card)
    for f in q["frames"]:
        add("quantum card", f"E[BC]², frame {f:,}", f"E[BC]² {q['F'][f]:.4f}", f"fidelity_floor({f})", card)
    add("quantum card", "this simulated run", f"this simulated run {q['run']:.4f}",
        f"BC² of splitmix64({q['seed']}) counts, {S:,} shots, top {q['K'].bit_length() - 1} bits", card)
    add("quantum card", "empty outcomes (desc)", f"{q['empty']} outcomes empty", "counts.count(0)", card)
    add("quantum card", "outcomes", f"{q['K']} outcomes", "QUANTUM.K = 2^8, 8 qubits, uniform", card)
    add("quantum card", "ideal count per outcome (desc)", f"ideal of {n(S / q['K'])} each", "QUANTUM.shots / QUANTUM.K",
        card)
    add("quantum card", "bar clip (desc)", f"clipped at {q['clip']} times the ideal", "QUANTUM.clip", card)
    for f in q["frames"][:-1]:
        add("quantum card", f"frame {f:,}", f"{f:,} shots so far", "QUANTUM.frames", card)
    add("quantum card", "seed", f"seed {q['seed']}", "QUANTUM.seed", card)
    add("quantum card", "asymptote", "1.0", "fidelity_floor(s) tends to 1 as s grows", card)
    add("quantum card", "axis ends", f"{q['axis'][0]:,}", "QUANTUM.axis[0]", card)
    add("quantum card", "axis ends", f"{q['axis'][1]:,}", "QUANTUM.axis[1]", card)
    card = ["shelf", "shelf-mid", "shelf-narrow"]
    count = sum(len(items) for _, items in TOOLS)
    add("things i made shelf", "tools (desc)", f"{count} small python tools", "len of every TOOLS group", card)
    add("things i made shelf", "headings (desc)", f"{NUMBER_WORDS.get(len(TOOLS), len(TOOLS))} headings", "len(TOOLS)",
        card)
    card, w = ["stats", "stats-mid", "stats-narrow"], "side-quest stat tiles, all three widths"
    sq, sp, slag = m["q"], m["prs"], m["lag"]
    add(w, "since", f"since {m['start']}", "issues.first_created_at", card)
    add(w, "issues filed", f"{m['total']} issues filed", "issues.total", card)
    add(w, "repositories", f"{m['repos']} repos", "issues.distinct_repos", card)
    add(w, "areas", plural(len(m["areas"]), "area"), "len(ecosystems)", card)
    add(w, "fixed", f"{m['fixed']} fixed", "fixed (others + own)", card)
    if m["fixed"]:
        add(w, "fixed by others, by me", f"{o['others']} by others, {o['own']} by me",
            "outcomes.fixed_by_merged_pr_from_someone_else, outcomes.fixed_by_his_own_merged_pr", card)
    if slag["n"]:
        add(w, "median hours to a fix", f"median {slag['median']} hours", "fix_lag_hours_filed_to_merge.median", card)
        add(w, "fixes by others with hours", f"{plural(slag['n'], 'fix', 'fixes')} by others",
            "fix_lag_hours_filed_to_merge.n", card)
    add(w, "PRs upstream", f"{plural(sp['upstream'], 'pull request')} to other", "prs.upstream", card)
    add(w, "PRs merged, open", f"{sq['prs_merged']} merged, {sq['prs_open']} open", "queries.prs_merged, queries.prs_open",
        card)
    card = ["divider"]
    add("divider", "dots (desc)", f"{m['total']} dots", "issues.total", card)
    add("divider", "lit (desc)", f"the {m['fixed']} fixed", "fixed (others + own)", card)
    card, w = ["constellation", "constellation-mid", "constellation-narrow"], "constellation, all three widths"
    add(w, "stars", m["total"], "issues.total", card)
    add(w, "lit", f"fixed by a merged PR: {m['fixed']}", "fixed (others + own)", card)
    add(w, "fixed by others", f"fixed by others {o['others']}", "outcomes.fixed_by_merged_pr_from_someone_else", card)
    add(w, "fixed by me", f"fixed by me {o['own']}", "outcomes.fixed_by_his_own_merged_pr", card)
    add(w, "closed, no fix", f"closed, no fix {o['nofix']}",
        "outcomes.closed_not_planned + outcomes.closed_completed_without_a_fix_merged", card)
    add(w, "open", f"open {o['open']}", "outcomes.open", card)
    add(w, "repositories", plural(m["repos"], "repository", "repositories"), "issues.distinct_repos", card)
    add(w, "areas", plural(len(m["areas"]), "area"), "len(ecosystems)", card)
    for i, (area, stars) in enumerate(m["stars"]):
        add(w, STAR_LABELS[area], f"{STAR_LABELS[area]} {len(stars)}", f"ecosystems[{i}].issues", card)
    card, w = ["analyzer", "analyzer-mid", "analyzer-narrow"], "analyzer, all three widths"
    add(w, "filed", f"{m['total']} filed", "issues.total", card)
    add(w, "fixed", f"{m['fixed']} fixed", "fixed (others + own)", card)
    if m["lag"]["median"] is not None:
        add(w, "median wait", f"median {m['lag']['median']} h",
            "fix_lag_hours_filed_to_merge.median, re-derived from created_at to merged_at", card)
    for r in m["fixrows"]:
        add(w, f"{r['label']} (desc)", f"{r['label']} {r['hours']:.1f} h",
            "issues.json created_at to the fix's merged_at; equals the fixes table", card)
    per = {"day": "issues.daily_utc[day]", "week": "issues.daily_utc, summed per week",
           "month": "issues.monthly[month]"}[m["unit"]]
    for x in m["bins"]:
        add("analyzer (desc)", f"filed, {x['desc']}", f"{x['desc']} {x['filed']}", per, card)
    add(w, "as of", m["as_of"][5:16].replace("T", " "), "as_of", card)
    return rows


def art_quoted(m: dict) -> list[tuple[str, tuple[str, ...], str, list[str]]]:
    """Figures the pictures quote rather than compute: (where, the figure's parts, source, pictures)."""
    out = [("header", GREP, "his personal site, sessions log", ["header", "header-mid", "header-narrow"]),
           ("music card", ("$ ls ~/music/released/", "(empty)"), "his personal site, sessions log", ["music"]),
           ("brains card", ("OpenNeuro ds004621 (CC0)",), "trigalign tests/data/NOTICE", ["brains"])]
    if m["brains"]["paused"]:
        out.append(("brains card", ("(the recording paused)",),
                    'trigalign README example output: "on a New Segment marker"', ["brains"]))
    return out


def checks(m: dict, svgs: dict, text: str, widgets: dict | None = None) -> str:
    """Every computed number on the page with the field it is read from. Each value is looked up in the output
    it names (on the line that holds its anchor, when it has one), so this list cannot drift."""
    rows: list[tuple[str, str, str, str, str, str]] = []

    def add(where, what, value, field, anchor="", needle=None):
        rows.append((where, what, str(value), field, anchor, str(value) if needle is None else needle))

    def share(field):
        return (f"({field})" if "+" in field else field) + " / issues.total"

    o = dict(m["outcome"])
    per = {"day": "issues.daily_utc[day]", "week": "issues.daily_utc, summed per week",
           "month": "issues.monthly[month]"}[m["unit"]]
    fixed_f = "outcomes.fixed_by_merged_pr_from_someone_else + outcomes.fixed_by_his_own_merged_pr"
    nofix_f = "outcomes.closed_not_planned + outcomes.closed_completed_without_a_fix_merged"
    add("filed panel", "issues filed", m["total"], "issues.total")
    add("filed panel", "issues fixed", m["fixed"], fixed_f)
    add("filed panel", "window", f"{m['start']}/{m['end']}", "issues.first_created_at, as_of")
    for x in m["bins"]:
        add("filed panel", f"filed, {x['desc']}", f"{x['desc']} {x['filed']}", per)
    for x in m["bins"]:
        if x["others"] + x["own"]:
            add("filed panel", f"fixed, {x['desc']} (squares)", f"{x['desc']} {x['others'] + x['own']}",
                "fixes_by_others[].merged_at, prs.merged_list[].merged_at")
    add("outcome panel", "fixed, of total", f"of {m['total']} fixed", "issues.total")
    for kind, field in (("others", "outcomes.fixed_by_merged_pr_from_someone_else"),
                        ("own", "outcomes.fixed_by_his_own_merged_pr"), ("nofix", nofix_f), ("open", "outcomes.open")):
        add("outcome panel", f"{kind}", o[kind], field)
        add("outcome panel", f"{kind}, share", f"{100 * o[kind] / m['total']:.1f}%", share(field))
    for k in ("n", "min", "median", "max"):
        add("outcome panel", f"hours, {k}", m["lag"][k], f"fix_lag_hours_filed_to_merge.{k}")
    add("areas panel", "repositories", m["repos"], "issues.distinct_repos")
    add("areas panel", "areas", plural(len(m["areas"]), "area"), "len(ecosystems)")
    shown = m["areas"] if len(m["areas"]) <= SHOW_AREAS + 1 else m["areas"][:SHOW_AREAS]
    for i, a in enumerate(m["areas"]):
        add("areas panel", area_label(a), f"{area_label(a)} {a['issues']}", f"ecosystems[{i}].issues")
    rest = m["areas"][len(shown):]
    if rest:
        add("areas panel", "folded areas, issues", plural(sum(a["issues"] for a in rest), "issue"),
            f"sum of ecosystems[{len(shown)}:].issues")
        add("areas panel", "folded areas, repositories", sum(a["repos"] for a in rest),
            f"sum of ecosystems[{len(shown)}:].repos")
    b, f = m["probe"]["runs"]
    add("probe panel", "checks that reproduce", f"{len(b['findings'])} of {len(b['checks_run'])}",
        "probe.json: len(runs[0].findings) of len(runs[0].checks_run)")
    add("probe panel", "after the one-line fix", f"{len(f['findings'])} of {len(f['checks_run'])}",
        "probe.json: len(runs[1].findings) of len(runs[1].checks_run)")
    for i, x in enumerate(b["findings"]):
        add("probe panel", f"{x['check']}, inputs that earned credit (in the description)", f"{x['n']} inputs",
            f"probe.json: runs[0].findings[{i}].n")
    for i, r in enumerate(m["rows"]):
        url = issue_url(r["issue"])
        add("README defect table", f"row {i + 1}, report", "#" + r["issue"].rsplit("#", 1)[1], f"notes.json: rows[{i}].issue", url)
        add("README defect table", f"row {i + 1}, fix", f"#{r['fix']['pr']}",
            "prs.merged_list[].number" if r["fix"]["own"] else "fixes_by_others[].pr", url)
    add("README fixes table", "summary, pull requests", plural(len(m["fixes"]), "merged pull request"),
        "len(fixes_by_others) + merged_list entries that close an issue")
    add("README fixes table", "summary, issues", f"closed {m['fixed']} of", fixed_f)
    for fx in m["fixes"]:
        src = "prs.merged_list[]" if fx["own"] else "fixes_by_others[]"
        anchor = f"]({fx['url']})"
        hrs = " / ".join(f"{x:.1f}" for x in fx["hours"])
        when = fx["merged_at"][5:10] if len({x["merged_at"][:4] for x in m["fixes"]}) == 1 else fx["merged_at"][:10]
        add("README fixes table", f"{fx['repo']}#{fx['pr']}, merged", when, f"{src}.merged_at", anchor, f"| {when} |")
        add("README fixes table", f"{fx['repo']}#{fx['pr']}, hours", hrs,
            f"{src}.{'hours' if fx['own'] else 'hours_issue_filed_to_merge'}", anchor, f"| {hrs} |")
    q, p, s = m["q"], m["prs"], m["summary"]
    count_line = "- counts are `total_count`"
    for k, shown_as in (("issues_total", "is:issue` ({}:"), ("issues_open", "{} open, "), ("issues_closed", "{} closed)"),
                        ("prs_total", "is:pr` ({}:"), ("prs_merged", "{} merged"), ("prs_open", "merged, {} open"),
                        ("prs_closed_unmerged", "{} closed unmerged")):
        add("README method", k.replace("_", " "), q[k], f"queries.{k}", count_line, shown_as.format(q[k]))
    add("README method", "PRs to other people's repositories", f"{p['upstream']} to other", "prs.upstream", count_line)
    fix_line = "- fixed means"
    add("README method", "closed issues traced", f"all {m['closed']} closed", "issues.closed", fix_line)
    add("README method", "fixed", f"{m['fixed']} fixed", fixed_f, fix_line)
    add("README method", "closed without a merged pull request", f"{o['nofix']} closed without", nofix_f, fix_line)
    add("README method", "pull requests by others", plural(s["prs"], "pull request"), "fixes_by_others_summary.prs", fix_line)
    add("README method", "people", plural(s["distinct_pr_authors"], "person", "people"),
        "fixes_by_others_summary.distinct_pr_authors", fix_line)
    add("README method", "repositories put in areas", f"{m['repos']} repositories", "issues.distinct_repos", "- areas:")
    add("README method", "areas", plural(len(m["areas"]), "area"), "len(ecosystems)", "- areas:")
    # three counts the build derives and writes as words: the fold's summary and the example's grader length
    n_fold = len([k for k in PANELS if k != "probe"])
    n_src = len(m["probe"]["source"])
    add("README side quest", "panels in the fold", f"{NUMBER_WORDS.get(n_fold, n_fold)} more panels", "len(PANELS) - 1",
        "more panels and")
    n_rows = len(m["rows"])
    add("README defect table", "fixes in the table, lead sentence", f"{NUMBER_WORDS.get(n_rows, n_rows)} of the fixes",
        "len(notes.json rows)", "of the fixes share")
    add("README side quest", "lines in the example grader", f"{NUMBER_WORDS.get(n_src, n_src)}-line grader",
        "len(probe.json source)", "one example, small enough")
    add("README method and footer", "as of", m["as_of"].replace("T", " ").replace("Z", " utc"), "as_of (from fetch.json)")
    add("README method", "trigalign capture", "ds004621", "trigalign.json source", "- the brains card is")

    hay = {"README.md": text, **{f"{k} panel": svg_text(svgs[(k, "light")]) for k in PANELS}}
    for where, what, value, field, anchor, needle in rows:
        target = hay.get(where, text)
        if anchor:
            lines = [ln for ln in target.splitlines() if anchor in ln]
            must(len(lines) >= 1 and needle in lines[0], f"checks: {what!r} = {needle!r} is not on the line with {anchor!r}")
        else:
            must(needle in target, f"checks: {what!r} = {needle!r} is not in the {where}")
        must("`" not in field, "checks: a field name holds a backtick")
    for where, anchor, figure, _ in QUOTED:
        lines = [ln for ln in text.splitlines() if anchor in ln]
        must(len(lines) >= 1 and figure in lines[0], f"checks: quoted {figure!r} is not on the line with {anchor!r} ({where})")
        if any(anchor in d for _, items in TOOLS for _, d in items):     # drawn on the shelf too, at every width
            for size in ("shelf", "shelf-mid", "shelf-narrow"):
                for th in THEMES:
                    must(figure in drawn_text(svgs[(size, th)]), f"checks: quoted {figure!r} is not drawn on {size}-{th}")
    art_rows = art_checks(m)
    for where, what, value, field, keys in art_rows:
        for k in keys:
            for th in THEMES:
                must(value in svg_text(svgs[(k, th)]), f"checks: {what!r} = {value!r} is not in {k}-{th}.svg")
        must("`" not in field, "checks: a field name holds a backtick")
    quoted = art_quoted(m)
    for where, parts, _, keys in quoted:
        for k in keys:
            for part in parts:
                must(part in svg_text(svgs[(k, "light")]), f"checks: quoted {part!r} is not in {k}")
    q = m["quantum"]
    guide = next(ln for ln in FIELD_GUIDE if ln.startswith("- **quantum**"))
    must(f"{q['shots']:,} shots: about {q['F'][q['shots']]:.2f} hellinger fidelity" in guide,
         "checks: the field guide's quantum figure is not fidelity_floor rounded to two places")
    out = ["# checks", "",
           "Every number this build computes from data/ and the field it is read from (data/stats.json unless another "
           "file is named).",
           "Written by `python3 build.py`, which fails if a value listed here is missing from the output it names.",
           "Panel values are looked up in the SVG text and its description; README values on the line they belong to.",
           "Figures the prose quotes from elsewhere are listed after the table, with their sources.",
           "", "| where | what | value as shown | field |", "|:--|:--|:--|:--|"]
    for where, what, value, field, _, _ in rows:
        out.append(f"| {md(where)} | {md(what)} | {md(value)} | `{field}` |")
    for where, what, value, field, _ in art_rows:
        out.append(f"| {md(where)} | {md(what)} | {md(value)} | `{field}` |")
    out += ["", "## quoted, not computed", "",
            "The prose also quotes a few figures from outside data/: the packages' own READMEs, the owner's resume and "
            "his personal site. This build cannot recompute them. It checks that each is still on the page, on the "
            "line it belongs to, so a figure cannot change on the page without its source being looked at again here.",
            "", "| where | figure as shown | source |", "|:--|:--|:--|"]
    for where, _, figure, source in QUOTED:
        out.append(f"| {md(where)} | {md(figure)} | {md(source)} |")
    out += ["", "## quoted, not computed (images)", "",
            "Text the pictures quote rather than compute. Each is checked to be on the picture it names.",
            "", "| where | figure as shown | source |", "|:--|:--|:--|"]
    for where, parts, source, _ in quoted:
        out.append(f"| {md(where)} | {md(' / '.join(parts))} | {md(source)} |")
    out += ["", "## drawn by an Action, not recomputed", ""]
    if widgets:
        out += [f"Every figure printed in {CONTRIB_3D[0]}, in the order the file has them ({CONTRIB_3D[1]} prints the "
                "same ones). They are GitHub's numbers for the public profile calendar, which counts things the side "
                "quest does not (for example contributions to his own organisations), so they are not expected to "
                "match the table above. The last one is the window the calendar covers, as printed in the file.",
                "", "| figure as printed | source |", "|:--|:--|"]
        for fig in widget_figures(widgets[CONTRIB_3D[0]]):
            out.append(f"| {md(fig)} | {md(CONTRIB_3D_SOURCE)} |")
    else:
        out.append("widgets: not generated yet. The refresh workflow draws them; until it has, the page leaves the "
                   "commit-weather section out.")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------- probe capture ----
GRADER = [
    "def grade(answer, reference):",
    "    return reference.lower() in answer.lower()",
]
FIXED_LINE = "    return reference.lower() == answer.lower()"


def capture_probe(src: str, status: str, url: str | None, out: Path) -> None:
    sys.path.insert(0, src)
    import scoreprobe  # noqa: E402  (imported only here, from the path given)

    def run(code: str) -> dict:
        ns: dict = {}
        exec(code, ns)
        r = scoreprobe.probe(grader=ns["grade"])
        must(r.probed, "scoreprobe probed nothing")
        return dict(checks_run=list(r.checks_run), findings=[
            dict(check=f.check, answer=repr(f.examples[0][0]), reference=repr(f.examples[0][1]), n=len(f.examples))
            for f in r.findings])

    broken = run("\n".join(GRADER) + "\n")
    fixed = run("\n".join(GRADER[:-1] + [FIXED_LINE]) + "\n")
    data = dict(version=scoreprobe.__version__, status=status, source=GRADER, fixed_line=FIXED_LINE,
                runs=[broken, fixed])
    if url:
        must(re.fullmatch(r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+", url) is not None, "--url")
        data["url"] = url
    out.write_text(dump(data), encoding="utf-8", newline="\n")
    print(f"wrote {out}: {len(broken['findings'])} and {len(fixed['findings'])} findings")


# ------------------------------------------------------------------ main ----
def model(data: Path) -> dict:
    """Everything the page draws, checked: derive() plus the facts behind each illustration."""
    issues = read(data / "issues.json")
    m = derive(read(data / "stats.json"), issues, read(data / "notes.json"), read(data / "probe.json"))
    m["projects"] = check_projects(read(data / "projects.json"), m["login"], m["probe"])
    for x in m["by_rule"]:
        log(f"areas: {x['repo']} is placed by rule in {x['area']!r}; add it to data/areas.json")
    m["spans"] = bins_for(m["start"], m["end"])[1]
    m["created"] = sorted(i["created_at"] for i in issues)
    m["area_of"] = area_map(issues, read(data / "areas.json"))
    m["stars"] = star_rows(m, issues)
    m["fixrows"] = fix_rows(m, issues)
    m["protein"] = protein_facts()
    m["quantum"] = quantum_facts()
    m["brains"] = brains_facts(check_trigalign(read(data / "trigalign.json")))
    return m


def render(data: Path, out: Path, widgets_root: Path | None = None) -> None:
    m = model(data)
    svgs = {(name, th): PANEL_FN[name](m, THEMES[th]) for name in PANELS for th in THEMES}
    for (name, th), svg in svgs.items():
        check_svg(f"{name}-{th}.svg", svg)
    art = render_art(m)
    for (name, th), svg in art.items():
        check_art(f"{name}-{th}.svg", svg)
    svgs.update(art)
    widgets = read_widgets(widgets_root)
    text = readme(m, svgs, widgets)
    check_readme(text)
    ledger = checks(m, svgs, text, widgets)  # everything is rendered and checked before anything is written
    (out / "assets").mkdir(parents=True, exist_ok=True)
    for (name, th), svg in svgs.items():
        write_if_changed(out / "assets" / f"{name}-{th}.svg", svg)
    for rel, svg in (widgets or {}).items():
        write_if_changed(out / rel, svg)
    write_if_changed(out / "README.md", text)
    write_if_changed(out / "CHECKS.md", ledger)
    extra = f", {len(widgets)} widget files" if widgets else ", no widget files"
    print(f"wrote {len(svgs)} svg{extra}, README.md and CHECKS.md to {out}")


# ------------------------------------------------------- trigalign capture ----
TRIG_EXAMPLE = ("tests/data/nencki/sub-24_task-oddball_block2_eeg.vmrk", "tests/data/nencki/sub-24_task-oddball_log_2.log")
TRIG_WHERE = "Event Type=Picture,Response"


def capture_trigalign(src: str, out: Path) -> None:
    """Run trigalign's README example from its source tree and keep the fields the brains card draws."""
    root = Path(src)
    sys.path.insert(0, str(root / "src"))
    sys.path.insert(0, str(root))
    import trigalign  # noqa: E402  (imported only here, from the path given)
    from trigalign import cli  # noqa: E402
    import contextlib
    import io

    argv = [str(root / TRIG_EXAMPLE[0]), str(root / TRIG_EXAMPLE[1]), "--log-where", TRIG_WHERE]
    buf_json, buf_text = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_json):
        status = cli.main(argv + ["--json"])
    with contextlib.redirect_stdout(buf_text):
        cli.main(argv)
    rep = json.loads(buf_json.getvalue())
    markers = {int(mo.group(1)): mo.group(2) for mo in re.finditer(r"#(\d+) .*?, on an? (.+?) marker", buf_text.getvalue())}
    log0 = rep["logs"][0]
    doc = dict(
        source=(f"trigalign {trigalign.__version__}, captured run of the README example on tests/data/nencki (excerpt "
                f"of OpenNeuro ds004621 v1.0.4, CC0): trigalign {Path(TRIG_EXAMPLE[0]).name} {Path(TRIG_EXAMPLE[1]).name} "
                f"--log-where '{TRIG_WHERE}'"),
        exit_status=status,
        triggers=dict(n=rep["triggers"]["n"], paired=rep["triggers"]["paired"]),
        unpaired_triggers=[dict(time=u["time"], code=u["code"]) for u in rep["unpaired_triggers"]],
        logs=[dict(
            n_events=log0["n_events"], n_paired=log0["n_paired"],
            segments=[{k: sg[k] for k in ("offset_s", "drift_ppm", "residual_sd_ms", "residual_max_ms", "n_pairs")}
                      for sg in log0["segments"]],
            unmatched=[dict({k: u[k] for k in ("event", "time", "status", "expected_trigger_time")},
                            **({"on_marker": markers[u["event"]]} if u["event"] in markers else {}))
                       for u in log0["unmatched"]],
            pairs=[{k: pr[k] for k in ("event", "time", "trigger_time", "residual_ms")} for pr in log0["pairs"]],
        )],
    )
    check_trigalign(doc)
    out.write_text(dump(doc), encoding="utf-8", newline="\n")
    print(f"wrote {out}: {log0['n_paired']} of {log0['n_events']} events paired")


def main() -> int:
    ap = argparse.ArgumentParser(description=inspect.cleandoc(__doc__).splitlines()[0])
    ap.add_argument("cmd", nargs="?", default="build",
                    choices=["build", "fetch", "stats", "capture-probe", "capture-trigalign"])
    ap.add_argument("--data", default=str(HERE / "data"), help="data directory")
    ap.add_argument("--out", default=str(HERE), help="render: output directory")
    ap.add_argument("--scoreprobe-src", help="capture-probe: directory that holds the scoreprobe package")
    ap.add_argument("--status", default=PROBE_PENDING, help="capture-probe: status line for the panel")
    ap.add_argument("--url", help="capture-probe: the scoreprobe repository, once it is public")
    ap.add_argument("--trigalign-src", help="capture-trigalign: a trigalign source tree (with tests/data)")
    ap.add_argument("--widgets", default=str(HERE), help="render: where the Action-drawn files are read from")
    a = ap.parse_args()
    data = Path(a.data)
    try:
        if a.cmd == "capture-probe":
            must(bool(a.scoreprobe_src), "capture-probe needs --scoreprobe-src")
            capture_probe(a.scoreprobe_src, a.status, a.url, data / "probe.json")
        elif a.cmd == "capture-trigalign":
            must(bool(a.trigalign_src), "capture-trigalign needs --trigalign-src")
            capture_trigalign(a.trigalign_src, data / "trigalign.json")
        elif a.cmd == "fetch":
            try:
                fetch(data, Client(os.environ.get("GITHUB_TOKEN", "")), dt.datetime.now(dt.timezone.utc))
            except SystemExit as e:
                raise SystemExit(scrub(e.code) if isinstance(e.code, str) else e.code) from None
            except ApiError:
                raise
            except Exception as e:   # one scrubbed line, no traceback: nothing of the exclusion can leak
                raise SystemExit(scrub(f"fetch: {type(e).__name__}: {e}; nothing written")) from None
        elif a.cmd == "stats":
            run_stats(data)
            print(f"wrote {data / 'stats.json'}")
        else:
            render(data, Path(a.out), Path(a.widgets))
    except ApiError as e:
        raise SystemExit(f"fetch: {e}; nothing written") from None
    return 0


if __name__ == "__main__":
    sys.exit(main())
