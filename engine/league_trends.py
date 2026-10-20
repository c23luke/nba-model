"""How the NBA has changed, 2020-21 to 2025-26 — and where the betting market lags behind it.

From every regular-season box score (ESPN) and the closing lines we already have:
  game style   pace, points per 100, 3PA share, 3P%, assist rate, FT rate, turnovers, offensive boards
  minutes      top players' minutes, how many 34+ mpg players, bench share, how many players a night
  bigs         centers' 3-point attempts per 36 and 3P% (stretch bigs)
  betting      over % and (actual - closing total) by month; favorite cover % by spread size;
               home cover %; how far scoring moved vs the season before
"""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from . import backtest as BT
from . import mine as M
from . import personnel as P
from . import sources
from .teams import code


def _pair(v):
    try:
        a, b = str(v).split("-")
        return int(a), int(b)
    except ValueError:
        return 0, 0


def _int(v):
    try:
        return int(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return 0


def box(g):
    js = BT._safe(sources.get_json, BT.SUM.format(g.id))
    if not js:
        return g, []
    out = []
    for t in (js.get("boxscore") or {}).get("players", []):
        team = code(t["team"]["abbreviation"])
        st = t["statistics"][0]
        keys = st["keys"]
        for a in st.get("athletes", []):
            if a.get("didNotPlay") or not a.get("stats"):
                continue
            d = dict(zip(keys, a["stats"]))
            mins = _int(d.get("minutes"))
            if mins <= 0:
                continue
            fgm, fga = _pair(d.get("fieldGoalsMade-fieldGoalsAttempted"))
            f3m, f3a = _pair(d.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
            ftm, fta = _pair(d.get("freeThrowsMade-freeThrowsAttempted"))
            pos = ((a.get("athlete") or {}).get("position") or {}).get("abbreviation", "")
            out.append({"team": team, "id": (a.get("athlete") or {}).get("id"), "pos": pos, "min": mins,
                        "pts": _int(d.get("points")), "fgm": fgm, "fga": fga, "f3m": f3m, "f3a": f3a,
                        "ftm": ftm, "fta": fta, "orb": _int(d.get("offensiveRebounds")),
                        "ast": _int(d.get("assists")), "tov": _int(d.get("turnovers"))})
    return g, out


def month_label(d):
    return {10: "Oct", 11: "Nov", 12: "Dec", 1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May"}[d.month]


def main():
    seasons = {}
    for season in M.SEASONS:
        games, start, end, days = M.games_for(season)
        lines, _ = M.closing_lines(season, days, "")
        with ThreadPoolExecutor(16) as ex:
            boxes = list(ex.map(box, games))
        seasons[season] = (boxes, lines, start)
        print(f"{season}: {len(games)} games, {sum(1 for _, b in boxes if b)} box scores")

    print("\n=== HOW THE GAME IS PLAYED (per team per game unless noted)")
    hdr = f"{'season':8} {'pace':>6} {'pts/100':>8} {'3PA%':>6} {'3P%':>6} {'AST/FGM':>8} {'FTA/FGA':>8} {'TOV/100':>8} {'ORB/g':>6} {'pts/g':>6}"
    print(hdr)
    style = {}
    for season, (boxes, lines, start) in seasons.items():
        agg = defaultdict(float)
        ngames = 0
        for g, rows in boxes:
            if not rows:
                continue
            ngames += 1
            for r in rows:
                for k in ("pts", "fgm", "fga", "f3m", "f3a", "ftm", "fta", "orb", "ast", "tov"):
                    agg[k] += r[k]
        teams = ngames * 2
        poss = agg["fga"] + 0.44 * agg["fta"] - agg["orb"] + agg["tov"]
        s = {"pace": poss / teams, "ortg": agg["pts"] / poss * 100, "3pa_share": agg["f3a"] / agg["fga"],
             "3p": agg["f3m"] / agg["f3a"], "ast_fgm": agg["ast"] / agg["fgm"], "fta_fga": agg["fta"] / agg["fga"],
             "tov100": agg["tov"] / poss * 100, "orb": agg["orb"] / teams, "ppg": agg["pts"] / teams}
        style[season] = s
        print(f"{season:8} {s['pace']:6.1f} {s['ortg']:8.1f} {s['3pa_share']:6.1%} {s['3p']:6.1%} {s['ast_fgm']:8.1%} "
              f"{s['fta_fga']:8.3f} {s['tov100']:8.1f} {s['orb']:6.1f} {s['ppg']:6.1f}")

    print("\n=== MINUTES (who plays, how much)")
    print(f"{'season':8} {'players/night':>13} {'top-1 mpg':>9} {'top-5 mpg':>9} {'bench share':>11} {'34+ mpg players':>16}")
    for season, (boxes, lines, start) in seasons.items():
        per_team_game = []
        player_min = defaultdict(lambda: [0, 0])
        for g, rows in boxes:
            byteam = defaultdict(list)
            for r in rows:
                byteam[r["team"]].append(r)
                player_min[r["id"]][0] += r["min"]
                player_min[r["id"]][1] += 1
            for t, rs in byteam.items():
                mins = sorted((r["min"] for r in rs), reverse=True)
                tot = sum(mins) or 1
                per_team_game.append((len(mins), mins[0], sum(mins[:5]) / 5, sum(mins[5:]) / tot))
        n = len(per_team_game) or 1
        heavy = sum(1 for m, gp in player_min.values() if gp >= 40 and m / gp >= 34)
        print(f"{season:8} {sum(x[0] for x in per_team_game)/n:13.1f} {sum(x[1] for x in per_team_game)/n:9.1f} "
              f"{sum(x[2] for x in per_team_game)/n:9.1f} {sum(x[3] for x in per_team_game)/n:11.1%} {heavy:16d}")

    print("\n=== BIGS (players listed C)")
    print(f"{'season':8} {'C 3PA per 36':>12} {'C 3P%':>6} {'share of C with 2+ 3PA/36':>26}")
    for season, (boxes, lines, start) in seasons.items():
        acc = defaultdict(lambda: [0, 0, 0])
        for g, rows in boxes:
            for r in rows:
                if r["pos"] == "C":
                    a = acc[r["id"]]
                    a[0] += r["min"]; a[1] += r["f3a"]; a[2] += r["f3m"]
        mins = sum(a[0] for a in acc.values()) or 1
        f3a = sum(a[1] for a in acc.values())
        f3m = sum(a[2] for a in acc.values())
        regular = [a for a in acc.values() if a[0] >= 500]
        stretch = sum(1 for a in regular if a[1] / a[0] * 36 >= 2) / max(len(regular), 1)
        print(f"{season:8} {f3a / mins * 36:12.2f} {f3m / max(f3a, 1):6.1%} {stretch:26.0%}")

    print("\n=== BETTING: does the market keep up? (vs the closing line)")
    print("Totals by month: over record, and average (actual points - closing total)")
    months = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May"]
    print(f"{'season':8} " + " ".join(f"{m:>15}" for m in months))
    allm = defaultdict(lambda: [0, 0, 0.0, 0])
    for season, (boxes, lines, start) in seasons.items():
        bym = defaultdict(lambda: [0, 0, 0.0, 0])
        for g, rows in boxes:
            ln = lines.get(f"{g.game_date.isoformat()}|{g.away}|{g.home}") or {}
            t = ln.get("total")
            if t is None:
                continue
            pts = g.home_score + g.away_score
            m = month_label(g.game_date)
            for b in (bym[m], allm[m]):
                b[2] += pts - t
                b[3] += 1
                if pts > t:
                    b[0] += 1
                elif pts < t:
                    b[1] += 1
        print(f"{season:8} " + " ".join(
            f"{bym[m][0]:>3}-{bym[m][1]:<3}{bym[m][2] / bym[m][3]:+5.1f}  " if bym[m][3] else f"{'-':>15}" for m in months))
    print(f"{'ALL':8} " + " ".join(
        f"{allm[m][0]:>3}-{allm[m][1]:<3}{allm[m][2] / allm[m][3]:+5.1f}  " if allm[m][3] else f"{'-':>15}" for m in months))

    print("\nFirst 2 weeks of each season: over record vs the close, and points vs the season before's average")
    prev = None
    for season, (boxes, lines, start) in seasons.items():
        o = u = 0
        diff = 0.0
        n = 0
        for g, rows in boxes:
            if (g.game_date - start).days >= 14:
                continue
            t = (lines.get(f"{g.game_date.isoformat()}|{g.away}|{g.home}") or {}).get("total")
            if t is None:
                continue
            pts = g.home_score + g.away_score
            o += pts > t
            u += pts < t
            diff += pts - t
            n += 1
        change = "" if prev is None else f"  league scoring vs season before: {style[season]['ppg'] * 2 - style[prev]['ppg'] * 2:+.1f} pts/game"
        print(f"  {season}: overs {o}-{u}, actual minus close {diff / max(n, 1):+.1f}{change}")
        prev = season

    print("\nSpreads: favorite cover % by size, and home cover % (all six seasons, by season)")
    buckets = [("fav 0.5-3", 0, 3), ("fav 3.5-6.5", 3.5, 6.5), ("fav 7-9.5", 7, 9.5), ("fav 10-13.5", 10, 13.5), ("fav 14+", 14, 99)]
    print(f"{'season':8} " + " ".join(f"{b[0]:>13}" for b in buckets) + f" {'home cover':>11}")
    for season, (boxes, lines, start) in seasons.items():
        rec = {b[0]: [0, 0] for b in buckets}
        home = [0, 0]
        for g, rows in boxes:
            hs = (lines.get(f"{g.game_date.isoformat()}|{g.away}|{g.home}") or {}).get("spread")
            if hs is None or hs == 0:
                continue
            res = (g.home_score - g.away_score) + hs
            if res == 0:
                continue
            home[0 if res > 0 else 1] += 1
            fav_covered = (res > 0) == (hs < 0)
            for name, lo, hi in buckets:
                if lo <= abs(hs) <= hi:
                    rec[name][0 if fav_covered else 1] += 1
        print(f"{season:8} " + " ".join(f"{rec[b[0]][0]:>6}-{rec[b[0]][1]:<6}" for b in buckets)
              + f" {home[0]:>5}-{home[1]:<5}")
    (P.STATIC / "league_trends.json").write_text(json.dumps(style))


if __name__ == "__main__":
    main()
