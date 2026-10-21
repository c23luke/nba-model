"""Does the players model miss schedule fatigue it doesn't price yet?

The model already takes 1.7 points off the second night of a back-to-back. This measures what else
is left in its errors, on the same two-season replay as engine/backtest_open.py:
  - 3rd game in 4 nights, 4th game in 6 nights
  - miles travelled since the last game (all games, and only on a back-to-back)
  - extra rest (days off beyond one, capped at 3)
  - long road trips (4th+ straight road game)
  - visitors at altitude (Denver, Utah)
For each one: how much the model's margin misses by (and the t-stat), whether the opening line
already prices it, and an out-of-sample check (fit on one season, test on the other) of margin
error and of the 3+ gap bets at the opening line. A flag is worth adding only if it helps out of
sample in both directions.

Run: python -m engine.measure_fatigue   (uses the cached opening/closing lines in data_static)
"""
from __future__ import annotations

import math
import os
from collections import defaultdict
from datetime import timedelta

from . import backtest_open as BO

LIVE = "live (top-down, bench fill, B2B)"
ARENA = {  # lat, lon
    "ATL": (33.757, -84.396), "BOS": (42.366, -71.062), "BKN": (40.683, -73.975), "CHA": (35.225, -80.839),
    "CHI": (41.881, -87.674), "CLE": (41.496, -81.688), "DAL": (32.790, -96.810), "DEN": (39.749, -105.008),
    "DET": (42.341, -83.055), "GSW": (37.768, -122.388), "HOU": (29.751, -95.362), "IND": (39.764, -86.155),
    "LAC": (33.945, -118.341), "LAL": (34.043, -118.267), "MEM": (35.138, -90.051), "MIA": (25.781, -80.188),
    "MIL": (43.045, -87.917), "MIN": (44.980, -93.276), "NOP": (29.949, -90.082), "NYK": (40.751, -73.993),
    "OKC": (35.463, -97.515), "ORL": (28.539, -81.384), "PHI": (39.901, -75.172), "PHX": (33.446, -112.071),
    "POR": (45.532, -122.667), "SAC": (38.580, -121.500), "SAS": (29.427, -98.437), "TOR": (43.643, -79.379),
    "UTA": (40.768, -111.901), "WAS": (38.898, -77.021),
}
FEATURES = ["3 in 4", "4 in 6", "miles (000s)", "miles on B2B (000s)", "extra rest days", "long road trip",
            "visitor at altitude"]


def miles(a, b):
    (la1, lo1), (la2, lo2) = ARENA.get(a, (0, 0)), ARENA.get(b, (0, 0))
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return 3958.8 * math.acos(max(-1.0, min(1.0, c)))


def team_flags(games):
    """(date, team) -> that team's schedule flags for that game."""
    sched = defaultdict(list)                                   # team -> [(date, arena, home?)]
    for g, _ in games:
        sched[g.home].append((g.game_date, g.home, True))
        sched[g.away].append((g.game_date, g.home, False))
    out = {}
    for team, gs in sched.items():
        gs.sort()
        road = 0
        for i, (d, arena, home) in enumerate(gs):
            prev = gs[i - 1] if i else None
            road = 0 if home else road + 1
            n3 = sum(1 for x in gs[:i] if d - timedelta(3) <= x[0] < d)
            n5 = sum(1 for x in gs[:i] if d - timedelta(5) <= x[0] < d)
            gap = (d - prev[0]).days if prev else 9
            mi = miles(prev[1], arena) / 1000 if prev else 0.0
            out[(d, team)] = {
                "3 in 4": float(n3 >= 2), "4 in 6": float(n5 >= 3),
                "miles (000s)": mi, "miles on B2B (000s)": mi if gap == 1 else 0.0,
                "extra rest days": float(min(max(gap - 2, 0), 2)),
                "long road trip": float(road >= 4),
                "at altitude": float(arena in ("DEN", "UTA") and not home and (not prev or prev[1] not in ("DEN", "UTA"))),
            }
    return out


def features(r, flags):
    h, a = flags.get((r["date"], r["home"])), flags.get((r["date"], r["away"]))
    if not h or not a:
        return None
    x = {f: h[f] - a[f] for f in FEATURES if f != "visitor at altitude"}
    x["visitor at altitude"] = a["at altitude"]                # helps the home team
    return x


def lstsq(X, y):
    """Multiple regression with an intercept: coefficients and t-stats (pure Python)."""
    rows = [[1.0] + xi for xi in X]
    k = len(rows[0])
    A = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    b = [sum(r[i] * yi for r, yi in zip(rows, y)) for i in range(k)]
    inv = [[float(i == j) for j in range(k)] for i in range(k)]
    M = [row[:] for row in A]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            return [0.0] * k, [0.0] * k
        M[c], M[p], inv[c], inv[p] = M[p], M[c], inv[p], inv[c]
        piv = M[c][c]
        M[c] = [v / piv for v in M[c]]
        inv[c] = [v / piv for v in inv[c]]
        for r in range(k):
            if r != c and M[r][c]:
                f = M[r][c]
                M[r] = [a - f * b_ for a, b_ in zip(M[r], M[c])]
                inv[r] = [a - f * b_ for a, b_ in zip(inv[r], inv[c])]
    beta = [sum(inv[i][j] * b[j] for j in range(k)) for i in range(k)]
    resid = [yi - sum(bj * xj for bj, xj in zip(beta, r)) for r, yi in zip(rows, y)]
    s2 = sum(e * e for e in resid) / max(len(y) - k, 1)
    se = [math.sqrt(max(inv[i][i] * s2, 0)) for i in range(k)]
    return beta, [beta[i] / se[i] if se[i] else 0.0 for i in range(k)]


def bets(rows):
    cal = BO.calibrate_open(rows)
    return {t: BO.grade(cal, t) for t in (3, 4)}


def main():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    data = {}
    for season in BO.SEASONS:
        games, days = BO.fetch_games(season)
        lines, how = BO.fetch_lines(season, days, key)
        preds, _ = BO.replay(season, games, lines)
        flags = team_flags(games)
        rows = []
        for r in preds[LIVE]:
            x = features(r, flags)
            if x is not None:
                rows.append({**r, "x": x})
        data[season] = rows
        n = {f: sum(1 for r in rows if r["x"][f]) for f in FEATURES}
        print(f"=== {season}: {len(rows)} games (lines {how}); games where each flag differs: "
              + ", ".join(f"{f} {n[f]}" for f in FEATURES))

    allr = [r for rs in data.values() for r in rs]
    print("\nOne flag at a time. Model miss = actual home margin minus the model's margin (it already has home court"
          " and back-to-backs).\nMarket miss = actual margin minus the opening line. Positive = helps the team with the flag.")
    for f in FEATURES:
        sub = [r for r in allr if r["x"][f]]
        bm, tm = lstsq([[r["x"][f]] for r in allr], [r["actual"] - r["pred"] for r in allr])
        mk = [r for r in allr if r["open"] is not None]
        bk, tk = lstsq([[r["x"][f]] for r in mk], [r["actual"] + r["open"] for r in mk])
        print(f"  {f:22} model misses {bm[1]:+.2f} pts per unit (t {tm[1]:+.1f}) | opening line misses {bk[1]:+.2f} "
              f"(t {tk[1]:+.1f}) | {len(sub)} games")

    print("\nAll flags together (model miss):")
    beta, t = lstsq([[r["x"][f] for f in FEATURES] for r in allr], [r["actual"] - r["pred"] for r in allr])
    for f, b, tt in zip(FEATURES, beta[1:], t[1:]):
        print(f"  {f:22} {b:+.2f} (t {tt:+.1f})")

    print("\nOut of sample: fit on one season, apply to the other.")
    seasons = list(data)
    for fit, test in ((seasons[0], seasons[1]), (seasons[1], seasons[0])):
        for keep in (FEATURES, [f for f, tt in zip(FEATURES, t[1:]) if abs(tt) >= 2.0]):
            if not keep:
                continue
            b, _ = lstsq([[r["x"][f] for f in keep] for r in data[fit]], [r["actual"] - r["pred"] for r in data[fit]])
            adj = [{**r, "pred": r["pred"] + sum(bi * r["x"][f] for bi, f in zip(b[1:], keep))} for r in data[test]]
            rmse = lambda rs: math.sqrt(sum((r["actual"] - r["pred"]) ** 2 for r in rs) / len(rs))
            before, after = bets(data[test]), bets(adj)
            label = "all flags" if keep == FEATURES else "only t>=2 flags: " + ", ".join(keep)
            print(f"  fit {fit} -> test {test} ({label})")
            print(f"     margin error {rmse(data[test]):.3f} -> {rmse(adj):.3f}")
            for th in (3, 4):
                print(f"     {th}+ gaps vs open: {BO.fmt(before[th])}\n                    -> {BO.fmt(after[th])}")


if __name__ == "__main__":
    main()
