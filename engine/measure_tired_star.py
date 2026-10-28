"""Caden 2026-10-28: tired teams rest stars late, so lines move toward the rested side after the open.
Two questions, replayed on 2024-25 and 2025-26 (choose on the first season, check on the second):

A) WHEN to bet: for T2 / T12, the record and line move from the night-before line (eve), the morning line
   (morn) and the close. If the eve number is better, the bettor should take it the night before.
B) A wider net: bet against a TIRED team (back-to-back, 3rd game in 4 nights, or 4th in 6) when the other
   team is NOT tired, split by whether the tired team has a STAR. Star = a player averaging 28+ minutes for
   that team in its games so far this season whose own previous-season BPM was 4+ (his number, wherever he
   played). Reports: record at the open and the close, line move, and how often the star sat.
Run: python -m engine.measure_tired_star
"""
from __future__ import annotations

import csv
from collections import defaultdict

from . import backtest_open as BO
from . import personnel as P
from .measure_moneyball import fetch
from .state import team_state
from .systems import evaluate_tests, label

PRIOR = {"2024-25": "players_2023_24.csv", "2025-26": "players_2024_25.csv"}


def prior_bpm(season):
    out = {}
    with open(P.STATIC / PRIOR[season]) as f:
        for r in csv.DictReader(f, delimiter=";"):
            try:
                if float(r["mp"]) >= 800:
                    out[P.norm(r["name"])] = float(r["bpm"])
            except (ValueError, KeyError):
                pass
    return out


def fmt(w, l):
    return f"{w}-{l} ({w / max(w + l, 1):.1%}, {w - 1.1 * l:+.1f}u)"


def main():
    res = defaultdict(lambda: {"move": [], "open": [0, 0], "close": [0, 0], "eve": [0, 0], "morn": [0, 0],
                               "move_eve": [], "star_sat": [0, 0]})
    for season in BO.SEASONS:
        games, days = fetch(season)
        lines, _ = BO.fetch_lines(season, days, "")
        bpm = prior_bpm(season)
        box = {str(g.id): rows for g, rows, _ in games}
        gl = sorted([g for g, _, _ in games], key=lambda g: (g.game_date, str(g.id)))
        finals, by_day = [], defaultdict(list)
        for g in gl:
            by_day[g.game_date].append(g)
        mins = defaultdict(lambda: defaultdict(list))        # team -> player -> minutes per team game so far
        team_games = defaultdict(int)

        def stars(team):
            n = team_games[team]
            if n < 3:
                return []
            return [name for name, m in mins[team].items()
                    if sum(m) / n >= 28 and bpm.get(P.norm(name), -99) >= 4]

        def tired(team, day):
            ago = [(day - x.game_date).days for x in finals if team in (x.home, x.away) and 1 <= (day - x.game_date).days <= 5]
            b2b = 1 in ago
            t34 = sum(1 for a in ago if a <= 3) >= 2
            f46 = len(ago) >= 3
            return b2b or t34 or f46

        for day in sorted(by_day):
            for g in by_day[day]:
                ln = lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
                op, cl = ln.get("open"), ln.get("close")
                if op is None or cl is None:
                    continue
                m = g.home_score - g.away_score
                played = {r["name"] for r in box.get(str(g.id), []) if r.get("min")}

                def grade(side_home, line_home):
                    if line_home is None:
                        return None
                    r = (m + line_home) if side_home else (-m - line_home)
                    return None if r == 0 else r > 0

                def add(key, side_home, star_list=None):
                    d = res[key]
                    for k, l in (("open", op), ("close", cl), ("eve", ln.get("eve")), ("morn", ln.get("morn"))):
                        w = grade(side_home, l)
                        if w is not None:
                            d[k][0 if w else 1] += 1
                    d["move"].append((op - cl) if side_home else (cl - op))
                    if ln.get("eve") is not None:
                        d["move_eve"].append((ln["eve"] - cl) if side_home else (cl - ln["eve"]))
                    if star_list:
                        sat = any(s not in played for s in star_list)
                        d["star_sat"][0 if sat else 1] += 1

                hs, as_ = team_state(g.home, finals, day), team_state(g.away, finals, day)
                for p in evaluate_tests(g, hs, as_, op, None):
                    if p.bet == "spread" and p.system in (102, 112):
                        add((label(p.system), season), p.side == g.home)
                th, ta = tired(g.home, day), tired(g.away, day)
                if th != ta:
                    tired_team = g.home if th else g.away
                    st = stars(tired_team)
                    add(("vs tired team, it has a star" if st else "vs tired team, no star", season), not th, st)
            for g in by_day[day]:
                rows = box.get(str(g.id), [])
                for t in (g.home, g.away):
                    team_games[t] += 1
                    for r in rows:
                        if r.get("team") == t:
                            mins[t][r["name"]].append(r.get("min") or 0)
                    for name in mins[t]:
                        if len(mins[t][name]) < team_games[t]:
                            mins[t][name] += [0] * (team_games[t] - len(mins[t][name]))
            finals += by_day[day]

    keys = sorted({k for k, _ in res})
    for k in keys:
        print(f"\n=== {k}")
        for season in BO.SEASONS:
            d = res.get((k, season))
            if not d or not d["move"]:
                continue
            mv, me = d["move"], d["move_eve"]
            ss = d["star_sat"]
            print(f"  {season}: {len(mv)} bets | open {fmt(*d['open'])} | close {fmt(*d['close'])} | "
                  f"night-before {fmt(*d['eve'])} | morning {fmt(*d['morn'])}")
            print(f"           line moved our way: open→close {sum(mv)/len(mv):+.2f} pts ({sum(x > 0 for x in mv)} toward, "
                  f"{sum(x < 0 for x in mv)} against); night-before→close {sum(me)/max(len(me),1):+.2f}"
                  + (f" | star sat {ss[0]} of {sum(ss)} ({ss[0]/max(sum(ss),1):.0%})" if sum(ss) else ""))


if __name__ == "__main__":
    main()
