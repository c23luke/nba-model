"""How much is each extra point worth in the NBA — and does our bell-curve math price it right?

When the bettor compares, say, NOP +3.5 at +100 with NOP +1.5 at +133, it decides with a normal curve
(SD 14.14 around the line): every point near the line is worth about 2.8% of cover chance. If real NBA
results land on small margins (1-3 points) more often than a bell curve says, points near the line are
worth MORE than we think, and we've been giving them up too cheaply for a better price.

Six seasons (2020-21 to 2025-26), closing consensus spreads. For every game and both sides:
  r = the side's final margin + its closing spread (r > 0 = covered the close).
Reports, real vs bell curve:
  1. how often the final margin lands exactly k points from the closing line (k = 0..10)
  2. the cover chance when you get d extra points over the close (d = 0.5 .. 7), i.e. what buying
     points is worth, overall and by the size of the line
  3. a straight comparison like Wednesday's: +2 points of cover chance worth vs the price difference

Run: python -m engine.measure_points
"""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import NormalDist

from . import mine

SD = 14.14
N = NormalDist(0, SD)


def collect():
    rows = []
    for season in mine.SEASONS:
        games, s, e, days = mine.games_for(season)
        lines, how = mine.closing_lines(season, days, "")
        n = 0
        for g in games:
            ln = lines.get(f"{g.game_date.isoformat()}|{g.away}|{g.home}") or {}
            hs = ln.get("spread")
            if hs is None:
                continue
            margin = g.home_score - g.away_score
            rows.append({"season": season, "line": hs, "r": margin + hs})          # home side
            rows.append({"season": season, "line": -hs, "r": -margin - hs})        # away side
            n += 1
        print(f"{season}: {n} games with a closing line ({how})")
    return rows


def cover(rows, d):
    """Share that covers with d extra points (push = half, as a refund)."""
    w = sum(1 for x in rows if x["r"] + d > 0)
    p = sum(1 for x in rows if x["r"] + d == 0)
    return (w + 0.5 * p) / len(rows)


def normal_cover(d):
    # same push handling as the model: on a whole number, a push is the mass within half a point
    return 1 - N.cdf(-d)


def main():
    rows = collect()
    print(f"\n{len(rows) // 2} games, {len(rows)} sides\n")

    print("1. How often the result lands exactly k points from the closing line (one side's view, both sides counted)")
    print("   k   real    bell curve   ratio")
    for k in range(0, 11):
        real = sum(1 for x in rows if abs(x["r"]) == k) / len(rows) / (1 if k == 0 else 2)
        bell = (N.cdf(k + 0.5) - N.cdf(k - 0.5))
        print(f"  {k:>2}  {real:6.2%}   {bell:6.2%}      {real / bell:4.2f}")

    print("\n2. Cover chance with d extra points over the close (0 = the closing line itself)")
    groups = {"all lines": rows,
              "close within 3": [x for x in rows if abs(x["line"]) <= 3],
              "close 3.5 to 7": [x for x in rows if 3 < abs(x["line"]) <= 7],
              "close 7.5+": [x for x in rows if abs(x["line"]) > 7]}
    for name, rs in groups.items():
        base = cover(rs, 0)
        print(f"  {name} ({len(rs)} sides): covers the close {base:.1%}")
        print("     d    real gain   bell-curve gain   per point (real)")
        for d2 in range(1, 15):
            d = d2 / 2
            real = cover(rs, d) - base
            bell = normal_cover(d) - normal_cover(0)
            print(f"   +{d:<4} {real:+7.1%}      {bell:+7.1%}          {real / d:5.2%}")

    print("\n3. Wednesday's choice, as a general rule: buying 2 points off a line of about 3.5")
    near = [x for x in rows if 2.5 <= abs(x["line"]) <= 4.5]
    for give in (1, 2, 3):
        real = cover(near, 0) - cover(near, -give)
        bell = normal_cover(0) - normal_cover(-give)
        print(f"  giving up {give} point(s) near a 3-4 point line: real cover chance drops {real:.1%}, bell curve says {bell:.1%}")

    print("\nBy season, value of 2 points over the close (all lines):")
    by = defaultdict(list)
    for x in rows:
        by[x["season"]].append(x)
    for s, rs in by.items():
        print(f"  {s}: {cover(rs, 2) - cover(rs, 0):+.1%}  ({len(rs)} sides)")


if __name__ == "__main__":
    main()
