"""How often do Questionable / Doubtful / Probable players actually play?

The players model prices a day-to-day player both ways (plays / sits) and only bets when the edge holds
either way. If, say, 85% of Questionable players play, waiting on them throws away good bets; if it's
50%, waiting is right. This measures it from the NBA's own reports.

For every game day of 2024-25 and 2025-26: the official injury report posted around 5:30 PM ET that day
(falling back to nearby slots, and to the older hourly file names), every player listed for that day's
games, and whether he played (box score minutes > 0).

Run: python -m engine.measure_questionable
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta

from . import backtest_open as BO
from . import injury_report as IR
from .personnel import norm

SLOTS = ["05_30PM", "05_15PM", "05_45PM", "05_00PM", "06_00PM", "04_30PM", "05PM", "06PM", "04PM"]
EARLY = ["01_30PM", "01_00PM", "01PM", "12_30PM"]          # the early-afternoon report, for "does status change"


def fetch_day(d, slots):
    for s in slots:
        url = f"https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d.isoformat()}_{s}.pdf"
        try:
            pdf = IR._get(url)
        except Exception:
            pdf = None
        if pdf:
            try:
                rows, _ = IR.parse(pdf)
                return s, rows
            except Exception:
                return s, None
    return None, None


def main():
    played = {}                    # (date, team, norm name) -> minutes
    days = set()
    for season in BO.SEASONS:
        games, _ = BO.fetch_games(season)
        for g, rows in games:
            days.add(g.game_date)
            for r in rows:
                played[(g.game_date, r["team"], norm(r["name"]))] = r["min"]
            # players listed on a report who never appear in the box were inactive (did not play)
    days = sorted(days)
    print(f"{len(days)} game days")
    with ThreadPoolExecutor(8) as ex:
        evening = dict(zip(days, ex.map(lambda d: fetch_day(d, SLOTS), days)))
        early = dict(zip(days, ex.map(lambda d: fetch_day(d, EARLY), days)))
    found = sum(1 for v in evening.values() if v[1])
    print(f"evening reports found for {found} of {len(days)} days; slots used: "
          + ", ".join(f"{s} x{n}" for s, n in sorted(
              defaultdict(int, {s: sum(1 for v in evening.values() if v[0] == s) for s in SLOTS}).items(), key=lambda kv: -kv[1]) if n))
    by = defaultdict(lambda: [0, 0])                 # status -> [played, listed]
    by_season = defaultdict(lambda: [0, 0])
    change = defaultdict(lambda: [0, 0])             # early status -> [played, listed]
    for d in days:
        slot, rows = evening[d]
        if not rows:
            continue
        for r in rows:
            if not r.get("date"):
                continue
            try:
                rd = datetime.strptime(r["date"], "%m/%d/%Y").date()
            except ValueError:
                continue
            if rd != d:
                continue
            m = played.get((d, r["team"], r["key"]), 0)
            p = 1 if m and m > 0 else 0
            by[r["status"]][0] += p; by[r["status"]][1] += 1
            season = "2024-25" if d.year == 2024 or (d.year == 2025 and d.month < 7) else "2025-26"
            by_season[(season, r["status"])][0] += p; by_season[(season, r["status"])][1] += 1
        _, erows = early[d]
        for r in erows or []:
            try:
                rd = datetime.strptime(r["date"], "%m/%d/%Y").date()
            except (ValueError, TypeError):
                continue
            if rd != d:
                continue
            m = played.get((d, r["team"], r["key"]), 0)
            change[r["status"]][0] += 1 if m and m > 0 else 0; change[r["status"]][1] += 1
    print("\nEVENING REPORT (~5:30 PM ET) → did he play that night?")
    for st in IR.STATUSES:
        p, n = by[st]
        print(f"  {st:12} {p}/{n} played ({p / n:.0%})" if n else f"  {st:12} -")
    print("\nby season")
    for (season, st), (p, n) in sorted(by_season.items()):
        print(f"  {season} {st:12} {p}/{n} ({p / n:.0%})")
    print("\nEARLY-AFTERNOON REPORT (~1:30 PM ET) → did he play that night? (what we know when betting earlier)")
    for st in IR.STATUSES:
        p, n = change[st]
        print(f"  {st:12} {p}/{n} played ({p / n:.0%})" if n else f"  {st:12} -")


if __name__ == "__main__":
    main()
