"""Can the 'this season's results' correction be made sharper? (follow-up to measure_personnel_upgrades)

Live now: correction = sum of misses / (games + 5), every game weighted the same.
Variants tested here, each CHOSEN on 2024-25 and TESTED untouched on 2025-26:
  K 3 / 5 / 7                    how fast results take over
  recent games count double      a team's last 10 games weighted 2x (rotations, health and form change)
  older games fade               each game's weight halves every 15 / 30 games back
Graded like the bet: calibrated to each day's openers, gap 3+, vs the opener, CLV, information per point.

Run: python -m engine.measure_results_variants
"""
from __future__ import annotations

import os
from collections import defaultdict

from . import backtest_open as BO
from .measure_personnel_upgrades import LIVE, market_rank, score, pct


def corrected(rows, K=5, recent_n=0, recent_w=1.0, half_life=None):
    res = defaultdict(list)
    out = []
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["date"]].append(r)

    def corr(team):
        v = res[team]
        n = len(v)
        if not n:
            return 0.0
        ws = []
        for i in range(n):
            back = n - 1 - i                       # 0 = most recent
            w = 1.0
            if recent_n and back < recent_n:
                w *= recent_w
            if half_life:
                w *= 0.5 ** (back / half_life)
            ws.append(w)
        # weighted mean shrunk like sum/(n+K): scale weights so they sum to n, then divide by n + K
        sw = sum(ws)
        return sum(w * e for w, e in zip(ws, v)) * (n / sw) / (n + K)

    for day in sorted(by_day):
        for r in by_day[day]:
            out.append({**r, "pred": r["pred"] + corr(r["home"]) - corr(r["away"])})
        for r in by_day[day]:
            e = r["actual"] - r["pred"]
            res[r["home"]].append(e)
            res[r["away"]].append(-e)
    return out


VARIANTS = {
    "none (players only)": None,
    "LIVE: K=5": dict(K=5),
    "K=3": dict(K=3),
    "K=7": dict(K=7),
    "K=5, last 10 games x2": dict(K=5, recent_n=10, recent_w=2.0),
    "K=5, fade half-life 30 g": dict(K=5, half_life=30),
    "K=5, fade half-life 15 g": dict(K=5, half_life=15),
}


def main():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    data = {}
    for season in BO.SEASONS:
        games, days = BO.fetch_games(season)
        lines, how = BO.fetch_lines(season, days, key)
        preds, _ = BO.replay(season, games, lines)
        data[season] = preds[LIVE]
        print(f"{season}: {len(preds[LIVE])} games replayed, lines {how}")
    res = {}
    for season, rows in data.items():
        ranks = market_rank(rows)
        print(f"\n=== {season}")
        for name, kw in VARIANTS.items():
            rs = rows if kw is None else corrected(rows, **kw)
            res[(season, name)] = score(rs, ranks, name)
    train, test = "2024-25", "2025-26"
    cands = [n for n in VARIANTS if VARIANTS[n] is not None]
    best = max(cands, key=lambda n: (round(res[(train, n)]["info"], 3), pct(res[(train, n)]["g3"])))
    print(f"\n=== CHOSEN ON {train}: {best} (info {res[(train, best)]['info']:+.3f}/pt; live K=5 "
          f"{res[(train, 'LIVE: K=5')]['info']:+.3f})")
    for n in ("none (players only)", "LIVE: K=5", best):
        r = res[(test, n)]
        print(f"    {test} {n:28} 3+ {BO.fmt(r['g3'])}; info {r['info']:+.3f}/pt (t {r['t']:.1f})")
    print("\n=== BOTH SEASONS, every variant (3+ vs open)")
    for n in VARIANTS:
        w = sum(res[(s, n)]["g3"]["w"] for s in data); l = sum(res[(s, n)]["g3"]["l"] for s in data)
        print(f"    {n:28} {w}-{l} ({w / max(w + l, 1):.1%})")


if __name__ == "__main__":
    main()
