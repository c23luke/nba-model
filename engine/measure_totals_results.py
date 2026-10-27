"""Totals: does the player-based totals model get an edge once it learns from THIS season's scoring?

The player-based totals model (engine/backtest_totals.py) has no edge on its own (~50% vs the opener):
box-score offense/defense and on-court pace miss scheme, defense and shooting luck. The same fix that
took the sides model from 50.7% to 54.6% is tested here for totals, separately for each team's
offense and defense:
  home points expected = possessions/100 × (league level + home offense − away defense), same for away
  after each game: offense miss = points scored − expected; defense miss = points allowed − expected
  correction = sum of misses / (games + K), separately for offense and defense
  new total = model total + home off corr + away def corr + away off corr + home def corr
K chosen on 2024-25 (5, 10, 20, 40), then tested untouched on 2025-26. Graded at the opening total:
calibrated to each day's openers, over/under the model likes, gap 3+ / 5+, CLV, info per point.

Run: python -m engine.measure_totals_results
"""
from __future__ import annotations

import os
from collections import defaultdict

from . import backtest as BT
from . import backtest_open as BO
from . import backtest_totals as BTT
from . import boxscore

KS = (5, 10, 20, 40)


def replay(season, games, lines, pace_boxes):
    """backtest_totals.replay, keeping each side's expected points so offense/defense misses can be tracked."""
    prior, base = BTT.priors(season)
    pace_prior, lg_pace, lg_level0 = BTT.pace_and_level(pace_boxes)
    start = BTT.SEASONS[season]["start"]
    data = sorted([(g, r) for g, r in games if r], key=lambda d: (d[0].game_date, d[0].id))
    by_date = defaultdict(list)
    for d in data:
        by_date[d[0].game_date].append(d)
    hist, out = [], []
    live_pace = defaultdict(lambda: [0.0, 0.0])
    pts = poss = 0.0
    ng = 0
    for day in sorted(by_date):
        live = boxscore.season_impact(hist) if hist else {}
        level = (lg_level0 * BTT.LG_PRIOR_GAMES + (pts / poss * 100 if poss else lg_level0) * ng) / (BTT.LG_PRIOR_GAMES + ng)
        for g, rows in by_date[day]:
            ln = lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
            ppl = defaultdict(list)
            for r in rows:
                if r.get("min"):
                    ppl[r["team"]].append((r["espn_id"], r["name"]))
            Oh, Dh, Ph = BTT.team_line(ppl[g.home], prior, base, pace_prior, lg_pace, live, live_pace)
            Oa, Da, Pa = BTT.team_line(ppl[g.away], prior, base, pace_prior, lg_pace, live, live_pace)
            possn = (Ph + Pa) / 2
            eh = possn / 100 * (level + Oh - Da)
            ea = possn / 100 * (level + Oa - Dh)
            out.append({"day": (day - start).days, "date": day, "home": g.home, "away": g.away,
                        "pred": eh + ea, "eh": eh, "ea": ea, "open": ln.get("open"), "close": ln.get("close"),
                        "actual": g.home_score + g.away_score, "hs": g.home_score, "as": g.away_score})
        for g, rows in by_date[day]:
            hist += rows
            ng += 1
            teams = defaultdict(list)
            for r in rows:
                teams[r["team"]].append(r)
            for t, rs in teams.items():
                tp, gm = rs[0]["team_poss"], rs[0]["game_min"] or 48
                pts += sum(r["pts"] for r in rs)
                poss += tp
                for r in rs:
                    live_pace[r["espn_id"]][0] += tp * 48 / gm * r["min"]
                    live_pace[r["espn_id"]][1] += r["min"]
    return out


def corrected(rows, K):
    off, dfn = defaultdict(list), defaultdict(list)
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["date"]].append(r)
    out = []
    c = lambda v: sum(v) / (len(v) + K)
    for day in sorted(by_day):
        for r in by_day[day]:
            adj = c(off[r["home"]]) + c(dfn[r["away"]]) + c(off[r["away"]]) + c(dfn[r["home"]])
            out.append({**r, "pred": r["pred"] + adj})
        for r in by_day[day]:
            mh, ma = r["hs"] - r["eh"], r["as"] - r["ea"]
            off[r["home"]].append(mh); dfn[r["away"]].append(mh)
            off[r["away"]].append(ma); dfn[r["home"]].append(ma)
    return out


def score(rows, label):
    cal = BTT.calibrate(rows)
    xs = [r["gap"] for r in cal]
    _, bi, ti = BT.ols(xs, [r["actual"] - r["open"] for r in cal])
    _, bm, tm = BT.ols(xs, [r["close"] - r["open"] for r in cal])
    g3, g5 = BTT.grade(cal, 3), BTT.grade(cal, 5)
    f30 = BTT.grade([r for r in cal if r["day"] <= 30], 3)
    print(f"  {label:30} 3+: {BO.fmt(g3)}")
    print(f"  {'':30} 5+: {BO.fmt(g5)}")
    print(f"  {'':30} first 30 days 3+: {BO.fmt(f30)}")
    print(f"  {'':30} result beats open by {bi:+.3f}/pt of gap (t {ti:.1f}); market moves toward us {bm:+.3f}/pt (t {tm:.1f}); {len(cal)} games")
    return {"g3": g3, "g5": g5, "info": bi, "t": ti}


def main():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    data = {}
    for season, cfg in BTT.SEASONS.items():
        games, days = BTT.season_boxes(cfg["start"], cfg["end"])
        pace_boxes, _ = BTT.season_boxes(*cfg["pace_season"])
        lines, how = BTT.fetch_totals(season, days, key)
        data[season] = replay(season, games, lines, pace_boxes)
        print(f"{season}: {len(data[season])} games, totals lines {how}")
    res = {}
    for season, rows in data.items():
        print(f"\n=== {season}")
        res[(season, None)] = score(rows, "players only (as tested before)")
        for K in KS:
            res[(season, K)] = score(corrected(rows, K), f"+ this season's scoring K={K}")
    best = max(KS, key=lambda k: res[("2024-25", k)]["info"])
    print(f"\n=== CHOSEN ON 2024-25: K={best}")
    for k in (None, best):
        r = res[("2025-26", k)]
        print(f"    2025-26 {'players only' if k is None else f'K={k}':14} 3+ {BO.fmt(r['g3'])} | 5+ {BO.fmt(r['g5'])} | "
              f"info {r['info']:+.3f}/pt (t {r['t']:.1f})")
    print("\n=== BOTH SEASONS, 3+ / 5+ vs the opener")
    for k in (None,) + KS:
        w3 = sum(res[(s, k)]["g3"]["w"] for s in data); l3 = sum(res[(s, k)]["g3"]["l"] for s in data)
        w5 = sum(res[(s, k)]["g5"]["w"] for s in data); l5 = sum(res[(s, k)]["g5"]["l"] for s in data)
        print(f"    {'players only' if k is None else f'K={k}':14} 3+: {w3}-{l3} ({w3 / max(w3 + l3, 1):.1%}) | "
              f"5+: {w5}-{l5} ({w5 / max(w5 + l5, 1):.1%})")


if __name__ == "__main__":
    main()
