"""PROPS STACK (Caden 2026-11-11: "test everything ... with stacks"). Does the stack method work on player points?

2025-26, every player-game in our sample with PINNACLE's points line 10 minutes before tip (both saved files,
reports/engine.measure_props_lines*.json: no credits spent). Each player-game gets OVER flags and UNDER flags,
all from what was known before tip (engine.measure_prop_model.features: only earlier games, plus who sat):
  model      our props model is 2+ points off the line that way
  fresh      a rotation teammate (20+ mpg) is freshly out and he picks up 2+ of those minutes   (over only)
  split      in past games without that teammate he played 3+ more minutes                    (over only)
  returning  he's back from 3+ missed games as a 28+ mpg player                                (under only)
  luck       his shooting ran 2+ points per 30 minutes below (over) / above (under) what his shots were worth
  match      tonight's opponent allows 5%+ more (over) / less (under) than the league on HIS shot mix
  opp        the opponent allows 8%+ more (over) / less (under) points to his position
  trend      his last 5 games' minutes are 3+ above (over) / below (under) his last 10
  vs_avg     the line is 2+ below (over) / above (under) his season average
  team_tot   his team's implied total is 4+ above (over) / below (under) its average
  blowout    the spread is 10+ and he's a 28+ mpg starter (under only: he sits late)
Graded at Pinnacle's own price (vig included). The two halves of the season stand in for "both seasons".
Run: python -m engine.measure_props_stack
"""
from __future__ import annotations

import itertools
import json
from collections import defaultdict
from pathlib import Path

from .measure_prop_model import features
from .personnel import norm
from .prop_model import TUNED, project
from .props_stack import flags

REPORTS = Path(__file__).resolve().parent.parent / "reports"
FILES = ("engine.measure_props_lines.json", "engine.measure_props_lines_h2.json")
HALF = "2026-01-15"


def payout(price):
    return price / 100 if price > 0 else 100 / -price


def rec(bs):
    w = sum(b["res"] == "W" for b in bs); l = sum(b["res"] == "L" for b in bs)
    units = sum(payout(b["price"]) if b["res"] == "W" else -1 if b["res"] == "L" else 0 for b in bs if b["price"])
    return f"{w}-{l} ({w / (w + l):.1%}, {units / max(1, w + l):+.1%}/bet)" if w + l else "-"


def main():
    saved = {}
    for fn in FILES:
        p = REPORTS / fn
        if p.exists():
            saved.update(json.loads(p.read_text()))
    print(f"games with saved Pinnacle lines: {sum(1 for v in saved.values() if v)}", flush=True)
    bets = []
    for f in features("2025-26"):
        k = f"{f['date']}|{f['away']}|{f['home']}"
        m = (saved.get(k) or {}).get(norm(f["name"]))
        if not m or m.get("over") is None or m.get("under") is None:
            continue
        proj = project(f, TUNED)["pts"]
        o, u = (set(x) for x in flags(f, m["line"], proj))      # the live trackers' definitions (engine/props_stack.py)
        act = f["pts_act"]
        half = "H1" if f["date"] < HALF else "H2"
        for side, fl in (("over", o), ("under", u)):
            res = "P" if act == m["line"] else "W" if (act > m["line"]) == (side == "over") else "L"
            bets.append({"side": side, "flags": fl, "res": res, "price": m[side], "half": half})
    print(f"player-games with a line: {len(bets) // 2}")
    for side in ("over", "under"):
        bs = [b for b in bets if b["side"] == side]
        print(f"\n=== {side.upper()}: records by how many {side} flags (at Pinnacle's price; break-even ~52-53%)")
        for n in range(0, 6):
            xs = [b for b in bs if (len(b["flags"]) >= n if n == 5 else len(b["flags"]) == n)]
            print(f"  {n}{'+' if n == 5 else ' '} flags   H1 {rec([b for b in xs if b['half'] == 'H1']):>32}   "
                  f"H2 {rec([b for b in xs if b['half'] == 'H2']):>32}   all {rec(xs)}")
        names = sorted({x for b in bs for x in b["flags"]})
        print(f"  -- single {side} flags --")
        for fl in names:
            xs = [b for b in bs if fl in b["flags"]]
            print(f"  {fl:10}   H1 {rec([b for b in xs if b['half'] == 'H1']):>32}   H2 {rec([b for b in xs if b['half'] == 'H2']):>32}")
        print(f"  -- {side} pairs (60+ bets) that won BOTH halves at 55%+ --")
        tested = hits = 0
        for a, b2 in itertools.combinations(names, 2):
            xs = [b for b in bs if {a, b2} <= b["flags"]]
            if len(xs) < 60:
                continue
            tested += 1
            h1 = [b for b in xs if b["half"] == "H1"]; h2 = [b for b in xs if b["half"] == "H2"]
            ok = lambda ys: sum(y["res"] == "W" for y in ys) > sum(y["res"] == "L" for y in ys)
            w = sum(b["res"] == "W" for b in xs); l = sum(b["res"] == "L" for b in xs)
            if ok(h1) and ok(h2) and w / max(1, w + l) >= 0.55:
                hits += 1
                print(f"  {a} + {b2:10}   H1 {rec(h1):>32}   H2 {rec(h2):>32}   all {rec(xs)}")
        print(f"  ({tested} tested; {hits} won both halves at 55%+; by luck alone about {max(1, round(tested * 0.06))})")


if __name__ == "__main__":
    main()
