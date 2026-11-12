"""CRAZIER IDEAS (Caden 2026-11-11: "go further ... test crazy stuff ... use shot quality luck and everything").
Two seasons, free (ESPN summaries with shot locations, box scores; saved lines). A result counts only if it wins in
BOTH seasons.
A. SHOT-QUALITY SPREAD: each team's last 10 games rated only by the shots it took and allowed (field-goal points
   at league rates by zone, plus actual free-throw points): "deserved" margin per game. Home edge = home deserved
   - away deserved + home court (2.0). Bet when that disagrees with the spread by 4+ / 6+.
B. SHOT-QUALITY TOTAL: deserved points for both teams (own shots and the shots the opponent allows, averaged) vs the
   total. Over / under when 5+ / 8+ off.
C. NET SHOOTING LUCK: (own FG points above shot quality) - (opponents' FG points above shot quality allowed), last
   10. Bet the unlucky team when the gap is 5+ / 8+ points a game.
D. TRAVEL: miles between the arenas of the team's last game and tonight's, on a back-to-back (1,000+ / 1,500+) ->
   fade. Home after a road trip of 4+ games: bet / fade.
E. ALTITUDE: visitors at Denver or Utah on a back-to-back -> home.
F. VARIANCE DOG: an 8+ point underdog in the top third of three-point share (last 10) -> dog.
Run: python -m engine.measure_ideas3
"""
from __future__ import annotations

import math
from collections import defaultdict

from . import backtest_open as BO
from .measure_ideas import ats, ou, rec
from .measure_ideas2 import team_ft
from .measure_minutes_spots import load
from .prop_model import ZONES, shot_list

ARENA = {"ATL": (33.76, -84.40), "BOS": (42.37, -71.06), "BKN": (40.68, -73.98), "CHA": (35.23, -80.84),
         "CHI": (41.88, -87.67), "CLE": (41.50, -81.69), "DAL": (32.79, -96.81), "DEN": (39.75, -105.01),
         "DET": (42.34, -83.06), "GSW": (37.77, -122.39), "HOU": (29.75, -95.36), "IND": (39.76, -86.16),
         "LAC": (33.94, -118.34), "LAL": (34.04, -118.27), "MEM": (35.14, -90.05), "MIA": (25.78, -80.19),
         "MIL": (43.05, -87.92), "MIN": (44.98, -93.28), "NOP": (29.95, -90.08), "NYK": (40.75, -73.99),
         "OKC": (35.46, -97.52), "ORL": (28.54, -81.38), "PHI": (39.90, -75.17), "PHX": (33.45, -112.07),
         "POR": (45.53, -122.67), "SAC": (38.58, -121.50), "SAS": (29.43, -98.44), "TOR": (43.64, -79.38),
         "UTA": (40.77, -111.90), "WAS": (38.90, -77.02)}
HCA = 2.0


def miles(a, b):
    if a not in ARENA or b not in ARENA:
        return 0.0
    (la1, lo1), (la2, lo2) = ARENA[a], ARENA[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    d = math.acos(min(1, math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(math.radians(lo2 - lo1))))
    return d * 3959


def season_rows(season):
    games, sums, lines = load(season)
    import json
    from . import personnel as P
    totals = json.loads((P.STATIC / f"odds_totals_{season.replace('-', '_')}.json").read_text())
    zl = {z: [0, 0] for z in ZONES}
    hist = defaultdict(list)       # team -> per game {"xo","xd","ao","ad","fto","ftd","three","fga"}
    last = {}                      # team -> {"date","site"}
    road = defaultdict(int)        # team -> consecutive road games before tonight
    out = []
    for g in games:
        js = sums.get(g.id) or {}
        k = f"{g.game_date.isoformat()}|{g.away}|{g.home}"
        ln, tt = lines.get(k) or {}, totals.get(k) or {}
        row = {"margin": g.home_score - g.away_score, "pts": g.home_score + g.away_score, "open": ln.get("open"),
               "close": ln.get("close"), "t_open": tt.get("open"), "t_close": tt.get("close"), "home": g.home}
        for side, t in (("h", g.home), ("a", g.away)):
            h = hist[t][-10:]
            if len(h) >= 5:
                n = len(h)
                row[f"xo_{side}"] = sum(x["xo"] + x["fto"] for x in h) / n
                row[f"xd_{side}"] = sum(x["xd"] + x["ftd"] for x in h) / n
                row[f"luck_{side}"] = sum((x["ao"] - x["xo"]) - (x["ad"] - x["xd"]) for x in h) / n
                row[f"three_{side}"] = sum(x["three"] for x in h) / max(1, sum(x["fga"] for x in h))
            p = last.get(t)
            row[f"b2b_{side}"] = bool(p and (g.game_date - p["date"]).days == 1)
            row[f"miles_{side}"] = miles(p["site"], g.home) if p else 0.0
            row[f"road_{side}"] = road[t]
        out.append(row)
        # update
        L = {z: (v[1] / v[0] if v[0] else 0) for z, v in zl.items()}
        shots = shot_list(js)
        ft = team_ft(js)
        per = {t: {"x": 0.0, "a": 0.0, "three": 0, "fga": 0} for t in (g.home, g.away)}
        for team, _, z, pts in shots:
            if team in per:
                per[team]["x"] += L[z]; per[team]["a"] += pts; per[team]["fga"] += 1
                per[team]["three"] += z in ("corner3", "above3")
        ok = sum(v[0] for v in zl.values()) > 2000 and all(per[t]["fga"] > 40 for t in per)
        for t, o in ((g.home, g.away), (g.away, g.home)):
            if ok:
                hist[t].append({"xo": per[t]["x"], "ao": per[t]["a"], "xd": per[o]["x"], "ad": per[o]["a"],
                                "fto": (ft.get(t) or (0, 0))[0], "ftd": (ft.get(o) or (0, 0))[0],
                                "three": per[t]["three"], "fga": per[t]["fga"]})
            last[t] = {"date": g.game_date, "site": g.home}
        road[g.away] += 1
        road[g.home] = 0
        for team, _, z, pts in shots:
            zl[z][0] += 1; zl[z][1] += pts
    # three-point share tercile cut per season
    shares = sorted(r[s] for r in out for s in ("three_h", "three_a") if r.get(s) is not None)
    cut = shares[int(len(shares) * 2 / 3)] if shares else 1
    for r in out:
        r["three_cut"] = cut
    return out


def main():
    data = {s: season_rows(s) for s in BO.SEASONS}

    def x_edge(r):
        if r.get("xo_h") is None or r.get("xo_a") is None:
            return None
        home_d = (r["xo_h"] - r["xd_h"]) / 2 - (r["xo_a"] - r["xd_a"]) / 2 + HCA
        return home_d                                       # deserved home margin
    tests = []
    for c in (4, 6):
        tests.append((f"A. shot-quality margin disagrees with the spread by {c}+", "ats",
                      lambda r, c=c: None if x_edge(r) is None or r.get("_line") is None else
                      ("home" if x_edge(r) + r["_line"] >= c else "away" if x_edge(r) + r["_line"] <= -c else None)))
    for c in (5, 8):
        tests.append((f"B. shot-quality total {c}+ above the total -> over", "ou",
                      lambda r, c=c: None if r.get("xo_h") is None or r.get("xo_a") is None or r.get("_tot") is None else
                      ("over" if (r["xo_h"] + r["xd_a"]) / 2 + (r["xo_a"] + r["xd_h"]) / 2 - r["_tot"] >= c else None)))
        tests.append((f"B. shot-quality total {c}+ below the total -> under", "ou",
                      lambda r, c=c: None if r.get("xo_h") is None or r.get("xo_a") is None or r.get("_tot") is None else
                      ("under" if (r["xo_h"] + r["xd_a"]) / 2 + (r["xo_a"] + r["xd_h"]) / 2 - r["_tot"] <= -c else None)))
    for c in (5, 8):
        tests.append((f"C. net shooting luck gap {c}+ a game: bet the unlucky team", "ats",
                      lambda r, c=c: None if r.get("luck_h") is None or r.get("luck_a") is None else
                      ("away" if r["luck_h"] - r["luck_a"] >= c else "home" if r["luck_a"] - r["luck_h"] >= c else None)))
    for c in (1000, 1500):
        tests.append((f"D. flew {c}+ miles on a back-to-back -> fade", "ats",
                      lambda r, c=c: ("away" if r["b2b_h"] and r["miles_h"] >= c and not (r["b2b_a"] and r["miles_a"] >= c)
                                      else "home" if r["b2b_a"] and r["miles_a"] >= c and not (r["b2b_h"] and r["miles_h"] >= c) else None)))
    tests.append(("D. first home game after a 4+ game road trip -> bet the home team", "ats",
                  lambda r: "home" if r["road_h"] >= 4 else None))
    tests.append(("D. first home game after a 4+ game road trip -> fade the home team", "ats",
                  lambda r: "away" if r["road_h"] >= 4 else None))
    tests.append(("E. visitor at DEN / UTA on a back-to-back -> home", "ats",
                  lambda r: "home" if r["home"] in ("DEN", "UTA") and r["b2b_a"] else None))
    tests.append(("F. 8+ point underdog in the top third of 3-point share -> dog", "ats",
                  lambda r: None if r.get("_line") is None else
                  ("home" if r["_line"] >= 8 and (r.get("three_h") or 0) >= r["three_cut"] else
                   "away" if r["_line"] <= -8 and (r.get("three_a") or 0) >= r["three_cut"] else None)))
    print(f"{'idea':66} {'season':8} {'at the open':>18} {'at the close':>18}")
    for name, kind, pick in tests:
        for s in list(BO.SEASONS) + ["both"]:
            rows = data[s] if s != "both" else [r for v in data.values() for r in v]
            res = []
            for when in ("open", "close"):
                for r in rows:
                    r["_line"] = r.get(when)
                    r["_tot"] = r.get("t_" + when)
                f = ats if kind == "ats" else ou
                res.append(rec(f(rows, pick, when)))
            print(f"{name if s == list(BO.SEASONS)[0] else '':66} {s:8} {res[0]:>18} {res[1]:>18}")


if __name__ == "__main__":
    main()
