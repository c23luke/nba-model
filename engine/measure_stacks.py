"""History for every stack the board tracks: the same tables as engine.run.tracking, replayed on
2024-25 and 2025-26 at the OPENING line, so each live record sits next to its two-season record.

Keys match tracking(): by_count, by_groups, by_combo, by_pair, stack_vs_personnel,
system_vs_personnel, each_system_vs_personnel, personnel_by_gap. The players model is the live version
(this season's results + opponents' 3-pt luck removed), calibrated to each day's openers.
The JSON at the end of the report is saved as data_static/stack_history.json.

Run: python -m engine.measure_stacks
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import backtest_open as BO
from . import personnel as P
from .measure_moneyball import corrected, fetch, luck_table
from .measure_personnel_upgrades import LIVE
from .run import _bucket, _wl, stack_key_count, track_agree
from .state import team_state
from .systems import evaluate, evaluate_early, evaluate_tests, group, label


def season_rows(season):
    games, days = fetch(season)
    lines, _ = BO.fetch_lines(season, days, "")
    totals = json.loads((P.STATIC / f"odds_totals_{season.replace('-', '_')}.json").read_text())
    preds, _ = BO.replay(season, [(g, r) for g, r, _ in games], lines)
    rows = corrected(preds[LIVE], luck_table(games), K=5, opp3=True)
    cal = {(r["date"], r["away"], r["home"]): r["gap"] for r in BO.calibrate_open(rows)}
    start = BO.SEASONS[season]["start"]
    gl = sorted([g for g, _, _ in games], key=lambda g: (g.game_date, str(g.id)))
    by_day = defaultdict(list)
    for g in gl:
        by_day[g.game_date].append(g)
    finals, out = [], []
    for day in sorted(by_day):
        for g in by_day[day]:
            k = f"{day.isoformat()}|{g.away}|{g.home}"
            op = (lines.get(k) or {}).get("open")
            ot = (totals.get(k) or {}).get("open")
            if op is None and ot is None:
                continue
            hs, as_ = team_state(g.home, finals, day), team_state(g.away, finals, day)
            picks = (evaluate(g, hs, as_, op, ot) + evaluate_tests(g, hs, as_, op, ot)
                     + evaluate_early(g, hs, as_, op, ot, (day - start).days))
            gap = cal.get((day, g.away, g.home))
            if gap is not None and op is not None and abs(gap) >= 3:
                from .systems import Pick
                picks.append(Pick(113, g.id, "spread", g.home if gap > 0 else g.away,
                                  op if gap > 0 else -op))
            for p in picks:
                if p.line is None or p.system >= 300:
                    continue
                if p.bet == "spread":
                    m = g.home_score - g.away_score
                    r = (m + p.line) if p.side == g.home else (-m + p.line)
                    gos = None if gap is None else (gap if p.side == g.home else -gap)
                else:
                    t = g.home_score + g.away_score
                    r = (t - p.line) if p.side == "OVER" else (p.line - t)
                    gos = None
                res = "W" if r > 0 else "L" if r < 0 else "P"
                out.append({"game": g.id, "bet": p.bet, "side": p.side, "system": p.system, "res": res, "gap": gos})
            if gap is not None and op is not None:
                m = g.home_score - g.away_score
                side_home = gap > 0
                r = (m + op) if side_home else (-m - op)
                out.append({"game": g.id, "bet": "x1", "side": None, "system": 301,
                            "res": "W" if r > 0 else "L" if r < 0 else "P", "gap": abs(gap)})
        finals += by_day[day]
    return out


def tables(rows):
    real = [r for r in rows if r["system"] < 300]
    stacks = defaultdict(list)
    for r in real:
        stacks[(r["game"], r["bet"], r["side"])].append(r)
    by = defaultdict(lambda: defaultdict(list))
    for (gid, bet, side), ps in stacks.items():
        res = ps[0]["res"]
        tags = sorted({label(p["system"]) for p in ps})
        n = len(tags)
        by["by_count"][stack_key_count(n)].append(res)
        if bet == "spread" and ps[0]["gap"] is not None and not any(p["system"] == 113 for p in ps):
            by["stack_vs_personnel"][f"{stack_key_count(n)} + {track_agree(ps[0]['gap'])}"].append(res)
        if n < 2:
            continue
        by["by_combo"]["+".join(tags)].append(res)
        by["by_groups"]["+".join(sorted({group(p['system']) for p in ps}))].append(res)
        for i in range(n):
            for j in range(i + 1, n):
                by["by_pair"][f"{tags[i]}+{tags[j]}"].append(res)
    for r in real:
        if r["bet"] == "spread" and r["system"] != 113 and r["gap"] is not None:
            by["system_vs_personnel"][f"{group(r['system'])} + {track_agree(r['gap'])}"].append(r["res"])
            by["each_system_vs_personnel"][f"{label(r['system'])} + {track_agree(r['gap'])}"].append(r["res"])
    for r in rows:
        if r["system"] == 301:
            by["personnel_by_gap"][_bucket(r["gap"])].append(r["res"])
    return {k: {kk: _wl(v) for kk, v in sorted(d.items())} for k, d in by.items()}


def main():
    allrows = []
    for season in BO.SEASONS:
        rows = season_rows(season)
        allrows += rows
        print(f"{season}: {len(rows)} graded picks")
    t = tables(allrows)
    for k in ("by_count", "stack_vs_personnel", "system_vs_personnel", "each_system_vs_personnel",
              "personnel_by_gap", "by_groups", "by_pair", "by_combo"):
        print(f"\n=== {k} (2 seasons, vs the open)")
        for kk, v in sorted((t.get(k) or {}).items(), key=lambda kv: -kv[1]["n"]):
            print(f"    {kk:44} {v['w']}-{v['l']}-{v['p']}  ({(v['win_pct'] or 0):.1%})  {v['units']:+.1f}u")
    print("\nJSON")
    print(json.dumps(t))


if __name__ == "__main__":
    main()
