"""Which situations move the line in a predictable direction (CLV), and does betting them early win?
Caden 2026-11-10: "backtest a CLV edge from the last 2 years, u have opening and closing lines".

Two seasons (2024-25, 2025-26) of spreads: the line the evening before (or that morning) = "open", the last
line before tip = "close". For each situation, from the side it points at:
  moved   = average points the line moved toward that side's bettors' benefit, open -> close
            (+ = we'd have beaten the close by betting at the open)
  beat    = share of games the close was better for us than the open (>= 0.5 pt), and worse
  ATS     = that side's record against the OPEN number, and against the CLOSE number
Every input here is known before the open: schedule, rest, streaks, last result, the open line itself, and the
rule systems (they read the same things). Nothing about who actually played. That keeps the injury leak out,
which is why the players model is NOT in this table (the replay knows who sat, so its "CLV" would be fake).
Run: python -m engine.measure_clv"""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from . import backtest as BT
from . import backtest_open as BO
from . import personnel as P
from . import sources
from .state import team_state
from .systems import evaluate, evaluate_early, evaluate_tests, label


def games_for(season):
    cfg = BO.SEASONS[season]
    days = [cfg["start"] + timedelta(i) for i in range((cfg["end"] - cfg["start"]).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        return [g for day in ex.map(lambda d: BT._safe(sources.espn_day, d) or [], days) for g, _ in day if g.final]


def rows_for(season):
    lines = json.loads((P.STATIC / f"odds_openclose_{season.replace('-', '_')}.json").read_text())
    totals = json.loads((P.STATIC / f"odds_totals_{season.replace('-', '_')}.json").read_text())
    start = BO.SEASONS[season]["start"]
    games = sorted(games_for(season), key=lambda g: (g.game_date, str(g.id)))
    by_day = defaultdict(list)
    for g in games:
        by_day[g.game_date].append(g)
    finals, out = [], []
    for day in sorted(by_day):
        for g in by_day[day]:
            k = f"{day.isoformat()}|{g.away}|{g.home}"
            ln = lines.get(k) or {}
            op, cl = ln.get("open"), ln.get("close")
            tot = totals.get(k) or {}
            if op is None or cl is None:
                continue
            hs, as_ = team_state(g.home, finals, day), team_state(g.away, finals, day)
            margin = g.home_score - g.away_score
            tags = situations(g, hs, as_, op, (day - start).days)
            sys = []
            for p in (evaluate(g, hs, as_, op, tot.get("open"), None) + evaluate_tests(g, hs, as_, op, tot.get("open"))
                      + evaluate_early(g, hs, as_, op, tot.get("open"), (day - start).days)):
                if p.bet == "spread" and p.line is not None and p.system < 300:
                    sys.append((f"system {label(p.system)}", "home" if p.side == g.home else "away"))
            out.append({"season": season, "open": op, "close": cl, "margin": margin, "tags": tags + sys})
        finals += by_day[day]
    return out


def situations(g, hs, as_, op, day_n):
    """(name, side) pairs; side = which team the situation points at."""
    t = []
    def both(name, cond_home, cond_away):
        if cond_home: t.append((name, "home"))
        if cond_away: t.append((name, "away"))
    # every game, both directions (the baseline)
    t += [("every home team", "home"), ("every away team", "away")]
    # the opening number
    if op <= -10: t.append(("home fav 10+ at the open", "home"))
    elif op <= -6.5: t.append(("home fav 6.5-9.5", "home"))
    elif op <= -3: t.append(("home fav 3-6", "home"))
    elif op < 0: t.append(("home fav under 3", "home"))
    elif op <= 3: t.append(("home dog 0-3", "home"))
    elif op <= 6.5: t.append(("home dog 3.5-6.5", "home"))
    else: t.append(("home dog 7+", "home"))
    if op in (-3.0, 3.0, -7.0, 7.0): t.append((f"open on a key number ({abs(op):g}), the favorite", "home" if op < 0 else "away"))
    # rest
    hb, ab = hs.days_rest == 0, as_.days_rest == 0
    both("on a back-to-back, opponent rested", hb and not ab, ab and not hb)
    both("rested team vs a back-to-back", ab and not hb, hb and not ab)
    if hs.days_rest is not None and as_.days_rest is not None:
        d = hs.days_rest - as_.days_rest
        both("2+ more days of rest", d >= 2, d <= -2)
    both("3 games in 4 nights", hs.games_last3 >= 2, as_.games_last3 >= 2)
    # form
    both("won last game by 20+", (hs.last_margin or 0) >= 20, (as_.last_margin or 0) >= 20)
    both("lost last game by 20+", (hs.last_margin or 0) <= -20, (as_.last_margin or 0) <= -20)
    both("won 5+ in a row", hs.win_streak >= 5, as_.win_streak >= 5)
    both("lost 5+ in a row", hs.lose_streak >= 5, as_.lose_streak >= 5)
    both("last game went to OT", hs.last_ot, as_.last_ot)
    if day_n <= 21:
        t += [("first 3 weeks: home team", "home"), ("first 3 weeks: away team", "away")]
    if hs.win_pct is not None and as_.win_pct is not None and hs.games >= 10 and as_.games >= 10:
        both("better record (10+ games, by .150+)", hs.win_pct - as_.win_pct >= 0.15, as_.win_pct - hs.win_pct >= 0.15)
    return t


def stats(rs):
    n = len(rs)
    if not n:
        return None
    moved = sum(r["mv"] for r in rs) / n
    beat = sum(r["mv"] >= 0.5 for r in rs) / n
    worse = sum(r["mv"] <= -0.5 for r in rs) / n
    def ats(key):
        w = sum(r[key] > 0 for r in rs); l = sum(r[key] < 0 for r in rs)
        return w, l
    return n, moved, beat, worse, ats("ro"), ats("rc")


def main():
    allrows = []
    for season in BO.SEASONS:
        allrows += rows_for(season)
    for scope in list(BO.SEASONS) + ["both"]:
        rows = allrows if scope == "both" else [r for r in allrows if r["season"] == scope]
        cats = defaultdict(list)
        for r in rows:
            for name, side in r["tags"]:
                # home spread: open -3, close -5 => the market moved 2 toward home; a home bettor at -3 beat -5 by 2
                mv = (r["open"] - r["close"]) if side == "home" else (r["close"] - r["open"])
                ro = (r["margin"] + r["open"]) if side == "home" else (-r["margin"] - r["open"])
                rc = (r["margin"] + r["close"]) if side == "home" else (-r["margin"] - r["close"])
                cats[f"{name} ({side})" if not name.startswith(("every", "system", "first")) else name].append(
                    {"mv": mv, "ro": ro, "rc": rc})
        print(f"\n=== {scope}: {len(rows)} games with an open and a close")
        print(f"  {'situation (side it points at)':58} {'n':>5} {'moved':>7} {'beat':>6} {'worse':>6}   ATS open        ATS close")
        res = [(k, stats(v)) for k, v in cats.items()]
        res = [(k, s) for k, s in res if s and s[0] >= 25]
        res.sort(key=lambda x: -x[1][1])
        for k, (n, moved, beat, worse, (wo, lo), (wc, lc)) in res:
            po = wo / (wo + lo) if wo + lo else 0
            pc = wc / (wc + lc) if wc + lc else 0
            print(f"  {k[:58]:58} {n:5d} {moved:+7.2f} {beat:6.0%} {worse:6.0%}   {wo:3d}-{lo:<3d} {po:5.1%}   {wc:3d}-{lc:<3d} {pc:5.1%}")


if __name__ == "__main__":
    main()
