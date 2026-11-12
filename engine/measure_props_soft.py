"""BEAT THE SOFT BOOKS, NOT PINNACLE (Caden 2026-11-11: "we don't have to beat pinnacle, we have to beat the ...
opening lines or middle lines, the less efficient stuff, or bet right before with special news").

We bet ProphetX / Novig / Kalshi, often hours early. Their past prop lines aren't kept, so the stand-ins are the
softer US books (BetRivers, Bovada, BetMGM, DraftKings, FanDuel, Caesars, BetOnline, Fanatics). 2025-26, a sample
spread across the whole season (env GAMES, default 600), points only, two snapshots per game (us + eu regions,
20 credits each): EARLY = 6 hours before tip, CLOSE = 10 minutes before tip.
  1. Our model vs each soft book's EARLY line. Fair test: the early model only knows players who had already missed
     the previous game (not that afternoon's news).
  2. Our model (knowing who sits) vs each soft book's CLOSING line.
  3. Stale lines after news, no model: at the close, a soft book's line 1.5+ points away from Pinnacle's -> bet
     the soft book toward Pinnacle's number at the soft book's price.
  Every bet is graded at that book's own price. Results split into two halves of the season (Oct-Jan / Jan-Apr):
  only what wins in BOTH counts.
Lines saved to reports/engine.measure_props_soft.json.
Run: python -m engine.measure_props_soft
"""
from __future__ import annotations

import json
import os
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import measure_prop_model as MPM
from . import props_ev as E
from . import sources
from .personnel import norm
from .prop_model import TUNED, project
from .teams import code

KEY = os.environ.get("ODDS_API_KEY", "")
H = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba"
SOFT = ("betrivers", "bovada", "betmgm", "draftkings", "fanduel", "williamhill_us", "betonlineag", "fanatics")
N = int(os.environ.get("GAMES", "600"))
SAVE = Path(__file__).resolve().parent.parent / "reports" / "engine.measure_props_soft.json"
SPLIT = "2026-01-24"
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


def snap(eid, when):
    js = get(f"{H}/events/{eid}/odds?apiKey={urllib.parse.quote(KEY)}&date={when.strftime('%Y-%m-%dT%H:%M:%SZ')}"
             "&regions=us,eu&markets=player_points&oddsFormat=american")
    px = E.prices((js or {}).get("data") or {})
    return {bk: {p: [ln, q.get("Over"), q.get("Under")] for (p, s, ln), q in d.items() if s == "pts"}
            for bk, d in px.items()}


def rec(rs):
    w = sum(1 for r in rs if r["res"] == "W"); l = sum(1 for r in rs if r["res"] == "L")
    u = sum((E.dec(r["price"]) - 1) if r["res"] == "W" else -1 for r in rs if r["res"] in ("W", "L"))
    return f"{w}-{l}" + (f" {w / (w + l):5.1%} {u:+7.1f}u ({u / (w + l):+5.1%})" if w + l else "")


def grade(act, line, side):
    return "P" if act == line else "W" if (act > line) == (side == "over") else "L"


def main():
    MPM.EARLY = True
    rows = MPM.features("2025-26")
    by_game = defaultdict(list)
    for f in rows:
        by_game[(f["date"], f["home"], f["away"])].append(f)
    keys = sorted(by_game)
    sample = [keys[int(i * len(keys) / N)] for i in range(min(N, len(keys)))]      # evenly across the season
    saved = json.loads(SAVE.read_text()) if SAVE.exists() else {}
    print(f"sample {len(sample)} games, {sample[0][0]} to {sample[-1][0]}", flush=True)
    day_events, bets = {}, []
    for d, home, away in sample:
        k = f"{d}|{away}|{home}"
        if k not in saved and not KEY:
            continue
        if k not in saved:
            if d not in day_events:
                js = get(f"{H}/events?apiKey={urllib.parse.quote(KEY)}&date={d}T16:00:00Z")
                day_events[d] = (js or {}).get("data") or []
            ev = next((e for e in day_events[d] if {c(e.get("home_team", "")), c(e.get("away_team", ""))} == {home, away}), None)
            if not ev:
                saved[k] = {}
                continue
            tip = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            saved[k] = {"early": snap(ev["id"], tip - timedelta(hours=6)), "close": snap(ev["id"], tip - timedelta(minutes=10))}
        S = saved[k]
        if not S:
            continue
        half = "Oct-Jan" if d < SPLIT else "Jan-Apr"
        for f in by_game[(d, home, away)]:
            nm = norm(f["name"])
            act = f["pts_act"]
            close_proj = project(f, TUNED)["pts"]
            early_proj = (f.get("early_proj") or {}).get("pts")
            pin = (S["close"].get("pinnacle") or {}).get(nm)
            for when, proj in (("early", early_proj), ("close", close_proj)):
                for bk in SOFT:
                    q = (S[when].get(bk) or {}).get(nm)
                    if not q or proj is None or q[1] is None or q[2] is None:
                        continue
                    diff = proj - q[0]
                    if abs(diff) < 3:
                        continue
                    side = "over" if diff > 0 else "under"
                    bets.append({"test": f"model vs {when} line", "book": bk, "half": half, "side": side,
                                 "price": q[1] if side == "over" else q[2], "res": grade(act, q[0], side),
                                 "big": abs(diff) >= 5, "fresh": f["fresh_out"] > 0, "bench": f["m10"] < 20})
            if pin:
                for bk in SOFT:
                    q = (S["close"].get(bk) or {}).get(nm)
                    if not q or q[1] is None or q[2] is None:
                        continue
                    gap = pin[0] - q[0]
                    if abs(gap) < 1.5:
                        continue
                    side = "over" if gap > 0 else "under"          # Pinnacle's line is higher -> the soft over
                    agrees = (close_proj - q[0]) * gap > 0
                    bets.append({"test": "stale soft line (1.5+ off Pinnacle at the close)", "book": bk, "half": half,
                                 "side": side, "price": q[1] if side == "over" else q[2], "res": grade(act, q[0], side),
                                 "big": abs(gap) >= 2.5, "fresh": f["fresh_out"] > 0, "bench": f["m10"] < 20,
                                 "model_agrees": agrees})
    if KEY:
        SAVE.write_text(json.dumps(saved))
    print(f"credits spent: {spent['credits']} | left: {spent['left']}", flush=True)
    for test in ("model vs early line", "model vs close line", "stale soft line (1.5+ off Pinnacle at the close)"):
        bs = [b for b in bets if b["test"] == test]
        print(f"\n=== {test}: {len(bs)} bets (one per book; a player can count at several books)")
        for half in ("Oct-Jan", "Jan-Apr"):
            print(f"  {half}: {rec([b for b in bs if b['half'] == half])}")
        for nm, fn in (("over", lambda b: b["side"] == "over"), ("under", lambda b: b["side"] == "under"),
                       ("big (5+ off / 2.5+ stale)", lambda b: b["big"]), ("teammate freshly out", lambda b: b["fresh"]),
                       ("bench (under 20 mpg)", lambda b: b["bench"]),
                       ("our model agrees (stale only)", lambda b: b.get("model_agrees") is True)):
            xs = [b for b in bs if fn(b)]
            if xs:
                print(f"  {nm:30} Oct-Jan {rec([b for b in xs if b['half'] == 'Oct-Jan']):40} Jan-Apr {rec([b for b in xs if b['half'] == 'Jan-Apr'])}")
        for bk in SOFT:
            xs = [b for b in bs if b["book"] == bk]
            if xs:
                print(f"    at {bk:16} Oct-Jan {rec([b for b in xs if b['half'] == 'Oct-Jan']):40} Jan-Apr {rec([b for b in xs if b['half'] == 'Jan-Apr'])}")


if __name__ == "__main__":
    main()
