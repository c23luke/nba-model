"""One-off checks before line shopping goes live:
  1. How far NBA totals land from the closing total (2025-26) -> the SD used to compare different total lines.
  2. What The Odds API's exchange region (us_ex) returns right now: which venues, which markets, what prices.
"""
from __future__ import annotations

import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from . import sources
from .personnel import STATIC


def total_sd():
    close = json.loads((STATIC / "odds_totals_2025_26.json").read_text())
    days = [date(2025, 10, 21) + timedelta(i) for i in range((date(2026, 4, 12) - date(2025, 10, 21)).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        games = [g for day in ex.map(lambda d: _safe_day(d), days) for g, _ in day if g.final]
    res = []
    for g in games:
        t = (close.get(f"{g.game_date.isoformat()}|{g.away}|{g.home}") or {}).get("close")
        if t is not None:
            res.append(g.home_score + g.away_score - t)
    n = len(res)
    mean = sum(res) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in res) / (n - 1))
    print(f"TOTALS 2025-26: {n} games, actual minus closing total mean {mean:+.2f}, SD {sd:.2f}")


def _safe_day(d):
    try:
        return sources.espn_day(d)
    except Exception:
        return []


def exchanges():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    meta = {}
    url = ("https://api.the-odds-api.com/v4/sports/basketball_nba/odds?apiKey={}&regions=us_ex"
           "&markets=spreads,totals,h2h&oddsFormat=american&includeBetLimits=true").format(key)
    events = sources.get_json(url, meta=meta)
    print(f"\nEXCHANGES (us_ex): {len(events)} games, credits left {meta.get('x-requests-remaining')}, "
          f"last call cost {meta.get('x-requests-last')}")
    venues = {}
    for ev in events[:8]:
        print(f"\n{ev['away_team']} @ {ev['home_team']}  {ev['commence_time']}")
        for bk in ev.get("bookmakers", []):
            venues[bk["key"]] = venues.get(bk["key"], 0) + 1
            for m in bk.get("markets", []):
                outs = "  ".join(f"{o['name']} {o.get('point', '')} {o['price']}"
                                 + (f" (limit {o['bet_limit']})" if o.get("bet_limit") is not None else "")
                                 for o in m["outcomes"])
                print(f"  {bk['key']:14} {m['key']:8} {outs}")
    for ev in events[8:]:
        for bk in ev.get("bookmakers", []):
            venues[bk["key"]] = venues.get(bk["key"], 0) + 1
    print("\nvenues and how many games each has:", venues)


if __name__ == "__main__":
    exchanges()
    total_sd()
