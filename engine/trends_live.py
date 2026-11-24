"""TRENDS TAB (Caden 2026-11-24): paper only, kept apart from the bets and the record.

Every Trends Center NBA trend from their X posts (as general rules, engine/measure_trends.py), plus our own, each with
their claimed record, our 6-season check at the closing line, and a live record from Nov 24 on. A trend "fires" on a
game side the first time we see it qualify before tip; it is graded at the line it fired on (spreads at -110,
totals over/under). Nothing here is ever bet.
State: bet_state "trends_fired" {trend|game|side: {...}}.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from . import measure_trends as T

# Caden 2026-11-24: a game side with 2+ spread trends and none on the other side. Paper only: 56.4% over 6 seasons
# but 2020-21 (52%) and 2024-25 (49.5%) miss the bar. The nested "... and it's the favorite" and the line-move trend
# don't count toward it (the first double-counts "scored 90 or less"; the second has no 6-season test).
STACK = "STACK: 2+ trends on one side, none on the other"
NOT_IN_STACK = {"... and it's the favorite today"}

# our 6-season check (engine.measure_trends, 2020-21 to 2025-26, closing line), shown next to theirs
OURS_6 = {
    "Away team on an 8+ game losing streak vs a sub-.500 opponent": ("32-32", "5-7 3-4 4-10 8-3 5-1 7-7"),
    "Team that scored 90 or less in its last game (their version: Celtics only, 14-0)": ("227-198", "42-37 68-57 27-13 31-31 33-38 26-22"),
    "... and it's the favorite today": ("84-57", "19-11 20-17 12-4 14-8 9-12 10-5"),
    "Facing a team playing its 5th+ straight home game": ("239-220", "36-35 35-35 44-32 53-41 40-44 31-33"),
    "Facing a team on a back-to-back after an overtime game": ("69-56", "10-10 16-9 10-8 13-4 13-11 7-14"),
    "Favorite that lost as the favorite to the same team yesterday": ("15-4", "6-2 1-0 1-0 2-1 2-1 3-0"),
    "Road favorite after losing its last game as a home favorite": ("115-101", "17-11 20-20 13-12 23-16 23-22 19-20"),
    "Facing a non-conference team on a back-to-back after an overtime WIN": ("14-6", "2-1 6-1 1-1 2-1 2-2 1-0"),
    "Road favorite on a 3+ game losing streak": ("101-80", "22-18 15-7 15-11 14-10 13-20 22-14"),
    "Above-.500 home favorite vs a team on a back-to-back riding a 4+ game win streak": ("25-17", "4-1 5-5 7-1 4-3 1-2 4-5"),
    "Heavy favorite (-9 or more) vs a team on a 4+ game win streak": ("18-11", "1-0 3-0 3-3 3-2 4-4 4-2"),
    "Away favorite of 7+ late in the season (March on)": ("188-144", "44-33 20-21 20-12 37-27 34-19 33-32"),
    "Underdog after scoring under 100, vs an above-.500 team": ("355-336", "59-63 97-72 28-38 59-62 59-63 53-38"),
    "Fade a home underdog playing its 3rd game in 4 nights": ("398-384", "75-81 63-43 65-50 63-59 55-72 77-79"),
    "Fade a home team on a back-to-back in its first game back from a 3+ game road trip": ("51-53", "10-7 8-12 9-9 10-5 9-11 5-9"),
    "Home favorite after a loss, vs a sub-.500 team": ("512-484", "85-70 85-83 78-87 75-82 86-82 103-80"),
    "UNDER: winless road team (1+ games) vs an above-.500 team": ("2-0", "0-0 0-0 1-0 0-0 0-0 1-0"),
    "UNDER: close spread (3 or less) and a high total (top quarter so far)": ("283-231", "47-34 58-47 76-46 42-44 34-40 26-20"),
    "OVER: heavy favorite (-9+) vs a team on a back-to-back": ("244-213", "40-25 35-33 29-35 40-42 52-43 48-35"),
    "Home team on an 8+ game losing streak vs a sub-.500 opponent": ("38-27", "3-7 4-3 4-3 10-6 9-3 8-5"),
    "Line moved 2.5+ toward the team since the first line we saw": ("194-148", "2 seasons only: 98-83 96-65"),
    STACK: ("306-237", "51-47 60-38 42-23 44-33 50-51 59-45"),
}

_sub500 = lambda c: c["wp"] is not None and c["n"] >= 5 and c["wp"] < 0.5

# (name, source, their record, kind, over?, rule)
OURS = [("Home team on an 8+ game losing streak vs a sub-.500 opponent", "Ours (from their losing-streak trend)", "",
         "spread", None, lambda r: r["home"] and r["me"]["ls"] >= 8 and _sub500(r["op"])),
        # bet at the moved (current) line, not the first one
        ("Line moved 2.5+ toward the team since the first line we saw", "Ours (line-movement research)", "",
         "spread", None, lambda r: r.get("move") is not None and r["move"] >= 2.5)]
AT_CURRENT = {"Line moved 2.5+ toward the team since the first line we saw"}


def trends():
    out = []
    for when, name, theirs, keep in T.SPREADS_TC:
        out.append((name, f"Trends Center ({when})", theirs, "spread", None, keep))
    for when, name, theirs, keep, over in T.TOTALS_TC:
        out.append((name, f"Trends Center ({when})", theirs, "total", over, keep))
    return out + OURS


def _hist(finals, stored):
    hist = defaultdict(list)
    for g in sorted(finals, key=lambda x: (x.game_date, str(x.id))):
        row = stored.get(g.id) or stored.get(str(g.id)) or {}
        hs, tot = row.get("home_spread"), row.get("total")
        m = g.home_score - g.away_score
        pts = g.home_score + g.away_score
        for team, opp, home, mg, own in ((g.home, g.away, True, m, g.home_score), (g.away, g.home, False, -m, g.away_score)):
            line = None if hs is None else (hs if home else -hs)
            hist[team].append({"date": g.game_date, "won": mg > 0, "margin": mg, "pts": own, "home": home, "opp": opp,
                               "ot": (g.periods or 4) > 4, "fav": line is not None and line < 0, "line": line,
                               "cov": None if line is None or mg + line == 0 else mg + line > 0, "allowed": own - mg,
                               "total": tot, "over": None if tot is None or pts == tot else pts > tot})
    return hist


def evaluate(finals, stored, upcoming, lines, season_start: date):
    """lines: game id -> (first home spread, first total[, current home spread]). Trends are judged at the first
    line; AT_CURRENT ones at the current line. Returns [(trend name, game, side, line)]."""
    hist = _hist(finals, stored)
    tots = sorted(r.get("total") for gid, r in stored.items() if r.get("final") and r.get("total") is not None)
    q3 = tots[3 * len(tots) // 4] if len(tots) >= 40 else None
    fired = []
    for g in upcoming:
        hs, tot, *rest = lines.get(g.id, (None, None))
        cur = rest[0] if rest else None
        day = g.game_date
        ch, ca = T.ctx(hist[g.home], day, True), T.ctx(hist[g.away], day, False)
        late = day >= date(season_start.year + 1, 3, 1)
        first14 = (day - season_start).days < 14
        nonconf = (g.home in T.EAST) != (g.away in T.EAST)
        sides = []
        if hs is not None:
            for team, me, op, line, home in ((g.home, ch, ca, hs, True), (g.away, ca, ch, -hs, False)):
                cl = None if cur is None else (cur if home else -cur)
                sides.append({"home": home, "line": line, "me": me, "op": op, "team": team, "cur": cl,
                              "move": None if cl is None else line - cl,      # + = moved toward this team
                              "opp": g.away if home else g.home, "nonconf": nonconf, "late": late, "day": day,
                              "total": tot, "first14": first14})
        t_row = None if tot is None else {"hs": hs, "tot": tot, "q3": q3, "h": ch, "a": ca, "day": day, "late": late,
                                          "first14": first14, "home": g.home, "away": g.away}
        for name, _src, _th, kind, over, keep in trends():
            try:
                if kind == "spread":
                    for r in sides:
                        if keep(r):
                            fired.append((name, g, r["team"], r["cur"] if name in AT_CURRENT else r["line"]))
                elif t_row is not None and keep(t_row):
                    fired.append((name, g, "OVER" if over else "UNDER", tot))
            except Exception:
                continue
    return fired


def grade(e: dict, g) -> str | None:
    if not g or not g.final:
        return None
    m = g.home_score - g.away_score
    if e["kind"] == "total":
        pts = g.home_score + g.away_score
        if pts == e["line"]:
            return "P"
        return "W" if (pts > e["line"]) == (e["side"] == "OVER") else "L"
    res = (m if e["side"] == g.home else -m) + e["line"]
    return "P" if res == 0 else ("W" if res > 0 else "L")


def run(store, now: datetime, finals, stored, upcoming, lines, season_start: date, games_by_id: dict) -> dict:
    state = (store.load_state(["trends_fired"]).get("trends_fired") or {}) if hasattr(store, "load_state") else {}
    kinds = {name: kind for name, _s, _t, kind, _o, _k in trends()}
    kinds[STACK] = "spread"
    fired = evaluate(finals, stored, upcoming, lines, season_start)
    per = defaultdict(lambda: defaultdict(set))           # game id -> side -> spread trends (stack-eligible)
    for name, g, side, line in fired:
        if kinds[name] == "spread" and name not in NOT_IN_STACK and name not in AT_CURRENT:
            per[g.id][side].add(name)
    stacks = []
    for name, g, side, line in fired:
        sides = per.get(g.id, {})
        if (name not in NOT_IN_STACK and name not in AT_CURRENT and len(sides.get(side, ())) >= 2
                and not any(v for k, v in sides.items() if k != side)):
            stacks.append((STACK, g, side, line))
    for name, g, side, line in fired + stacks:
        k = f"{name}|{g.id}|{side}"
        if k not in state:
            state[k] = {"trend": name, "game_id": str(g.id), "side": side, "line": line, "kind": kinds[name],
                        "fired_at": now.isoformat(), "game": f"{g.away} @ {g.home}", "date": g.game_date.isoformat()}
    for e in state.values():
        if not e.get("result"):
            r = grade(e, games_by_id.get(e["game_id"]))
            if r:
                e["result"] = r
    if hasattr(store, "save_state"):
        store.save_state({"trends_fired": state})
    out = []
    for name, src, theirs, kind, over, _k in [(STACK, "Ours (Caden's stack rule)", "", "spread", None, None)] + trends():
        es = [e for e in state.values() if e["trend"] == name]
        w = sum(e.get("result") == "W" for e in es)
        l = sum(e.get("result") == "L" for e in es)
        ours = OURS_6.get(name, ("", ""))
        today = [{"game": e["game"], "side": e["side"], "line": e["line"], "date": e["date"]}
                 for e in es if not e.get("result")]
        recent = sorted((e for e in es if e.get("result")), key=lambda e: e["date"], reverse=True)[:10]
        out.append({"name": name, "source": src, "theirs": theirs, "kind": kind, "ours": ours[0], "ours_seasons": ours[1],
                    "live": {"w": w, "l": l, "p": sum(e.get("result") == "P" for e in es), "units": round(w - 1.1 * l, 1)},
                    "open": today, "recent": [{"game": e["game"], "side": e["side"], "line": e["line"],
                                                "date": e["date"], "result": e["result"]} for e in recent]})
    return {"trends": out, "since": "2026-11-24"}
