"""TRENDS (Caden 2026-11-24): Trends Center's NBA trends, checked on our own data — 6 seasons at the closing line.

Read from @trendscenterapp's X posts (Nov 24). Their records span up to 31 years; ours is 2020-21 to 2025-26 (Odds API
closing consensus, -110). Team-specific or "since Christmas" style trends can't be tested fairly and are left out; the
rest are written as general rules. Only earlier games count toward streaks, records and rest.
A trend PASSES Caden's bar if it is 56%+ overall with no season under 53% (seasons with fewer than 5 bets skipped).
Run: python -m engine.measure_trends
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date

from . import mine as M

EAST = {"ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DET", "IND", "MIA", "MIL", "NYK", "ORL", "PHI", "TOR", "WAS"}


def ctx(h, day, home_today):
    """A team's situation going into today, from its earlier games h (dicts in date order)."""
    last = h[-1] if h else None
    ws = ls = 0
    for x in reversed(h):
        if x["won"] and ls == 0:
            ws += 1
        elif not x["won"] and ws == 0:
            ls += 1
        else:
            break
    stretch = 0                                  # consecutive home (or road) games including today
    for x in reversed(h):
        if x["home"] != home_today:
            break
        stretch += 1
    prev_road = 0                                # road games right before today (for "first game back home")
    for x in reversed(h):
        if x["home"]:
            break
        prev_road += 1
    n = len(h)
    cov = [x["cov"] for x in h if x.get("cov") is not None]
    cs = ncs = 0                                  # straight covers / straight non-covers
    for c in reversed(cov):
        if c and ncs == 0:
            cs += 1
        elif not c and cs == 0:
            ncs += 1
        else:
            break
    return {"cs": cs, "ncs": ncs, "in6": sum(1 for x in h if 1 <= (day - x["date"]).days <= 5) + 1,
            "rest": (day - last["date"]).days - 1 if last else None, "hist": list(h), "n": n,     # hist is a COPY: no later games
            "wp": (sum(x["won"] for x in h) / n) if n else None, "wins": sum(x["won"] for x in h),
            "ws": ws, "ls": ls, "b2b": bool(last and (day - last["date"]).days == 1),
            "in4": sum(1 for x in h if 1 <= (day - x["date"]).days <= 3) + 1,
            "last": last, "stretch": stretch + 1, "prev_road": prev_road}


def build(season, key):
    games, start, end, days = M.games_for(season)
    lines, _ = M.closing_lines(season, days, key)
    hist = defaultdict(list)
    rows, totals = [], []
    seen_tot = []
    by_day = defaultdict(list)
    for g in games:
        by_day[g.game_date].append(g)
    for day in sorted(by_day):
        q3 = sorted(seen_tot)[3 * len(seen_tot) // 4] if len(seen_tot) >= 40 else None
        for g in by_day[day]:
            ln = lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
            hs, tot = ln.get("spread"), ln.get("total")
            ch, ca = ctx(hist[g.home], day, True), ctx(hist[g.away], day, False)
            margin = g.home_score - g.away_score
            nonconf = (g.home in EAST) != (g.away in EAST)
            late = day >= date(start.year + 1, 3, 1)
            if hs is not None:
                for team, me, op, line, home in ((g.home, ch, ca, hs, True), (g.away, ca, ch, -hs, False)):
                    res = (margin if home else -margin) + line
                    if res:
                        rows.append({"season": season, "home": home, "line": line, "me": me, "op": op, "team": team,
                                     "day": day, "total": tot, "first14": (day - start).days < 14,
                                     "opp": g.away if home else g.home, "nonconf": nonconf, "late": late,
                                     "win": res > 0})
            if tot is not None and g.home_score + g.away_score != tot:
                totals.append({"season": season, "hs": hs, "tot": tot, "q3": q3, "h": ch, "a": ca, "day": day,
                               "home": g.home, "away": g.away, "late": late, "first14": (day - start).days < 14,
                               "over": g.home_score + g.away_score > tot})
        for g in by_day[day]:
            ln = lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
            hs = ln.get("spread")
            if ln.get("total") is not None:
                seen_tot.append(ln["total"])
            m = g.home_score - g.away_score
            for team, opp, home, mg, pts in ((g.home, g.away, True, m, g.home_score), (g.away, g.home, False, -m, g.away_score)):
                line = None if hs is None else (hs if home else -hs)
                cv = None if line is None or mg + line == 0 else mg + line > 0
                hist[team].append({"date": day, "won": mg > 0, "margin": mg, "pts": pts, "home": home, "opp": opp,
                                   "ot": (g.periods or 4) > 4, "fav": line is not None and line < 0, "cov": cv,
                                   "line": line, "allowed": pts - mg,
                                   "total": ln.get("total"), "over": None if ln.get("total") is None or
                                   g.home_score + g.away_score == ln["total"] else g.home_score + g.away_score > ln["total"]})
    return rows, totals


# Trends Center trends as general rules (shared with the live Trends tab, engine/trends_live.py)
sub500 = lambda c: c["wp"] is not None and c["n"] >= 5 and c["wp"] < 0.5
over500 = lambda c: c["wp"] is not None and c["n"] >= 5 and c["wp"] > 0.5
L = lambda c: c["last"] or {}

SPREADS_TC = [
    ("Nov 23", "Away team on an 8+ game losing streak vs a sub-.500 opponent", "182-127",
     lambda r: not r["home"] and r["me"]["ls"] >= 8 and sub500(r["op"])),
    ("Nov 24", "Team that scored 90 or less in its last game (their version: Celtics only, 14-0)", "14-0",
     lambda r: L(r["me"]).get("pts", 999) <= 90),
    ("Nov 24", "... and it's the favorite today", "",
     lambda r: L(r["me"]).get("pts", 999) <= 90 and r["line"] < 0),
    ("Nov 21", "Facing a team playing its 5th+ straight home game", "61.2%",
     lambda r: not r["home"] and r["op"]["stretch"] >= 5),
    ("Nov 14", "Facing a team on a back-to-back after an overtime game", "88-37",
     lambda r: r["op"]["b2b"] and L(r["op"]).get("ot")),
    ("Nov 11", "Favorite that lost as the favorite to the same team yesterday", "33-13",
     lambda r: r["line"] < 0 and r["me"]["b2b"] and L(r["me"]).get("opp") == r["opp"]
     and L(r["me"]).get("fav") and not L(r["me"]).get("won")),
    ("Nov 7", "Road favorite after losing its last game as a home favorite", "59.7%",
     lambda r: not r["home"] and r["line"] < 0 and L(r["me"]).get("home") and L(r["me"]).get("fav")
     and not L(r["me"]).get("won")),
    ("Nov 5", "Facing a non-conference team on a back-to-back after an overtime WIN", "39-3",
     lambda r: r["nonconf"] and r["op"]["b2b"] and L(r["op"]).get("ot") and L(r["op"]).get("won")),
    ("Nov 4", "Road favorite on a 3+ game losing streak", "120-62",
     lambda r: not r["home"] and r["line"] < 0 and r["me"]["ls"] >= 3),
    ("Nov 2", "Above-.500 home favorite vs a team on a back-to-back riding a 4+ game win streak", "60.1%",
     lambda r: r["home"] and r["line"] < 0 and over500(r["me"]) and r["op"]["b2b"] and r["op"]["ws"] >= 4),
    ("Oct 29", "Heavy favorite (-9 or more) vs a team on a 4+ game win streak", "260-179",
     lambda r: r["line"] <= -9 and r["op"]["ws"] >= 4),
    ("Mar 24", "Away favorite of 7+ late in the season (March on)", "254-189",
     lambda r: not r["home"] and r["line"] <= -7 and r["late"]),
    ("Mar 4", "Underdog after scoring under 100, vs an above-.500 team", "50-12",
     lambda r: r["line"] > 0 and L(r["me"]).get("pts", 999) < 100 and over500(r["op"])),
    ("Mar 4", "Fade a home underdog playing its 3rd game in 4 nights", "93-37",
     lambda r: not r["home"] and r["line"] < 0 and r["op"]["in4"] >= 3),
    ("Mar 4", "Fade a home team on a back-to-back in its first game back from a 3+ game road trip", "237-147",
     lambda r: not r["home"] and r["op"]["b2b"] and r["op"]["prev_road"] >= 3),
    ("Mar 3", "Home favorite after a loss, vs a sub-.500 team", "45-13",
     lambda r: r["home"] and r["line"] < 0 and L(r["me"]) and not L(r["me"]).get("won") and sub500(r["op"])),
]
TOTALS_TC = [
    ("Oct 31", "UNDER: winless road team (1+ games) vs an above-.500 team", "83-43",
     lambda t: t["a"]["n"] >= 1 and t["a"]["wins"] == 0 and over500(t["h"]), False),
    ("Apr 4", "UNDER: close spread (3 or less) and a high total (top quarter so far)", "319-246",
     lambda t: t["hs"] is not None and abs(t["hs"]) <= 3 and t["q3"] is not None and t["tot"] >= t["q3"], False),
    ("Mar 15", "OVER: heavy favorite (-9+) vs a team on a back-to-back", "392-231",
     lambda t: t["hs"] is not None and ((t["hs"] <= -9 and t["a"]["b2b"]) or (t["hs"] >= 9 and t["h"]["b2b"])), True),
]



def main():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    rows, totals = [], []
    for s in M.SEASONS:
        r, t = build(s, key)
        rows += r
        totals += t
        print(f"{s}: {len(r)} team-games with a closing spread, {len(t)} games with a closing total")
    seasons = list(M.SEASONS)
    def line_for(rs, won):
        w = sum(won(r) for r in rs)
        n = len(rs)
        per = []
        ok = n > 0 and w / n >= 0.56
        for s in seasons:
            sub = [r for r in rs if r["season"] == s]
            sw = sum(won(r) for r in sub)
            per.append(f"{sw}-{len(sub) - sw}")
            if len(sub) >= 5 and sw / len(sub) < 0.53:
                ok = False
        pct = f"{w / n:.1%}" if n else "-"
        return f"{w}-{n - w} ({pct}, {w - 1.1 * (n - w):+.1f}u)", "  ".join(per), ok

    print("\nSPREADS (one row per team per game; we bet the team described)")
    print("seasons: " + "  ".join(s[2:] for s in seasons))
    for when, name, theirs, keep in SPREADS_TC:
        rs = [r for r in rows if keep(r)]
        allr, per, ok = line_for(rs, lambda r: r["win"])
        print(f"  [{when}] {name}\n      theirs: {theirs:10}  ours, 6 seasons: {allr:30} {per}   {'PASSES' if ok else 'fails'}")
    print("\nTOTALS")
    for when, name, theirs, keep, over in TOTALS_TC:
        rs = [t for t in totals if keep(t)]
        allr, per, ok = line_for(rs, (lambda t: t["over"]) if over else (lambda t: not t["over"]))
        print(f"  [{when}] {name}\n      theirs: {theirs:10}  ours, 6 seasons: {allr:30} {per}   {'PASSES' if ok else 'fails'}")


if __name__ == "__main__":
    main()
