"""MONEYBALL (Caden's stack): two or more of our systems on the same side of a spread AND the players
model agreeing with that side by 4-6 points. Replayed on 2024-25 and 2025-26 at the opening line,
each season separately, next to the nearby versions so we can see it isn't a lucky slice.

Players model = live version (this season's results + opponents' 3-pt luck removed), calibrated to the
day's openers. "Systems" = every OG / FAV / EARLY / TEST spread system except T13 itself.

Run: python -m engine.measure_moneyball_stack
"""
from __future__ import annotations

from collections import defaultdict

from . import backtest_open as BO
from .measure_stacks import season_rows

VERSIONS = {
    "MONEYBALL: 2+ systems + players agree 4-6": (2, 4, 6),
    "2+ systems + players agree 4+": (2, 4, 99),
    "2+ systems + players agree 3+": (2, 3, 99),
    "2+ systems + players agree 3-4": (2, 3, 4),
    "1 system + players agree 4-6": (1, 4, 6),
    "players model alone, gap 4-6": (0, 4, 6),
    "players model alone, gap 3-4": (0, 3, 4),
}


def fmt(w, l):
    return f"{w}-{l} ({w / max(w + l, 1):.1%}, {w - 1.1 * l:+.1f}u)"


def main():
    out = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    examples = []
    for season in BO.SEASONS:
        rows = season_rows(season)
        stacks = defaultdict(list)
        x1 = {}
        for r in rows:
            if r["system"] == 301:
                x1[r["game"]] = r
            elif r["bet"] == "spread" and r["system"] != 113 and r["gap"] is not None:
                stacks[(r["game"], r["side"])].append(r)
        # players-model-only rows: X1 graded on the side it likes
        for g, r in x1.items():
            for name, (n, lo, hi) in VERSIONS.items():
                if n == 0 and lo <= r["gap"] < hi and r["res"] != "P":
                    out[name][season][0 if r["res"] == "W" else 1] += 1
        for (g, side), ps in stacks.items():
            k = len({p["system"] for p in ps})
            gap = ps[0]["gap"]
            res = ps[0]["res"]
            if res == "P":
                continue
            for name, (n, lo, hi) in VERSIONS.items():
                if n and (k >= n if n == 2 else k == n) and lo <= gap < hi:
                    out[name][season][0 if res == "W" else 1] += 1
                    if name.startswith("MONEYBALL"):
                        examples.append(f"{season} {side} gap {gap:+.1f} systems {sorted({p['system'] for p in ps})} → {res}")
    for name in VERSIONS:
        per = " | ".join(f"{s}: {fmt(*out[name][s])}" for s in BO.SEASONS)
        w = sum(out[name][s][0] for s in BO.SEASONS); l = sum(out[name][s][1] for s in BO.SEASONS)
        print(f"{name:46} BOTH {fmt(w, l)}   [{per}]")
    print("\nEvery MONEYBALL bet:")
    for e in examples:
        print("   ", e)


if __name__ == "__main__":
    main()
