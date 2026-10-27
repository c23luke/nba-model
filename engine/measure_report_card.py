"""Report card for every system, season by season, for the bet tickets on the site.

Caden (2026-10-27): "easily understand why ur putting money on it — the systems it includes, each
system's grading from last year / the last couple years and this year."

Replays 2024-25 and 2025-26 at the OPENING line (same replay as engine.measure_stacks) and grades:
  systems      every system by its tag (S3, T7, E4 ...), per season
  players_gap  the players model on the side it likes, by gap bucket (3-4, 4-6, 6+, and 4+), per season
  moneyball    2+ different systems on the same spread side + players model 3+ on that side, per season
  early_combo  an early-season system + players model 3+ on that side, per season
The JSON at the end is saved as data_static/report_card.json.

Run: python -m engine.measure_report_card
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import backtest_open as BO
from .measure_stacks import season_rows
from .systems import group, label


def _wl(rs):
    w, l, p = (sum(r == x for r in rs) for x in "WLP")
    return {"w": w, "l": l, "p": p}


def gap_buckets(gap):
    out = []
    if 3 <= gap < 4:
        out.append("3-4")
    if 4 <= gap < 6:
        out.append("4-6")
    if gap >= 6:
        out.append("6+")
    if gap >= 4:
        out.append("4+")
    return out


def main():
    res = {"systems": defaultdict(dict), "players_gap": defaultdict(dict), "moneyball": {}, "early_combo": {}}
    for season in BO.SEASONS:
        rows = season_rows(season)
        per_sys, per_gap, mb, ec = defaultdict(list), defaultdict(list), [], []
        stacks = defaultdict(list)
        for r in rows:
            if r["system"] == 301:
                for b in gap_buckets(r["gap"]):
                    per_gap[b].append(r["res"])
                continue
            if r["system"] == 113:
                continue
            per_sys[label(r["system"])].append(r["res"])
            if r["bet"] == "spread" and r["gap"] is not None:
                stacks[(r["game"], r["side"])].append(r)
        for ps in stacks.values():
            gap, outcome = ps[0]["gap"], ps[0]["res"]
            if gap < 3:
                continue
            if len({p["system"] for p in ps}) >= 2:
                mb.append(outcome)
            if any(group(p["system"]) == "EARLY" for p in ps):
                ec.append(outcome)
        for k, v in per_sys.items():
            res["systems"][k][season] = _wl(v)
        for k, v in per_gap.items():
            res["players_gap"][k][season] = _wl(v)
        res["moneyball"][season] = _wl(mb)
        res["early_combo"][season] = _wl(ec)
        print(f"{season}: {len(rows)} graded picks")

    def line(d):
        return " | ".join(f"{s}: {v['w']}-{v['l']}" + (f"-{v['p']}" if v['p'] else "")
                          + f" ({v['w'] / max(v['w'] + v['l'], 1):.1%})" for s, v in d.items())
    print("\n=== systems")
    for k in sorted(res["systems"]):
        print(f"    {k:6} {line(res['systems'][k])}")
    print("\n=== players model by gap (side it likes, vs the open)")
    for k in ("3-4", "4-6", "6+", "4+"):
        print(f"    {k:6} {line(res['players_gap'].get(k, {}))}")
    print(f"\n=== MONEYBALL (2+ systems + players 3+)  {line(res['moneyball'])}")
    print(f"=== early system + players 3+           {line(res['early_combo'])}")
    out = {"note": "Replayed at the opening line, each season separately (engine/measure_report_card.py)",
           **{k: dict(v) if isinstance(v, defaultdict) else v for k, v in res.items()}}
    print("\nJSON")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
