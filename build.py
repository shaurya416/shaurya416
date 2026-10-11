#!/usr/bin/env python3
"""Regenerate the profile README and its panels.

    python3 build.py                 render data/ into assets/*.svg, README.md and CHECKS.md (no network)
    python3 build.py fetch           read the GitHub API into data/, then run the stats step (needs GITHUB_TOKEN)
    python3 build.py stats           rebuild data/stats.json from the other files in data/ (no network)
    python3 build.py capture-probe --scoreprobe-src PATH [--status v0.1.0] [--url URL]
                                     re-run scoreprobe on the grader its panel shows; rewrites data/probe.json
    python3 build.py --out DIR       render somewhere else (used to prove two builds give the same bytes)

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
    projects.json  hand-written: which of the packages in TOOLS are public, and their repository url
    stats.json   stats: every number the page shows, derived from the files above

Standard library only, Python 3.12 or later. Requests are serial and paced under GitHub's published
limits. Rendering reads no clock, no randomness and no network, so the same data gives the same bytes.
A text node that would leave its card or touch another mark fails the build, every total is checked
against its parts, every string that did not come from this file is escaped, and the output is checked
against an element allowlist before anything is written.
"""
from __future__ import annotations

import argparse
import datetime as dt
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

# neutrals are Primer's own tokens; one accent, and it always means "fixed"
THEMES = {
    "light": dict(bg="#ffffff", fg="#1f2328", muted="#59636e", line="#d1d9e0",
                  ink="#6e7781", cell="#d0d7de", accent="#0969da"),
    "dark": dict(bg="#0d1117", fg="#f0f6fc", muted="#9198a1", line="#3d444d",
                 ink="#7d8590", cell="#30363d", accent="#3987e5"),
}

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
    """One panel. Every text node and mark is registered as a box; a text box that leaves the card or
    touches another box fails the build."""

    def __init__(self, t: dict, title: str, desc: str):
        self.t = t
        self.texts: list[tuple] = []
        self.marks: list[tuple] = []
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {IMG} {H + GUT}" width="{IMG}" height="{H + GUT}" '
            f'role="img" aria-labelledby="t d">',
            f'<title id="t">{h(title)}</title>',
            f'<desc id="d">{h(desc)}</desc>',
            "<style>"
            f"text{{font-family:{FONT};font-size:{T}px;fill:{t['fg']}}}"
            f".m{{fill:{t['muted']}}}.a{{fill:{t['accent']}}}.b{{font-size:{BIG}px}}"
            ".e{text-anchor:end}.c{text-anchor:middle}"
            "</style>",
            f'<rect x=".5" y=".5" width="{CARD - 1}" height="{H - 1}" rx="6" fill="{t["bg"]}" stroke="{t["line"]}"/>',
        ]

    def add(self, s: str) -> None:
        self.parts.append(s)

    @staticmethod
    def box(x: float, y: float, s: str, size: float = T, anchor: str = "start") -> tuple:
        w = len(s) * size * ADV
        x0 = {"end": x - w, "middle": x - w / 2}.get(anchor, x)
        return (x0, x0 + w, y - 0.78 * size, y + 0.22 * size, s)

    def free(self, b: tuple, gap: float = 0.0) -> bool:
        """Whether a text box fits inside the card, `gap` units clear of everything placed."""
        inside = b[0] >= PAD - EPS and b[1] <= CARD - PAD + EPS and b[2] >= 0 and b[3] <= H
        wide = (b[0] - gap, b[1] + gap, b[2], b[3], b[4])
        return inside and not any(_hit(wide, o) for o in self.texts + self.marks)

    def _place(self, b: tuple) -> None:
        if b[0] < PAD - EPS or b[1] > CARD - PAD + EPS or b[2] < 0 or b[3] > H:
            raise SystemExit(f"overflow: {b[4]!r} spans {b[0]:.0f}..{b[1]:.0f} x {b[2]:.0f}..{b[3]:.0f}; "
                             f"the card's text area is {PAD}..{CARD - PAD} x 0..{H}")
        for o in self.texts + self.marks:
            if _hit(b, o):
                raise SystemExit(f"collision: {b[4]!r} overlaps {o[4]!r}")
        self.texts.append(b)

    def text(self, x: float, y: float, s: str, cls: str = "") -> None:
        c = cls.split()
        self._place(self.box(x, y, s, T, "end" if "e" in c else ("middle" if "c" in c else "start")))
        body = escape("".join(ch for ch in s if ord(ch) >= 32), quote=False)   # spaces kept: code is shown
        if "  " in s or s.startswith(" "):
            body = body.replace(" ", "\u00a0")   # SVG collapses runs of spaces; code keeps its indent
        attr = f' class="{cls}"' if cls else ""
        self.add(f'<text{attr} x="{n(x)}" y="{n(y)}">{body}</text>')

    def rect(self, x, y, w, hh, fill, rx=0.0, what="mark", extra="") -> None:
        b = (x, x + w, y, y + hh, what)
        for o in self.texts:
            if _hit(b, o):
                raise SystemExit(f"collision: {what} overlaps {o[4]!r}")
        self.marks.append(b)
        r = f' rx="{n(rx)}"' if rx else ""
        self.add(f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(hh)}"{r} fill="{fill}"{extra}/>')

    def readout(self, x: float, big: str, unit: str, y: float = 56) -> None:
        b1 = self.box(x, y, big, BIG)
        self._place(b1)
        self._place(self.box(b1[1] + 7, y, unit))
        self.add(f'<text x="{n(x)}" y="{n(y)}"><tspan class="b">{h(big)}</tspan>'
                 f'<tspan class="m" dx="7">{h(unit)}</tspan></text>')

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
    """Filings as a symmetric envelope (the shape of a waveform), fixes as squares by merge date."""
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

    slot = INNER / k
    cx = [PAD + slot * (i + .5) for i in range(k)]
    base = H - 38
    stack = max(x["others"] + x["own"] for x in b)
    pitch = min(11.0, 99 / max(stack, 1), slot - 2)
    sq = pitch - 2
    must(sq >= 2, f"{stack} fixes in one {unit} do not fit the panel")
    sq_top = base - max(33.0, stack * pitch)
    wave_top, wave_bot = 96, sq_top - 16
    mid, half = (wave_top + wave_bot) / 2, (wave_bot - wave_top) / 2
    peak = max(x["filed"] for x in b) or 1
    bw = min(8.0, slot - 4)
    tops = []
    for i, x in enumerate(b):
        c = x["filed"]
        hh = max(1.3, half * c / peak)
        tops.append(mid - hh)
        s.rect(cx[i] - bw / 2, mid - hh, bw, 2 * hh, t["ink"] if c else t["cell"], min(bw / 2, hh), f"bar {x['tick']}")
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
    s = Svg(t, "issues by area", desc)
    s.text(PAD, 22, "issues by area", "m")
    s.text(CARD - PAD, 22, plural(len(areas), "area"), "m e")
    s.readout(PAD, str(m["repos"]), "repositories")
    lines = len(shown) + (1 if rest else 0)
    y0 = 86
    pitch = min(18.0, (H - 30 - y0) / max(lines - 1, 1))
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


# ---------------------------------------------------------------- readme ----
FIRST_COL = "25%"   # width hint for the defect table's first column, so the description gets the room


def alt(name: str, m: dict) -> str:
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


def picture(name: str, svgs: dict, m: dict) -> str:
    v = {th: hashlib.sha1(svgs[(name, th)].encode()).hexdigest()[:8] for th in THEMES}
    return (
        "<picture>\n"
        f'<source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg?v={v["dark"]}">\n'
        f'<source media="(prefers-color-scheme: light)" srcset="assets/{name}-light.svg?v={v["light"]}">\n'
        f'<img alt="{h(alt(name, m))}" src="assets/{name}-light.svg?v={v["light"]}" width="{IMG}">\n'
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
INTRO = [
    "**Shaurya Singh** · Seattle, WA · cs + data science at UW, class of '27 · "
    "[shauryasingh.com](https://shauryasingh.com)",
    "",
    "i find what hurts, then build at it. so far: proteins, brains, quantum noise, classrooms, street safety, "
    "buildings, an underwater robot, and the code that grades things.",
    "",
    "```",
    '$ grep -rl "same field" ~/built/',
    "no matches",
    "```",
]
FIELD_GUIDE = [
    "- **proteins** · UW's DAIS lab: preprocessing, training runs and renders for DeepTracer, cryo-EM maps to 3D "
    "protein structures. no byline, and that's fine.",
    "- **brains** · four essays, taught to myself in public, optogenetics to connectomics (2022–23). now {trigalign}, "
    "for EEG recordings that dropped a trigger or two.",
    "- **quantum** · {shotfloor}: the score a perfect quantum computer gets from shot noise alone. 8 qubits, uniform "
    "target, 1,024 shots: 0.92 hellinger fidelity, not 1.",
    "- **classrooms** · co-founded SkillTern, its CTO (2022–23): computer science for 350+ students, built to run "
    "without me.",
    "- **street safety** · TurtleShell: K-means over 10,000+ LAPD crime datapoints and an iOS SOS app. Microsoft for "
    "Startups, then shut down on purpose (oct 2023).",
    "- **buildings** · a cabin designer that has to pass the Seattle residential code: rule engine, NSGA-II over "
    "cost, space and comfort, IFC export. runs locally, so no link.",
    "- **earlier** · H2OAquatics, an autonomous underwater vehicle aimed at ocean acidification; a phishing policy "
    "paper, runner-up at WatGov (Waterloo, 2023).",
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
    ("README field guide, quantum", "**quantum**", "8 qubits, uniform target, 1,024 shots: 0.92 hellinger fidelity",
     "shotfloor README.md, lines 9-20: the example for uniform:8 at 1024 shots prints a hellinger fidelity of 0.9239"),
    ("README things i made, normladder", "the same answer as", "8 of 14 answer-matching rules",
     'normladder README.md, line 9: the example for "1,000" against "1000" prints 8 of 14 rules match'),
    ("README things i made, scoreprobe", "feeds a grader", "4200 against 42",
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


def field_and_tools(projects: dict) -> list:
    """The field guide and the tools table: one line per world, one row per package, every name shown once here."""
    names = {n: proj(n, projects) for _, items in TOOLS for n, _ in items}
    out = ["### field guide", "", "one line per world i've wandered into.", ""]
    out += [line.format(**names) for line in FIELD_GUIDE]
    out += ["", "### things i made", ""]
    released = sum(p["status"] == "released" for p in projects.values())
    lead = "small python tools, each about one thing that quietly goes wrong."
    if released == 0:
        lead += " none is public yet, so no links: each name becomes one the day its repository is."
    elif released < len(projects):
        lead += " linked names are out; the rest become links the day their repositories are public."
    out += [lead, "", "| | | |", "|:--|:--|:--|"]
    for label, items in TOOLS:
        for i, (n, line) in enumerate(items):
            out.append(f"| {label if i == 0 else ''} | {names[n]} | {line} |")
    return out


def strip(m: dict) -> list:
    """The numbers of the side quest as a table a reader takes in before the sentence; every cell is checked."""
    o, lag, p, q = dict(m["outcome"]), m["lag"], m["prs"], m["q"]
    rows = [
        ("issues filed", m["total"], f"in {plural(m['repos'], 'repository', 'repositories')}, "
                                     f"{plural(len(m['areas']), 'area')}"),
        ("fixed by a merged pull request", m["fixed"],
         f"{o['others']} by other people, {o['own']} by me" if m["fixed"] else "none yet"),
        ("median hours to a fix", lag["median"] if lag["median"] is not None else "—",
         f"filed to merged, over {plural(lag['n'], 'fix', 'fixes')} by others" if lag["n"] else "no fix by others yet"),
        ("pull requests to other people's repositories", p["upstream"],
         f"{q['prs_merged']} merged, {q['prs_open']} open"),
    ]
    return [f"| since {m['start']} | | |", "|:--|--:|:--|", *[f"| {k} | {v} | {note} |" for k, v, note in rows]]


def side_quest(m: dict) -> list:
    o = dict(m["outcome"])
    have = {a["bucket"]: a["issues"] for a in m["areas"]}
    must(all(have.get(v, 0) >= 1 for v in SIDE_AREAS.values()), "the side-quest sentence names an empty area")
    kinds = ", ".join(list(SIDE_AREAS)[:-1]) + " and " + list(SIDE_AREAS)[-1]
    if m["fixed"]:
        fixed = (f"{m['fixed']} fixed by a merged pull request so far, {o['others']} of those by other people and "
                 f"{o['own']} by me.")
    else:
        fixed = "none fixed yet."
    lines = len(m["probe"]["source"])
    word = NUMBER_WORDS.get(lines, str(lines))
    return [
        "### grading the graders",
        "",
        *strip(m),
        "",
        f"{SIDE_ANCHOR} i read the code that decides whether an answer is right ({kinds}) and file what i find. "
        f"since {m['start']}: {plural(m['total'], 'issue')} in "
        f"{plural(m['repos'], 'repository', 'repositories')}, " + fixed,
        "",
        f"one example, small enough to read: scoreprobe on a {word}-line grader, before and after a one-line fix.",
        "",
        "<p>\n" + "{probe}" + "\n</p>",
    ]


def readme(m: dict, svgs: dict) -> str:
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
        "- regenerate: `python3 build.py fetch` reads the api (it needs `GITHUB_TOKEN`), then `python3 build.py` "
        "renders. same input, same bytes.",
    ]
    rest = [k for k in PANELS if k != "probe"]
    grid = "<p>\n" + "\n".join(picture(k, svgs, m) for k in rest) + "\n</p>"
    side = [x.replace("{probe}", picture("probe", svgs, m)) for x in side_quest(m)]
    return "\n".join([
        *INTRO,
        "",
        *side,
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
        *fixes_table(m),
        "",
        "</details>",
        "",
        *field_and_tools(m["projects"]),
        "",
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


# ---------------------------------------------------------------- guards ----
SVG_TAGS = {"svg", "title", "desc", "style", "rect", "path", "text", "tspan"}
README_TAGS = {"p": set(), "br": set(), "picture": set(), "source": {"media", "srcset"},
               "img": {"alt", "src", "width"}, "table": set(), "tr": set(), "th": {"align", "width"},
               "td": {"width"}, "a": {"href"}, "sub": set(), "wbr": set(), "details": set(), "summary": set()}
# Links go to GitHub, and to his own site — the one host added by hand, so the page never links anywhere a reader
# did not expect from a profile.
URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9][A-Za-z0-9._/-]*|https://shauryasingh\.com(?:/[A-Za-z0-9._/-]*)?")
ASSET_RE = re.compile(r"assets/[a-z]+-(light|dark)\.svg\?v=[0-9a-f]{8}")


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
    must("url(" not in style and "@import" not in style, f"guard: {name} style loads something")


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


def checks(m: dict, svgs: dict, text: str) -> str:
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
    st = "| since "
    add("README strip", "since", f"| since {m['start']} |", "issues.first_created_at", st)
    add("README strip", "issues filed", f"| {m['total']} |", "issues.total", "| issues filed |")
    add("README strip", "repositories", "in " + plural(m["repos"], "repository", "repositories"),
        "issues.distinct_repos", "| issues filed |")
    add("README strip", "areas", plural(len(m["areas"]), "area"), "len(ecosystems)", "| issues filed |")
    add("README strip", "fixed", f"| {m['fixed']} |", fixed_f, "| fixed by a merged pull request |")
    if m["fixed"]:
        add("README strip", "fixed by others", f"{o['others']} by other people",
            "outcomes.fixed_by_merged_pr_from_someone_else", "| fixed by a merged pull request |")
        add("README strip", "fixed by own PR", f"{o['own']} by me", "outcomes.fixed_by_his_own_merged_pr",
            "| fixed by a merged pull request |")
    if m["lag"]["n"]:
        add("README strip", "median hours", f"| {m['lag']['median']} |", "fix_lag_hours_filed_to_merge.median",
            "| median hours to a fix |")
        add("README strip", "fixes by others with hours", plural(m["lag"]["n"], "fix", "fixes"),
            "fix_lag_hours_filed_to_merge.n", "| median hours to a fix |")
    add("README strip", "PRs upstream", f"| {p['upstream']} |", "prs.upstream", "| pull requests to other people")
    add("README strip", "PRs merged", f"{q['prs_merged']} merged", "queries.prs_merged", "| pull requests to other people")
    add("README strip", "PRs open", f"{q['prs_open']} open", "queries.prs_open", "| pull requests to other people")
    sq = SIDE_ANCHOR
    add("README side quest", "since", f"since {m['start']}:", "issues.first_created_at", sq)
    add("README side quest", "issues filed", plural(m["total"], "issue") + " in", "issues.total", sq)
    add("README side quest", "repositories", "in " + plural(m["repos"], "repository", "repositories"),
        "issues.distinct_repos", sq)
    if m["fixed"]:
        add("README side quest", "fixed", f"{m['fixed']} fixed by a merged", fixed_f, sq)
        add("README side quest", "fixed by others", f"{o['others']} of those by other people",
            "outcomes.fixed_by_merged_pr_from_someone_else", sq)
        add("README side quest", "fixed by own PR", f"and {o['own']} by me", "outcomes.fixed_by_his_own_merged_pr", sq)
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
    out = ["# checks", "",
           "Every number this build computes from data/ and the field it is read from (data/stats.json unless another "
           "file is named).",
           "Written by `python3 build.py`, which fails if a value listed here is missing from the output it names.",
           "Panel values are looked up in the SVG text and its description; README values on the line they belong to.",
           "Figures the prose quotes from elsewhere are listed after the table, with their sources.",
           "", "| where | what | value as shown | field |", "|:--|:--|:--|:--|"]
    for where, what, value, field, _, _ in rows:
        out.append(f"| {md(where)} | {md(what)} | {md(value)} | `{field}` |")
    out += ["", "## quoted, not computed", "",
            "The prose also quotes a few figures from outside data/: the packages' own READMEs, the owner's resume and "
            "his personal site. This build cannot recompute them. It checks that each is still on the page, on the "
            "line it belongs to, so a figure cannot change on the page without its source being looked at again here.",
            "", "| where | figure as shown | source |", "|:--|:--|:--|"]
    for where, _, figure, source in QUOTED:
        out.append(f"| {md(where)} | {md(figure)} | {md(source)} |")
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
def render(data: Path, out: Path) -> None:
    m = derive(read(data / "stats.json"), read(data / "issues.json"), read(data / "notes.json"),
               read(data / "probe.json"))
    m["projects"] = check_projects(read(data / "projects.json"), m["login"], m["probe"])
    for x in m["by_rule"]:
        log(f"areas: {x['repo']} is placed by rule in {x['area']!r}; add it to data/areas.json")
    svgs = {(name, th): PANEL_FN[name](m, THEMES[th]) for name in PANELS for th in THEMES}
    for (name, th), svg in svgs.items():
        check_svg(f"{name}-{th}.svg", svg)
    text = readme(m, svgs)
    check_readme(text)
    ledger = checks(m, svgs, text)  # everything is rendered and checked before anything is written
    (out / "assets").mkdir(parents=True, exist_ok=True)
    for (name, th), svg in svgs.items():
        write_if_changed(out / "assets" / f"{name}-{th}.svg", svg)
    write_if_changed(out / "README.md", text)
    write_if_changed(out / "CHECKS.md", ledger)
    print(f"wrote {len(svgs)} svg, README.md and CHECKS.md to {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=inspect.cleandoc(__doc__).splitlines()[0])
    ap.add_argument("cmd", nargs="?", default="build", choices=["build", "fetch", "stats", "capture-probe"])
    ap.add_argument("--data", default=str(HERE / "data"), help="data directory")
    ap.add_argument("--out", default=str(HERE), help="render: output directory")
    ap.add_argument("--scoreprobe-src", help="capture-probe: directory that holds the scoreprobe package")
    ap.add_argument("--status", default=PROBE_PENDING, help="capture-probe: status line for the panel")
    ap.add_argument("--url", help="capture-probe: the scoreprobe repository, once it is public")
    a = ap.parse_args()
    data = Path(a.data)
    try:
        if a.cmd == "capture-probe":
            must(bool(a.scoreprobe_src), "capture-probe needs --scoreprobe-src")
            capture_probe(a.scoreprobe_src, a.status, a.url, data / "probe.json")
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
            render(data, Path(a.out))
    except ApiError as e:
        raise SystemExit(f"fetch: {e}; nothing written") from None
    return 0


if __name__ == "__main__":
    sys.exit(main())
