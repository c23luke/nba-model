"""CONFIDENCE FROM SAMPLE SIZE (2026-11-11). The players model's gap 4-5 wins (109-64) but 5-6 loses (55-56):
big gaps may be the model being wrong, not the market. Suspect: a team leaning on players the model barely knows.
"Thin" player = no rating from last season (rookie or new to the league) and under 200 minutes this season before
tonight. For each game, the share of each team's minutes tonight played by thin players; the game's thin share =
the larger of the two. The live players model's record (at the open, gap 3+), split by that share and gap size,
and by whether the side we'd bet or the other side is the thin one.
Run: python -m engine.measure_unknowns
"""
from __future__ import annotations

from collections import defaultdict

from . import backtest as BT
from . import backtest_open as BO
from . import measure_stacks as MS
from . import personnel as P
from .measure_opp_adjust import model_rows, rec

THIN_MIN = 200


def thin_shares(season):
    prior, _ = BO.priors(season)
    games, _ = MS.fetch(season)
    by_day = defaultdict(list)
    for g, rows, _ in games:
        if rows:
            by_day[g.game_date].append((g, rows))
    mins = defaultdict(float)
    out = {}
    for day in sorted(by_day):
        for g, rows in by_day[day]:
            sh = {}
            for t in (g.home, g.away):
                tr = [r for r in rows if r["team"] == t and r["min"] > 0]
                tot = sum(r["min"] for r in tr) or 1
                thin = 0.0
                for r in tr:
                    pr = prior.get(P.norm(r["name"])) or BT._fuzzy(prior, r["name"])
                    vet = pr is not None and pr.get("kind") == "veteran"
                    if not vet and mins[r["espn_id"]] < THIN_MIN:
                        thin += r["min"]
                sh[t] = thin / tot
            out[(day, g.home, g.away)] = sh
        for g, rows in by_day[day]:
            for r in rows:
                mins[r["espn_id"]] += r["min"]
    return out


def main():
    cells = defaultdict(list)
    for season in BO.SEASONS:
        sh = thin_shares(season)
        for r in model_rows(season):
            g = r["gap"]
            if abs(g) < 3 or r["actual"] is None:
                continue
            s = sh.get((r["date"], r["home"], r["away"]))
            if not s:
                continue
            side, other = (r["home"], r["away"]) if g > 0 else (r["away"], r["home"])
            res = r["actual"] + r["open"]
            res = res if g > 0 else -res
            x = "W" if res > 0 else "L" if res < 0 else "P"
            mx = max(s.values())
            b = "under 10%" if mx < 0.10 else "10-20%" if mx < 0.20 else "20-30%" if mx < 0.30 else "30%+"
            a = abs(g)
            gb = "3-4" if a < 4 else "4-5" if a < 5 else "5-6" if a < 6 else "6+"
            who = ("the side we'd bet is thinner" if s[side] > s[other] + 0.05 else
                   "the other side is thinner" if s[other] > s[side] + 0.05 else "about even")
            for sc in (season, "both"):
                cells[(sc, "share", b)].append(x)
                cells[(sc, "share x gap", b, gb)].append(x)
                cells[(sc, "who", who)].append(x)
                if a >= 4:
                    cells[(sc, "4+ share", b)].append(x)
                    cells[(sc, "4+ who", who)].append(x)
    # system bets and MONEYBALL: same "who is thinner" split, one bet per game side
    for season in BO.SEASONS:
        sh = thin_shares(season)
        games, _ = MS.fetch(season)
        key = {str(g.id): (g.game_date, g.home, g.away) for g, _, _ in games}
        sides = defaultdict(list)
        for r in MS.season_rows(season):
            if r["bet"] == "spread" and r["system"] < 300 and r["system"] != 113 and r["gap"] is not None:
                sides[(r["game"], r["side"])].append(r)
        for (gid, side), ps in sides.items():
            if ps[0]["gap"] < 3 or ps[0]["res"] == "P":
                continue
            k = key.get(str(gid))
            s = sh.get(k) if k else None
            if not s or side not in s:
                continue
            other = k[2] if side == k[1] else k[1]
            who = ("the side we'd bet is thinner" if s[side] > s[other] + 0.05 else
                   "the other side is thinner" if s[other] > s[side] + 0.05 else "about even")
            kind = "MONEYBALL" if len({p["system"] for p in ps}) >= 2 else "system bet"
            for sc in (season, "both"):
                cells[(sc, kind, who)].append(ps[0]["res"])
    bands = ["under 10%", "10-20%", "20-30%", "30%+"]
    whos = ["the side we'd bet is thinner", "about even", "the other side is thinner"]
    for sc in list(BO.SEASONS) + ["both"]:
        print(f"\n=== {sc}: players model gap 3+ at the open, by the share of minutes played by thin players")
        for b in bands:
            print(f"  {b:12} all 3+ {rec(cells[(sc, 'share', b)])[1]:28} 4+ {rec(cells[(sc, '4+ share', b)])[1]}")
            for gb in ("3-4", "4-5", "5-6", "6+"):
                print(f"      gap {gb:4} {rec(cells[(sc, 'share x gap', b, gb)])[1]}")
        for w in whos:
            print(f"  {w:30} all 3+ {rec(cells[(sc, 'who', w)])[1]:28} 4+ {rec(cells[(sc, '4+ who', w)])[1]}")
        for kind in ("system bet", "MONEYBALL"):
            print(f"  {kind} (players model 3+):")
            for w in whos:
                print(f"      {w:30} {rec(cells[(sc, kind, w)])[1]}")


if __name__ == "__main__":
    main()
