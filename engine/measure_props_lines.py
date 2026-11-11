"""THE REAL TEST (Caden 2026-11-11: "run it"): does our props model beat REAL closing lines?

2025-26: our model's walk-forward projections (engine.measure_prop_model.features: only games before that night,
plus who sat), against PINNACLE's points line 10 minutes before tip (inactives known by then), for a sample of
games spread across the season (env GAMES, default 600). Pinnacle only (region eu): 10 credits a game.
Graded at Pinnacle's own price for that side (vig included: break-even about 52-53%).
Compared with the same test using the player's last-10 average instead of our model.
The lines are saved to reports/engine.measure_props_lines.json so they never have to be bought again.
Run: python -m engine.measure_props_lines
"""
from __future__ import annotations

import json
import os
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import props_ev as E
from . import sources
from .measure_prop_model import features
from .personnel import norm
from .prop_model import TUNED, project
from .teams import code

KEY = os.environ.get("ODDS_API_KEY", "")
H = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba"
N = int(os.environ.get("GAMES", "600"))
SAVE = Path(__file__).resolve().parent.parent / "reports" / "engine.measure_props_lines.json"
spent = {"credits": 0, "left": None}


def get(url):
    meta = {}
    try:
        js = sources.get_json(url, meta=meta)
    except Exception:
        return None
    spent["credits"] += int(meta.get("x-requests-last") or 0)
    spent["left"] = meta.get("x-requests-remaining")
    return js


def c(x):
    try:
        return code(x)
    except Exception:
        return None


def rec(rs):
    w = sum(1 for r in rs if r["res"] == "W"); l = sum(1 for r in rs if r["res"] == "L")
    u = sum((E.dec(r["price"]) - 1) if r["res"] == "W" else -1 for r in rs if r["res"] in ("W", "L"))
    return f"{w}-{l}" + (f"  {w / (w + l):5.1%}  {u:+7.1f}u  ({u / (w + l):+5.1%} a bet)" if w + l else "")


def main(start: str = "0000", label: str = ""):
    rows = [f for f in features("2025-26") if f["date"] >= start]
    by_game = defaultdict(list)
    for f in rows:
        by_game[(f["date"], f["home"], f["away"])].append(f)
    keys = sorted(by_game)
    step_ = max(1, len(keys) // N)
    sample = keys[::step_][:N]
    saved = json.loads(SAVE.read_text()) if SAVE.exists() else {}
    print(f"games with projections: {len(keys)}; sample {len(sample)} from {sample[0][0]} to {sample[-1][0]}", flush=True)
    day_events = {}
    bets = []
    for d, home, away in sample:
        k = f"{d}|{away}|{home}"
        if k not in saved:
            if d not in day_events:
                js = get(f"{H}/events?apiKey={urllib.parse.quote(KEY)}&date={d}T16:00:00Z")
                day_events[d] = (js or {}).get("data") or []
            ev = next((e for e in day_events[d] if {c(e.get("home_team", "")), c(e.get("away_team", ""))} == {home, away}), None)
            lines = {}
            if ev:
                tip = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")) - timedelta(minutes=10)
                js = get(f"{H}/events/{ev['id']}/odds?apiKey={urllib.parse.quote(KEY)}&date={tip.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                         "&regions=eu&markets=player_points&bookmakers=pinnacle&oddsFormat=american")
                px = E.prices((js or {}).get("data") or {}).get("pinnacle") or {}
                lines = {p: {"line": ln, "over": q.get("Over"), "under": q.get("Under")}
                         for (p, s, ln), q in px.items() if s == "pts" and "Over" in q and "Under" in q}
            saved[k] = lines
        lines = saved[k]
        for f in by_game[(d, home, away)]:
            m = lines.get(norm(f["name"]))
            if not m:
                continue
            proj = project(f, TUNED)["pts"]
            act = f["pts_act"]
            for who, val in (("model", proj), ("last-10", f["pts_l10avg"])):
                diff = val - m["line"]
                side = "over" if diff > 0 else "under"
                price = m["over"] if side == "over" else m["under"]
                res = "P" if act == m["line"] else "W" if (act > m["line"]) == (side == "over") else "L"
                bets.append({"who": who, "diff": abs(diff), "side": side, "price": price, "res": res,
                             "fresh": f["fresh_out"] > 0, "ret": bool(f["returning"]), "bench": f["m10"] < 20,
                             "agree_l10": None})
    SAVE.write_text(json.dumps(saved))
    print(f"credits spent: {spent['credits']} | left: {spent['left']} | games with Pinnacle lines: "
          f"{sum(1 for v in saved.values() if v)}", flush=True)
    for who in ("model", "last-10"):
        bs = [b for b in bets if b["who"] == who]
        print(f"\n=== {who} vs Pinnacle's closing points line ({len(bs)} player-games with a line)")
        for lo, hi in ((0, 1.5), (1.5, 3), (3, 5), (5, 99)):
            xs = [b for b in bs if lo <= b["diff"] < hi]
            print(f"  {lo:>3}-{hi if hi < 99 else '+':<4} points off the line: {rec(xs)}")
            for side in ("over", "under"):
                ys = [b for b in xs if b["side"] == side]
                if ys and lo >= 1.5:
                    print(f"        {side:6} {rec(ys)}")
        big = [b for b in bs if b["diff"] >= 3]
        for nm, fn in (("teammate freshly out", lambda b: b["fresh"]), ("returning star", lambda b: b["ret"]),
                       ("bench (under 20 mpg)", lambda b: b["bench"])):
            print(f"  3+ off, {nm:22} {rec([b for b in big if fn(b)])}")


if __name__ == "__main__":
    main()
