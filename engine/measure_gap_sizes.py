"""HOW BIG DOES THE PLAYERS MODEL'S GAP NEED TO BE? (Caden 2026-11-11: "gap 3-4 ... 62-65 ... is it just good when
stacked ... check if 4+ is better or 5+").

Same replay as engine.measure_stacks / measure_agree (2024-25 and 2025-26, live players model, at the OPENING line).
  A. The players model alone (X1: the side it likes on every game), by gap size.
  B. One bet per game side where systems fired, by how many systems and the players model's gap on that side
     (negative = it likes the other side).
Run: python -m engine.measure_gap_sizes
"""
from __future__ import annotations

from collections import defaultdict

from . import backtest_open as BO
from .measure_stacks import season_rows

BANDS = [(-99, -3, "players model likes the OTHER side by 3+"), (-3, 0, "other side by 0-3"),
         (0, 3, "this side by 0-3"), (3, 4, "3-4"), (4, 5, "4-5"), (5, 6, "5-6"), (6, 8, "6-8"), (8, 99, "8+")]


def band(g):
    for lo, hi, name in BANDS:
        if lo <= g < hi:
            return name
    return None


def rec(rs):
    w, l = sum(r == "W" for r in rs), sum(r == "L" for r in rs)
    n = w + l
    return f"{w}-{l}" + (f"  {w / n:5.1%}  {w * 100 / 110 - l:+6.1f}u" if n else "")


def main():
    alone = defaultdict(lambda: defaultdict(list))
    stack = defaultdict(lambda: defaultdict(list))
    for season in BO.SEASONS:
        rows = season_rows(season)
        sides = defaultdict(list)
        for r in rows:
            if r["system"] == 301 and r["res"] != "P":
                for sc in (season, "both"):
                    alone[sc][band(r["gap"])].append(r["res"])
            elif r["bet"] == "spread" and r["system"] < 300 and r["system"] != 113 and r["gap"] is not None:
                sides[(r["game"], r["side"])].append(r)
        for ps in sides.values():
            if ps[0]["res"] == "P":
                continue
            k = len({p["system"] for p in ps})
            key = "1 system" if k == 1 else "2+ systems"
            for sc in (season, "both"):
                stack[(sc, key)][band(ps[0]["gap"])].append(ps[0]["res"])
    for sc in list(BO.SEASONS) + ["both"]:
        print(f"\n=== {sc} (opening line, -110)")
        print("  A. players model alone, by how many points it likes the side")
        for _, _, name in BANDS[3:]:
            print(f"    gap {name:6} {rec(alone[sc][name])}")
        for lo, name in ((3, "3+"), (4, "4+"), (5, "5+"), (6, "6+")):
            rs = [x for lo2, _, nm in BANDS[3:] if lo2 >= lo for x in alone[sc][nm]]
            print(f"    gap {name:6} {rec(rs)}")
        for key in ("1 system", "2+ systems"):
            print(f"  B. {key} on a side, by the players model's gap on that side")
            for _, _, name in BANDS:
                if stack[(sc, key)][name]:
                    print(f"    {name:44} {rec(stack[(sc, key)][name])}")


if __name__ == "__main__":
    main()
