"""Follow the league's direction on totals, instead of betting a fixed over.

Idea (Caden): the game changes every year — more threes, faster pace, rule changes — and the books are
slow to catch up. So don't assume "early-season overs" (E8); measure which way THIS season's totals are
missing and bet with it while the books lag.

For each of six seasons (2020-21 .. 2025-26), every game graded against the CLOSING total:
  running miss = average of (actual total − closing total) over this season's games before today
  rule: when the running miss is ≥ +X (over Y+ games), bet the over; ≤ −X, bet the under
Reported by stage of season, every season separately, for X = 1, 2, 3 and Y = 30, 60 games.
Nothing is fitted; the direction comes only from games already played this season.

Run: python -m engine.measure_league_shift
"""
from __future__ import annotations

from collections import defaultdict

from . import mine

STAGES = [("days 0-30", 0, 30), ("days 31-71", 31, 71), ("days 72+", 72, 999)]


def wl(rs):
    w = sum(1 for r in rs if r > 0); l = sum(1 for r in rs if r < 0)
    return w, l


def fmt(w, l):
    return f"{w}-{l} ({w / max(w + l, 1):.1%}, {w - 1.1 * l:+.1f}u)"


def main():
    rules = [(x, y) for y in (30, 60) for x in (1.0, 2.0, 3.0)]
    total = {r: defaultdict(list) for r in rules}
    fixed_over = defaultdict(list)
    for season in mine.SEASONS:
        try:
            gs, s, e, days = mine.games_for(season)
            cl, how = mine.closing_lines(season, days, "")
        except Exception as ex:
            print(f"{season}: {ex}")
            continue
        games = sorted([g for g in gs if (cl.get(f"{g.game_date.isoformat()}|{g.away}|{g.home}") or {}).get("total") is not None],
                       key=lambda g: (g.game_date, g.id))
        by_day = defaultdict(list)
        for g in games:
            by_day[g.game_date].append(g)
        misses = []
        per = {r: defaultdict(list) for r in rules}
        for day in sorted(by_day):
            stage = next(n for n, lo, hi in STAGES if lo <= (day - s).days <= hi)
            run = sum(misses) / len(misses) if misses else 0.0
            todays = []
            for g in by_day[day]:
                t = cl[f"{day.isoformat()}|{g.away}|{g.home}"]["total"]
                d = g.home_score + g.away_score - t
                todays.append(d)
                if (day - s).days <= 30:
                    fixed_over[season].append(d)
                for (x, y) in rules:
                    if len(misses) >= y and abs(run) >= x:
                        per[(x, y)][stage].append(d if run > 0 else -d)
            misses += todays
        avg = sum(misses) / max(len(misses), 1)
        print(f"\n=== {season}: {len(games)} games with a closing total ({how}); whole-season actual − close {avg:+.2f}")
        print(f"    E8-style fixed over, first 30 days: {fmt(*wl(fixed_over[season]))}")
        for r in rules:
            cells = " | ".join(f"{n}: {fmt(*wl(per[r][n]))}" for n, _, _ in STAGES)
            allr = [v for n in per[r] for v in per[r][n]]
            print(f"    follow direction, |miss| ≥ {r[0]:g} after {r[1]} games → {fmt(*wl(allr))}   [{cells}]")
            for n in per[r]:
                total[r][n] += per[r][n]
    print("\n=== SIX SEASONS")
    allf = [v for s in fixed_over for v in fixed_over[s]]
    print(f"    E8-style fixed over, first 30 days: {fmt(*wl(allf))}")
    for r in rules:
        allr = [v for n in total[r] for v in total[r][n]]
        cells = " | ".join(f"{n}: {fmt(*wl(total[r][n]))}" for n, _, _ in STAGES)
        print(f"    follow direction, |miss| ≥ {r[0]:g} after {r[1]} games → {fmt(*wl(allr))}   [{cells}]")


if __name__ == "__main__":
    main()
