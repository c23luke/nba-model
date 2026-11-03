"""Does a system still win when the players model disagrees? And how do 2-3 systems on one side do?

Caden (2026-11-02): "some of the models aren't even good ... and the players model likes the other side,
how do u decide" / "what are the hit rates when 2 or 3 systems fire at once".

Replays 2024-25 and 2025-26 at the OPENING line (same replay as engine.measure_stacks). Spread bets only
(the players model only rates sides). One row per game+side, so a side three systems liked counts once.
  players  = how many points the players model liked THIS side by at the open (negative = other side)
Run: python -m engine.measure_agree
"""
from __future__ import annotations

from collections import defaultdict

from . import backtest_open as BO
from .measure_stacks import season_rows
from .systems import group, label


def rec(rs):
    w, l, p = (sum(r == x for r in rs) for x in "WLP")
    n = w + l
    roi = (w * 100 / 110 - l) / n if n else 0.0     # at -110
    return f"{w}-{l}" + (f"-{p}" if p else "") + (f"  {w / n:5.1%}  roi {roi:+.1%}" if n else "")


def pbucket(g):
    if g is None:
        return "no rating"
    if g >= 3:
        return "agrees 3+"
    if g > 0:
        return "agrees 0-3"
    if g > -3:
        return "disagrees 0-3"
    return "disagrees 3+"


BUCKETS = ("agrees 3+", "agrees 0-3", "disagrees 0-3", "disagrees 3+", "no rating")


def main():
    all_rows = {}
    for season in BO.SEASONS:
        all_rows[season] = [r for r in season_rows(season)
                            if r["bet"] == "spread" and r["system"] < 300 and r["system"] != 113]
        print(f"{season}: {len(all_rows[season])} spread system picks")
    seasons = list(all_rows) + ["both"]
    all_rows["both"] = [r for s in BO.SEASONS for r in all_rows[s]]

    def sides(rows):
        out = defaultdict(list)
        for r in rows:
            out[(r["game"], r["side"])].append(r)
        return out

    print("\n=== A. Every system pick, split by what the players model said (one row per pick)")
    for s in seasons:
        by = defaultdict(list)
        for r in all_rows[s]:
            by[pbucket(r["gap"])].append(r["res"])
        print(f"  {s}")
        for b in BUCKETS:
            print(f"    {b:14} {rec(by[b])}")

    print("\n=== B. One bet per side: how many different systems, and the players model")
    for s in seasons:
        print(f"  {s}")
        cells = defaultdict(list)
        for ps in sides(all_rows[s]).values():
            n = len({p["system"] for p in ps})
            k = "1 system" if n == 1 else "2 systems" if n == 2 else "3+ systems"
            cells[(k, pbucket(ps[0]["gap"]))].append(ps[0]["res"])
            cells[(k, "all")].append(ps[0]["res"])
        for k in ("1 system", "2 systems", "3+ systems"):
            print(f"    {k:11} all            {rec(cells[(k, 'all')])}")
            for b in BUCKETS:
                if cells[(k, b)]:
                    print(f"    {'':11} {b:14} {rec(cells[(k, b)])}")

    print("\n=== C. Same as B but only the original (OG) systems, early-season systems left out")
    for s in seasons:
        print(f"  {s}")
        cells = defaultdict(list)
        og = [r for r in all_rows[s] if group(r["system"]) != "EARLY"]
        for ps in sides(og).values():
            n = len({p["system"] for p in ps})
            k = "1 system" if n == 1 else "2+ systems"
            cells[(k, "all")].append(ps[0]["res"])
            g = ps[0]["gap"]
            cells[(k, "players agree or neutral (> -3)" if g is None or g > -3 else "players disagree 3+")].append(ps[0]["res"])
        for k in ("1 system", "2+ systems"):
            for b in ("all", "players agree or neutral (> -3)", "players disagree 3+"):
                print(f"    {k:11} {b:32} {rec(cells[(k, b)])}")

    print("\n=== D. Each system (both seasons): all / players agree (>0) / players disagree (<0) / disagree 3+")
    by = defaultdict(lambda: defaultdict(list))
    for r in all_rows["both"]:
        t = label(r["system"])
        by[t]["all"].append(r["res"])
        g = r["gap"]
        if g is not None:
            by[t]["agree" if g > 0 else "disagree"].append(r["res"])
            if g <= -3:
                by[t]["dis3"].append(r["res"])
    for t in sorted(by):
        d = by[t]
        print(f"    {t:6} [{group_of(t)}] all {rec(d['all']):28} | agree {rec(d['agree']):28} | "
              f"disagree {rec(d['disagree']):28} | disagree 3+ {rec(d['dis3'])}")


def group_of(tag):
    from .systems import SYSTEMS
    for sid in SYSTEMS:
        if label(sid) == tag:
            return group(sid)
    return "?"


if __name__ == "__main__":
    main()
