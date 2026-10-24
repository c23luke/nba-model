"""Does the players model get fooled by BAD teams?

Caden's question (Oct 2026): Charlotte lost by 47, the market has them near the bottom, and the
players model still rates them about average and keeps betting them. Is that a real blind spot?

Two seasons (2024-25, 2025-26), every game with a personnel gap (data_static/personnel_gaps.json,
the live model replayed with only what was known before each game, calibrated to the opening lines)
and an opening line. We look at the bets the model would make (gap 3+) and split them two ways:

  1. How good the market thinks the team we'd bet is (its average opening-line rating so far
     this season, ranked 1-30): bottom 10 vs middle 10 vs top 10.
  2. Whether the team's RESULTS so far are worse than the market expected (average actual margin
     minus average expected margin, before this game): results 4+ pts/game worse than the market
     expected, within 4, 4+ better. "Worse" is the Charlotte case — losing badly AND rated average by us.

For each group: record against the opening line, CLV (did the line move our way), both for the
first 30 days and the whole season. If bottom-10 or "results much worse" bets lose and lose CLV,
the model needs a fix for those teams. If they hold up, the model is right and the market is wrong.

Run: python -m engine.measure_badteams
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import mine
from . import personnel as P

HCA = P.HOME_COURT
SEASONS = ("2024-25", "2025-26")


def season_rows(season):
    games, s, e, days = mine.games_for(season)
    lines = json.loads((P.STATIC / f"odds_openclose_{season.replace('-', '_')}.json").read_text())
    gaps = json.loads((P.STATIC / "personnel_gaps.json").read_text())
    # running team numbers, updated after each day (only games BEFORE the one being bet count)
    exp_sum, act_sum, n = defaultdict(float), defaultdict(float), defaultdict(int)
    rating_sum, rating_n = defaultdict(float), defaultdict(int)
    out = []
    by_day = defaultdict(list)
    for g in games:
        by_day[g.game_date].append(g)
    for day in sorted(by_day):
        todays = []
        for g in by_day[day]:
            k = f"{day.isoformat()}|{g.away}|{g.home}"
            ln, gp = lines.get(k) or {}, gaps.get(k)
            if ln.get("open") is None:
                continue
            exp_home = -ln["open"]                                   # expected home margin at the open
            # market rating (neutral court): home = exp - HCA, away = -(exp - HCA); include today's line
            rating_sum[g.home] += exp_home - HCA; rating_n[g.home] += 1
            rating_sum[g.away] += -(exp_home - HCA); rating_n[g.away] += 1
            todays.append((g, ln, gp, exp_home))
        ranks = sorted((rating_sum[t] / rating_n[t], t) for t in rating_n)
        rank = {t: i + 1 for i, (_, t) in enumerate(reversed(ranks))}  # 1 = best
        for g, ln, gp, exp_home in todays:
            actual = g.home_score - g.away_score
            if gp and abs(gp["gap"]) >= 3 and ln.get("close") is not None:
                home = gp["gap"] > 0
                side = g.home if home else g.away
                res = actual + ln["open"]
                won = None if res == 0 else (res > 0) == home
                clv = (ln["open"] - ln["close"]) if home else (ln["close"] - ln["open"])
                gn = n[side]
                vs_mkt = (act_sum[side] - exp_sum[side]) / gn if gn else None
                out.append({"season": season, "day": gp["day"], "side": side, "rank": rank.get(side),
                            "teams": len(rank), "games_before": gn, "vs_mkt": vs_mkt,
                            "won": won, "clv": clv, "gap": abs(gp["gap"])})
        # after the day: update results vs expectation
        for g, ln, gp, exp_home in todays:
            actual = g.home_score - g.away_score
            for t, a, ex in ((g.home, actual, exp_home), (g.away, -actual, -exp_home)):
                act_sum[t] += a; exp_sum[t] += ex; n[t] += 1
    return out


def line(name, rows):
    w = sum(r["won"] is True for r in rows)
    l = sum(r["won"] is False for r in rows)
    clv = [r["clv"] for r in rows]
    if not rows:
        return f"    {name:44} -"
    return (f"    {name:44} {w:>3}-{l:<3} ({w / (w + l):.1%})  CLV {sum(clv) / len(clv):+.2f} pts"
            f"  (moved our way {sum(c > 0 for c in clv)}, against {sum(c < 0 for c in clv)})"
            if w + l else f"    {name:44} no graded bets")


def report(rows, title):
    print(title)
    print(line("all 3+ bets", rows))
    print("  by how good the MARKET thinks the team we bet is (rank 1-30 so far)")
    print(line("bottom 10 (rank 21-30)", [r for r in rows if r["rank"] and r["rank"] > 20]))
    print(line("middle 10 (rank 11-20)", [r for r in rows if r["rank"] and 10 < r["rank"] <= 20]))
    print(line("top 10 (rank 1-10)", [r for r in rows if r["rank"] and r["rank"] <= 10]))
    print("  by the team's RESULTS so far vs what the market expected (needs 2+ games)")
    has = [r for r in rows if r["games_before"] >= 2 and r["vs_mkt"] is not None]
    print(line("results 4+ pts/game WORSE than expected", [r for r in has if r["vs_mkt"] <= -4]))
    print(line("within 4", [r for r in has if -4 < r["vs_mkt"] < 4]))
    print(line("results 4+ pts/game BETTER than expected", [r for r in has if r["vs_mkt"] >= 4]))
    print(line("bottom 10 AND results 4+ worse", [r for r in has if r["rank"] > 20 and r["vs_mkt"] <= -4]))
    print(line("fewer than 2 games played (no results yet)", [r for r in rows if r["games_before"] < 2]))
    print()


def main():
    allrows = []
    for s in SEASONS:
        rows = season_rows(s)
        allrows += rows
        report([r for r in rows if r["day"] <= 30], f"=== {s}, first 30 days")
        report(rows, f"=== {s}, whole season")
    report([r for r in allrows if r["day"] <= 30], "=== BOTH SEASONS, first 30 days")
    report(allrows, "=== BOTH SEASONS, whole season")


if __name__ == "__main__":
    main()
