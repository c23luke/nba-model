"""BAD TEAMS ON SYSTEM BETS AND MONEYBALL (Caden 2026-11-11: a MONEYBALL bet on the Bulls +12.5, ranked 25th and
1-8 — "i just wanna test it").

The players model alone (T13) already skips teams the market ranks 21-30 (measured: 163-185 on them). System bets
(a system + the players model agreeing by 3+) and MONEYBALL (2+ systems + players 3+) never had that filter.
This replays both, exactly as engine.measure_agree did (2024-25 and 2025-26 at the OPENING line, one bet per game
side), and splits them by how the market ranked the team we'd bet that day (average opening-line rating so far
this season, today's line included, as live; rank 1 = best), and by the size of the spread.
Run: python -m engine.measure_badteams_combos
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import backtest_open as BO
from . import mine
from . import personnel as P
from .measure_stacks import season_rows

HCA = P.HOME_COURT


def ranks_by_game(season):
    """game id -> {team: market rank that day (1 = best), plus the number of teams ranked}."""
    games, _, _, _ = mine.games_for(season)
    lines = json.loads((P.STATIC / f"odds_openclose_{season.replace('-', '_')}.json").read_text())
    rs, rn = defaultdict(float), defaultdict(int)
    by_day = defaultdict(list)
    for g in games:
        by_day[g.game_date].append(g)
    out = {}
    for day in sorted(by_day):
        todays = []
        for g in by_day[day]:
            op = (lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}).get("open")
            if op is None:
                continue
            exp_home = -op
            rs[g.home] += exp_home - HCA; rn[g.home] += 1
            rs[g.away] += -(exp_home - HCA); rn[g.away] += 1
            todays.append(g)
        order = sorted(rn, key=lambda t: -rs[t] / rn[t])
        rank = {t: i + 1 for i, t in enumerate(order)}
        for g in todays:
            out[str(g.id)] = {"rank": rank, "teams": len(order), "day": (day - BO.SEASONS[season]["start"]).days}
    return out


def rec(rs):
    w, l = sum(r == "W" for r in rs), sum(r == "L" for r in rs)
    n = w + l
    return f"{w}-{l}" + (f"  {w / n:5.1%}  {w * 100 / 110 - l:+6.1f}u" if n else "")


def main():
    cells = defaultdict(lambda: defaultdict(list))
    examples = []
    for season in BO.SEASONS:
        rows = [r for r in season_rows(season) if r["bet"] == "spread" and r["system"] < 300 and r["system"] != 113]
        rk = ranks_by_game(season)
        sides = defaultdict(list)
        for r in rows:
            sides[(r["game"], r["side"])].append(r)
        for (gid, side), ps in sides.items():
            gap, res = ps[0]["gap"], ps[0]["res"]
            if gap is None or gap < 3 or res == "P":
                continue
            k = len({p["system"] for p in ps})
            kind = "MONEYBALL (2+ systems + players 3+)" if k >= 2 else "System bet (1 system + players 3+)"
            info = rk.get(str(gid))
            if not info or info["teams"] < 30:
                band = "no full ranking yet"
            else:
                r_ = info["rank"].get(side)
                band = "ranked 1-10" if r_ <= 10 else "ranked 11-20" if r_ <= 20 else "ranked 21-30 (bottom 10)"
            line = ps[0].get("line")
            for scope in (season, "both"):
                cells[(scope, kind)][band].append(res)
                if band.startswith("ranked 21-30"):
                    r_ = info["rank"][side]
                    cells[(scope, kind)]["  ranked 28-30 (bottom 3)" if r_ >= 28 else "  ranked 21-27"].append(res)
                    cells[(scope, kind)]["  ranked 26-30 (bottom 5)" if r_ >= 26 else "  ranked 21-25"].append(res)
                    cells[(scope, kind)][f"    rank {r_}"].append(res)
                    cells[(scope, kind)]["  bottom 10, first 30 days" if info["day"] < 30 else "  bottom 10, after 30 days"].append(res)
                    if line is not None:
                        cells[(scope, kind)]["  bottom 10, getting 10+ pts" if line >= 10 else "  bottom 10, under 10 pts"].append(res)
                if line is not None and line >= 10:
                    cells[(scope, kind)]["any rank, getting 10+ pts"].append(res)
            if band.startswith("ranked 21-30") and k >= 2:
                examples.append(f"{season} day {info['day']:3}: {side} (rank {info['rank'][side]}) {line:+} "
                                f"gap {gap:+.1f}, systems {sorted({p['system'] for p in ps})} -> {res}")
    order = ["ranked 1-10", "ranked 11-20", "ranked 21-30 (bottom 10)", "  ranked 21-25", "  ranked 26-30 (bottom 5)",
             "  ranked 21-27", "  ranked 28-30 (bottom 3)"] + [f"    rank {i}" for i in range(21, 31)] + [ "  bottom 10, first 30 days", "  bottom 10, after 30 days", "  bottom 10, getting 10+ pts", "  bottom 10, under 10 pts",
             "any rank, getting 10+ pts", "no full ranking yet"]
    for scope in list(BO.SEASONS) + ["both"]:
        print(f"\n=== {scope} (at the open, one bet per side, -110)")
        for kind in ("System bet (1 system + players 3+)", "MONEYBALL (2+ systems + players 3+)"):
            c = cells[(scope, kind)]
            allr = [x for b in ("ranked 1-10", "ranked 11-20", "ranked 21-30 (bottom 10)", "no full ranking yet") for x in c[b]]
            print(f"  {kind}: all {rec(allr)}")
            for b in order:
                if c[b]:
                    print(f"    {b:32} {rec(c[b])}")
    print("\n=== every MONEYBALL on a bottom-10 team")
    for e in examples:
        print("  " + e)


if __name__ == "__main__":
    main()
