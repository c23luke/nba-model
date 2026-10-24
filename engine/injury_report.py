"""The NBA's official injury report — fresher than ESPN's injury list.

The league posts a PDF every 15 minutes, all day (Eastern time in the file name):
  https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-20_09_45AM.pdf
Columns: Game Date | Game Time | Matchup | Team | Player Name ("Last, First") | Current Status | Reason.
Date, time, matchup and team print only on the first row of each block, Reason can wrap onto extra
lines, and a team that hasn't filed shows "NOT YET SUBMITTED".

We read the newest report and let it override ESPN's status for every player it lists:
  Out → out · Doubtful / Questionable → day-to-day (the model prices both versions) ·
  Probable / Available → playing.
If the report can't be fetched or read, nothing changes and the model uses ESPN as before.
"""
from __future__ import annotations

import io
import re
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .personnel import norm
from .teams import TEAMS, code

ET = ZoneInfo("America/New_York")
URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d}_{t}.pdf"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")
MAP = {"Out": "Out", "Doubtful": "Doubtful", "Questionable": "Questionable", "Probable": None, "Available": None}

_DATE = r"\d{2}/\d{2}/\d{4}"
_TIME = r"\d{1,2}:\d{2}\s*\(ET\)"
_MATCH = r"[A-Z]{3}@[A-Z]{3}"         # the report uses 3-letter codes (BOS, NOP, SAS, ...)
# columns can run together when the PDF's text is extracted ("UTA@MEMUtah Jazz"), so spaces are optional
_LEAD = re.compile(rf"^(?:(?P<date>{_DATE})\s*)?(?:(?P<time>{_TIME})\s*)?(?:(?P<match>{_MATCH})\s*)?(?P<rest>.*)$")
_STATUS = re.compile(r"(" + "|".join(STATUSES) + r")(?=\s|$|[A-Z\-])")
_TEAM_NAMES = sorted({v[0] for v in TEAMS.values()} | {"LA Clippers"}, key=len, reverse=True)


def slot_urls(now: datetime, back: int = 12) -> list[tuple[datetime, str]]:
    """The newest report slots (every 15 min, Eastern) from now going back."""
    et = now.astimezone(ET).replace(second=0, microsecond=0)
    et -= timedelta(minutes=et.minute % 15)
    out = []
    for i in range(back):
        t = et - timedelta(minutes=15 * i)
        out.append((t, URL.format(d=t.strftime("%Y-%m-%d"), t=t.strftime("%I_%M%p"))))
    return out


def _get(url: str, timeout: int = 20) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/pdf,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read() if r.status == 200 else None
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None
        raise


def latest(now: datetime | None = None, fetch=_get) -> dict | None:
    """The newest report: {"at": ET datetime, "url", "rows": [...], "not_submitted": [team codes]}."""
    for at, url in slot_urls(now or datetime.now(ET)):
        pdf = fetch(url)
        if pdf:
            rows, missing = parse(pdf)
            return {"at": at, "url": url, "rows": rows, "not_submitted": missing}
    return None


def lines_from_pdf(pdf: bytes) -> list[str]:
    try:
        import pdfplumber                  # installed in the workflows (pip install pdfplumber)
    except ImportError:                    # a watcher that restarted itself on new code skipped that step
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber==0.11.4"], check=True, timeout=180)
        import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for page in doc.pages:
            out += (page.extract_text(x_tolerance=1.5) or "").splitlines()
    return out


def parse_lines(lines: list[str]) -> tuple[list[dict], list[str]]:
    rows, missing = [], []
    date = match = team = None
    for raw in lines:
        s = " ".join(raw.split())
        if not s or s.startswith(("Injury Report:", "Page ")) or s.startswith("Game Date"):
            continue
        m = _LEAD.match(s)
        date = m["date"] or date
        if m["match"]:
            match, team = m["match"], None
        rest = m["rest"]
        for name in _TEAM_NAMES:
            if rest.startswith(name):
                try:
                    team = code(name)
                except Exception:
                    team = None
                rest = rest[len(name):].strip()
                break
        if "NOT YET SUBMITTED" in rest.upper():
            if team and team not in missing:
                missing.append(team)
            continue
        comma = rest.find(",")
        st = _STATUS.search(rest, comma + 1) if comma > 0 else None
        if not st or not team:
            continue                       # a wrapped Reason line, or something we can't place
        player, status, reason = rest[:st.start(1)].strip(), st.group(1), rest[st.end(1):].strip()
        last, first = [x.strip() for x in player.split(",", 1)]
        rows.append({"date": date, "matchup": match, "team": team, "player": f"{first} {last}",
                     "key": norm(f"{first} {last}"), "status": status, "reason": reason})
    return rows, missing


def parse(pdf: bytes) -> tuple[list[dict], list[str]]:
    return parse_lines(lines_from_pdf(pdf))


def for_games(rows: list[dict], games) -> list[dict]:
    """Only rows for games still to be played (date, away, home), and for each team only its NEXT game —
    the report also lists games already finished today, and a player out yesterday may be fine tonight."""
    want = {}
    for gd, away, home in games:
        for t in (away, home):
            if t not in want or gd < want[t][0]:
                want[t] = (gd, away, home)
    keep = []
    for r in rows:
        nxt = want.get(r["team"])
        if not nxt or not r.get("date") or not r.get("matchup"):
            continue
        try:
            rd = datetime.strptime(r["date"], "%m/%d/%Y").date()
            a, h = (code(x) for x in r["matchup"].split("@"))
        except Exception:
            continue
        if (rd, a, h) == nxt:
            keep.append(r)
    return keep


def submitted_for(report: dict | None, games) -> set[str]:
    """Teams whose report for their NEXT game is in: the matchup appears in the report and the team
    isn't marked NOT YET SUBMITTED. (A matchup with nobody hurt on either side may not appear; then we
    treat it as not in yet, which only means waiting — never assuming.)"""
    if not report:
        return set()
    seen = {(r["team"], r.get("date"), r.get("matchup")) for r in for_games(report["rows"], games)}
    matchups = {(d, m) for _, d, m in seen}
    want = {}
    for gd, away, home in games:
        for t in (away, home):
            if t not in want or gd < want[t][0]:
                want[t] = (gd, away, home)
    out = set()
    for t, (gd, away, home) in want.items():
        key = (gd.strftime("%m/%d/%Y") if hasattr(gd, "strftime") else str(gd))
        if any(d == key and m and {code(x) for x in m.split("@")} == {away, home} for d, m in matchups) \
                and t not in (report.get("not_submitted") or []):
            out.add(t)
    return out


def apply(rosters: dict[str, list[dict]], report: dict | None, games=None) -> list[str]:
    """Overwrite ESPN's status with the official one for every listed player (for each team's next game
    when `games` = [(date, away, home), ...] is given). Returns what changed."""
    if not report:
        return []
    rows = report["rows"] if games is None else for_games(report["rows"], games)
    by = {(r["team"], r["key"]): r for r in rows}
    changed = []
    for team, athletes in rosters.items():
        for a in athletes:
            name = a.get("fullName") or a.get("displayName") or ""
            r = by.get((team, norm(name)))
            if not r:
                continue
            before = [str(i.get("status", "")) for i in a.get("injuries") or []]
            new = MAP[r["status"]]
            a["injuries"] = [{"status": new, "source": "NBA official report"}] if new else []
            a["official_status"] = r["status"]
            if (before[:1] or ["active"])[0].lower() != (new or "active").lower():
                changed.append(f"{name} ({team}): {r['status']}" + (f" — {r['reason']}" if r["reason"] and r["reason"] != "-" else ""))
    return changed


def fingerprint(report: dict | None) -> str:
    if not report:
        return ""
    return "|".join(sorted(f"{r['team']}:{r['key']}:{r['status']}" for r in report["rows"]))


if __name__ == "__main__":         # python -m engine.injury_report  → read the newest report and show what we parsed
    rep = latest()
    if not rep:
        print("no report found in the last 3 hours")
    else:
        print(f"{rep['url']}\n{len(rep['rows'])} players, not yet submitted: {rep['not_submitted']}")
        for r in rep["rows"]:
            print(f"  {r['date']} {r['matchup']:8} {r['team']} {r['player']:28} {r['status']:12} {r['reason']}")
