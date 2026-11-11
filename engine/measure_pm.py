"""PLUS-MINUS FOR DEFENSE (2026-11-11). Box scores barely see defense. Every ESPN box score carries each player's
plus-minus. This blends each player's on-court margin RELATIVE to what his team did in the same games (per 100
of his possessions) into his impact, shrunk for small samples: weight x poss / (poss + SHRINK).
Same rules as engine.measure_opp_adjust: chosen on 2024-25, tested untouched on 2025-26, adopted only if it beats
today's model on 3+, 4+, line movement, and doesn't make system bets or MONEYBALL worse.
Run: python -m engine.measure_pm
"""
from __future__ import annotations

from . import backtest_open as BO
from . import boxscore
from . import measure_stacks as MS
from .measure_opp_adjust import grade, model_rows

GRID = [(0.0, 1000.0), (0.25, 1000.0), (0.5, 1000.0), (1.0, 1000.0), (0.5, 3000.0), (1.0, 3000.0)]


def main():
    res = {}
    for w, sh in GRID:
        boxscore.PM_WEIGHT, boxscore.PM_SHRINK = w, sh
        for season in BO.SEASONS:
            res[((w, sh), season)] = grade(model_rows(season), MS.season_rows(season))
            print(f"done weight {w} shrink {sh} {season}", flush=True)
    boxscore.PM_WEIGHT, boxscore.PM_SHRINK = 0.0, 1000.0
    keys = ["3+", "4+", "3-4", "4-5", "5-6", "6+", "system bet (1 system + 3+)", "MONEYBALL (2+ systems + 3+)"]
    for season in BO.SEASONS:
        print(f"\n=== {season} (opening line, -110)")
        for v in GRID:
            g = res[(v, season)]
            c = g["clv"]
            print(f"  weight {v[0]:<4} shrink {v[1]:<6.0f} line moved toward us {c[0]:+.2f} pts ({c[1]} toward / {c[2]} against)")
            for k in keys:
                if k in g:
                    print(f"      {k:30} {g[k][1]}")
    pick = max(GRID, key=lambda v: res[(v, "2024-25")]["3+"][0][2])
    base = GRID[0]
    print(f"\nCHOSEN on 2024-25 (best units, players model 3+): weight {pick[0]} shrink {pick[1]:.0f}")
    a, z = res[(pick, "2025-26")], res[(base, "2025-26")]
    checks = {
        "3+ record (units)": a["3+"][0][2] > z["3+"][0][2],
        "4+ record (units)": a["4+"][0][2] > z["4+"][0][2],
        "line movement toward us": a["clv"][0] > z["clv"][0],
        "system bets not worse": a["system bet (1 system + 3+)"][0][2] >= z["system bet (1 system + 3+)"][0][2],
        "MONEYBALL not worse": a["MONEYBALL (2+ systems + 3+)"][0][2] >= z["MONEYBALL (2+ systems + 3+)"][0][2],
    }
    print("TESTED untouched on 2025-26 vs today's model:")
    for k, v in checks.items():
        print(f"  {k:28} {'PASS' if v else 'FAIL'}")
    print("VERDICT:", "ADOPT" if pick != base and all(checks.values()) else "KEEP TODAY'S MODEL")


if __name__ == "__main__":
    main()
