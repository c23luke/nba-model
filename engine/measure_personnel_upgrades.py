"""Does the players model get better if it learns from THIS season's results?

The players model rates teams only from each player's own numbers (box-score impact). Box scores
miss a lot that shows up in results: defense, fit, coaching, effort, a rotation that doesn't work.
Charlotte, Oct 2026: rated about average from its players, lost by 47 and the market had them near
the bottom. This test asks whether a team's results THIS SEASON, relative to what the players model
expected in those same games, should move its rating — and by how much.

  residual (per team, per game) = actual margin − players-model margin, from that team's side
  correction = sum of the team's residuals so far / (games so far + K)        (K = how slowly we trust it)
  new home margin = players-model margin + L × (home correction − away correction)

Only THIS season's games, only games before the one being priced (no peeking), only the current
players' model as the base. No prior-season team numbers anywhere.

Grid: K in 5, 10, 20, 40;  L in 0.5, 1.0. K and L are CHOSEN on 2024-25 and then TESTED untouched
on 2025-26 (out of sample). Graded the way we bet: calibrated to each day's opening lines, gap 3+,
against the opener; plus closing-line movement (CLV), whether the result beats the open per point of
gap, and the bottom-10-team split (the 46.8% problem).

Run: python -m engine.measure_personnel_upgrades
"""
from __future__ import annotations

import os
from collections import defaultdict

from . import backtest as BT
from . import backtest_open as BO

LIVE = "live (top-down, bench fill, B2B)"
GRID = [(k, l) for k in (5, 10, 20, 40) for l in (0.5, 1.0)]


def with_correction(rows, K, L):
    """rows: one season, any order. Returns copies with pred moved by this season's residuals so far."""
    res = defaultdict(list)          # team -> residuals from its own side
    out = []
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["date"]].append(r)
    for day in sorted(by_day):
        for r in by_day[day]:
            ch = sum(res[r["home"]]) / (len(res[r["home"]]) + K)
            ca = sum(res[r["away"]]) / (len(res[r["away"]]) + K)
            out.append({**r, "pred": r["pred"] + L * (ch - ca), "corr_home": ch, "corr_away": ca})
        for r in by_day[day]:
            e = r["actual"] - r["pred"]
            res[r["home"]].append(e)
            res[r["away"]].append(-e)
    return out


def market_rank(rows):
    """Running market rating (opening lines, home edge out), rank 1 = best, for each game's two teams."""
    tot, n = defaultdict(float), defaultdict(int)
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["date"]].append(r)
    ranks = {}
    for day in sorted(by_day):
        for r in by_day[day]:
            if r["open"] is None:
                continue
            e = -r["open"] - 1.7
            tot[r["home"]] += e; n[r["home"]] += 1
            tot[r["away"]] -= e; n[r["away"]] += 1
        order = sorted(n, key=lambda t: -tot[t] / n[t])
        rk = {t: i + 1 for i, t in enumerate(order)}
        for r in by_day[day]:
            ranks[(r["date"], r["home"], r["away"])] = (rk.get(r["home"]), rk.get(r["away"]), len(order))
    return ranks


def score(rows, ranks, label):
    cal = BO.calibrate_open(rows)
    xs = [r["gap"] for r in cal]
    _, binfo, tinfo = BT.ols(xs, [r["actual"] + r["open"] for r in cal])
    _, bmove, tmove = BT.ols(xs, [r["open"] - r["close"] for r in cal])
    g3 = BO.grade(cal, 3)
    first30 = BO.grade([r for r in cal if r["day"] <= 30], 3)
    bad, rest = [], []
    for r in cal:
        if abs(r["gap"]) < 3:
            continue
        hr, ar, n = ranks.get((r["date"], r["home"], r["away"]), (None, None, 0))
        side_rank = hr if r["gap"] > 0 else ar
        (bad if n >= 30 and side_rank and side_rank > 20 else rest).append(r)
    gb, gr = BO.grade(bad, 0), BO.grade(rest, 0)
    print(f"  {label:34} 3+: {BO.fmt(g3)}")
    print(f"  {'':34}     first 30 days 3+: {BO.fmt(first30)}")
    print(f"  {'':34}     bottom-10 team: {BO.fmt(gb)} | other teams: {BO.fmt(gr)}")
    print(f"  {'':34}     result beats open by {binfo:+.3f}/pt of gap (t {tinfo:.1f}); market moves toward us "
          f"{bmove:+.3f}/pt (t {tmove:.1f}); {len(cal)} games")
    return {"g3": g3, "info": binfo, "t": tinfo, "bad": gb, "rest": gr}


def pct(g):
    return g["w"] / (g["w"] + g["l"]) if g["w"] + g["l"] else 0.0


def main():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    data = {}
    for season in BO.SEASONS:
        games, days = BO.fetch_games(season)
        lines, how = BO.fetch_lines(season, days, key)
        preds, _ = BO.replay(season, games, lines)
        data[season] = preds[LIVE]
        print(f"{season}: {len(preds[LIVE])} games replayed, lines {how}")
    print()
    results = {}
    for season, rows in data.items():
        ranks = market_rank(rows)
        print(f"=== {season}")
        results[(season, "base")] = score(rows, ranks, "players model as is")
        for K, L in GRID:
            results[(season, K, L)] = score(with_correction(rows, K, L), ranks, f"+ this season's results K={K} L={L}")
        print()
    # choose on 2024-25: best information per point of gap (the cleanest measure), tie → more 3+ wins
    train = "2024-25"
    best = max(GRID, key=lambda kl: (round(results[(train, *kl)]["info"], 3), pct(results[(train, *kl)]["g3"])))
    print(f"=== CHOSEN ON {train}: K={best[0]}, L={best[1]} (info {results[(train, *best)]['info']:+.3f}/pt vs "
          f"base {results[(train, 'base')]['info']:+.3f})")
    test = "2025-26"
    b, n = results[(test, "base")], results[(test, *best)]
    print(f"=== OUT OF SAMPLE {test}:")
    print(f"    base:      3+ {BO.fmt(b['g3'])}; info {b['info']:+.3f}/pt (t {b['t']:.1f}); bottom-10 {BO.fmt(b['bad'])}")
    print(f"    corrected: 3+ {BO.fmt(n['g3'])}; info {n['info']:+.3f}/pt (t {n['t']:.1f}); bottom-10 {BO.fmt(n['bad'])}")
    both_b = [results[(s, "base")] for s in data]
    both_n = [results[(s, *best)] for s in data]
    def tot(rs, k):
        return sum(r[k]["w"] for r in rs), sum(r[k]["l"] for r in rs)
    for name, rs in (("base", both_b), ("corrected", both_n)):
        w, l = tot(rs, "g3"); bw, bl = tot(rs, "bad"); rw, rl = tot(rs, "rest")
        print(f"    BOTH SEASONS {name:9} 3+: {w}-{l} ({w / max(w + l, 1):.1%}) | bottom-10 {bw}-{bl} "
              f"({bw / max(bw + bl, 1):.1%}) | others {rw}-{rl} ({rw / max(rw + rl, 1):.1%})")


if __name__ == "__main__":
    main()
