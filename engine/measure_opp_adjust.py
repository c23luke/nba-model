"""OPPONENT-ADJUSTED PLAYER RATINGS (Caden 2026-11-11: "yes go on that, keep what we have rn tho if that doesnt work").

Today a player's box impact treats 30 points against the best team the same as 30 against the worst. This test
moves each player's impact by BETA x the average strength (net points per 100 possessions, from games BEFORE the
one being priced) of the opponents he actually faced, weighted by his possessions in each game.

Everything else is the live players model (this season's results correction K=5, opponents' 3-pt luck removed,
calibrated to each day's opening lines), replayed on 2024-25 and 2025-26.
BETA is CHOSEN on 2024-25 (best units on gap 3+ at the open) and then TESTED untouched on 2025-26.
Rule written before the run: it replaces the live model only if, on 2025-26, it beats BETA=0 on the players model's
3+ AND 4+ records at the open AND its line movement toward us, and doesn't make system bets or MONEYBALL worse.
Run: python -m engine.measure_opp_adjust
"""
from __future__ import annotations

import functools
from collections import defaultdict

from . import backtest_open as BO
from . import boxscore
from . import measure_stacks as MS
from .measure_moneyball import corrected, luck_table
from .measure_personnel_upgrades import LIVE

BETAS = (0.0, 0.25, 0.5, 0.75, 1.0)
MS.fetch = functools.lru_cache(maxsize=None)(MS.fetch)          # fetch each season's games once


def model_rows(season):
    games, days = MS.fetch(season)
    lines, _ = BO.fetch_lines(season, days, "")
    preds, _ = BO.replay(season, [(g, r) for g, r, _ in games], lines)
    return BO.calibrate_open(corrected(preds[LIVE], luck_table(games), K=5, opp3=True))


def rec(rs):
    w, l = sum(r == "W" for r in rs), sum(r == "L" for r in rs)
    n = w + l
    return (w, l, w * 100 / 110 - l), (f"{w}-{l} {w / n:5.1%} {w * 100 / 110 - l:+6.1f}u" if n else "-")


def grade(cal, rows):
    out = {}
    x1 = defaultdict(list)
    toward = against = 0
    clv = []
    for r in cal:
        g = r["gap"]
        if abs(g) < 3 or r["actual"] is None:
            continue
        home = g > 0
        res = r["actual"] + r["open"]
        res = res if home else -res
        x = "W" if res > 0 else "L" if res < 0 else "P"
        a = abs(g)
        x1["3+"].append(x)
        if a >= 4:
            x1["4+"].append(x)
        x1["3-4" if a < 4 else "4-5" if a < 5 else "5-6" if a < 6 else "6+"].append(x)
        mv = (r["open"] - r["close"]) if home else (r["close"] - r["open"])
        clv.append(mv)
        toward += mv > 0
        against += mv < 0
    for k, v in x1.items():
        out[k] = rec(v)
    out["clv"] = (sum(clv) / len(clv) if clv else 0.0, toward, against)
    sides = defaultdict(list)
    for r in rows:
        if r["bet"] == "spread" and r["system"] < 300 and r["system"] != 113 and r["gap"] is not None:
            sides[(r["game"], r["side"])].append(r)
    one, two = [], []
    for ps in sides.values():
        if ps[0]["gap"] >= 3 and ps[0]["res"] != "P":
            (two if len({p["system"] for p in ps}) >= 2 else one).append(ps[0]["res"])
    out["system bet (1 system + 3+)"] = rec(one)
    out["MONEYBALL (2+ systems + 3+)"] = rec(two)
    return out


def main():
    res = {}
    for beta in BETAS:
        boxscore.OPP_BETA = beta
        for season in BO.SEASONS:
            res[(beta, season)] = grade(model_rows(season), MS.season_rows(season))
            print(f"done beta {beta} {season}", flush=True)
    boxscore.OPP_BETA = 0.0
    keys = ["3+", "4+", "3-4", "4-5", "5-6", "6+", "system bet (1 system + 3+)", "MONEYBALL (2+ systems + 3+)"]
    for season in BO.SEASONS:
        print(f"\n=== {season} (opening line, -110)")
        for beta in BETAS:
            g = res[(beta, season)]
            c = g["clv"]
            print(f"  BETA {beta:<4}  line moved toward us {c[0]:+.2f} pts ({c[1]} toward / {c[2]} against)")
            for k in keys:
                if k in g:
                    print(f"      {k:30} {g[k][1]}")
    pick = max(BETAS, key=lambda b: res[(b, "2024-25")]["3+"][0][2])
    print(f"\nCHOSEN on 2024-25 (best units, players model 3+): BETA {pick}")
    a, z = res[(pick, "2025-26")], res[(0.0, "2025-26")]
    checks = {
        "3+ record (units)": a["3+"][0][2] > z["3+"][0][2],
        "4+ record (units)": a["4+"][0][2] > z["4+"][0][2],
        "line movement toward us": a["clv"][0] > z["clv"][0],
        "system bets not worse": a["system bet (1 system + 3+)"][0][2] >= z["system bet (1 system + 3+)"][0][2],
        "MONEYBALL not worse": a["MONEYBALL (2+ systems + 3+)"][0][2] >= z["MONEYBALL (2+ systems + 3+)"][0][2],
    }
    print("TESTED untouched on 2025-26 vs today's model (BETA 0):")
    for k, v in checks.items():
        print(f"  {k:28} {'PASS' if v else 'FAIL'}")
    print("VERDICT:", "ADOPT" if pick != 0.0 and all(checks.values()) else "KEEP TODAY'S MODEL")


if __name__ == "__main__":
    main()
