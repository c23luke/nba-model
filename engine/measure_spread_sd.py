"""Measure how far NBA results land from the closing spread (2025-26 regular season).
Lines: ESPN scoreboard odds, else the game summary's pickcenter (DraftKings)."""
from __future__ import annotations
import math, traceback
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from . import sources
from .teams import code

SUM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={}"

def one(d):
    try:
        return sources.espn_day(d)
    except Exception:
        return []

def pick_line(g):
    try:
        js = sources.get_json(SUM.format(g.id))
        for pc in js.get("pickcenter") or []:
            sp = pc.get("spread")
            hf = (pc.get("homeTeamOdds") or {}).get("favorite")
            det = pc.get("details") or ""
            if sp is None:
                continue
            sp = float(sp)
            # ESPN pickcenter "spread" is from the home team's side
            return sp
    except Exception:
        return None
    return None

try:
    days = [date(2025, 10, 21) + timedelta(i) for i in range((date(2026, 4, 12) - date(2025, 10, 21)).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        allg = [x for day in ex.map(one, days) for x in day]
    finals = [(g, ln) for g, ln in allg if g.final]
    with_line = sum(1 for _, ln in finals if ln and ln.get("home_spread") is not None)
    print(f"finals: {len(finals)}; with a scoreboard line: {with_line}")
    need = [g for g, ln in finals if not (ln and ln.get("home_spread") is not None)]
    with ThreadPoolExecutor(12) as ex:
        extra = dict(zip([g.id for g in need], ex.map(pick_line, need)))
    res, sample = [], []
    for g, ln in finals:
        hs = ln["home_spread"] if (ln and ln.get("home_spread") is not None) else extra.get(g.id)
        if hs is None:
            continue
        res.append((g.home_score - g.away_score) + hs)
        if len(sample) < 5:
            sample.append(f"{g.away} {g.away_score} @ {g.home} {g.home_score}, home spread {hs:+g}")
    print("sample:", *sample, sep="\n  ")
    n = len(res)
    print(f"games with a line and a result: {n}")
    if n:
        mean = sum(res) / n
        sd = math.sqrt(sum((r - mean) ** 2 for r in res) / (n - 1))
        print(f"home margin minus spread: mean {mean:+.2f}, SD {sd:.2f}")
        print(f"home covered {sum(r > 0 for r in res)/n:.1%}, push {sum(r == 0 for r in res)/n:.1%}")
except Exception:
    traceback.print_exc()
