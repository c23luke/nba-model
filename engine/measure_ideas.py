"""FOUR IDEAS NOBODY PRICES WELL (Caden 2026-11-11: "think outside the box ... ideas no one is thinking about").
Two seasons (2024-25, 2025-26), every game with an open and a close line. Free: ESPN game summaries + saved lines.

1. REFEREE CREWS (totals). ESPN lists the officials. Each referee's tendency = how far games he worked went over/
   under the closing total, before tonight (5+ games, shrunk toward 0 with 10 games of weight). Crew = average of
   its referees. Big over-crews / under-crews -> over / under at the close (and open).
2. SHOOTING LUCK (spreads and totals). From shot locations: each team's field-goal points minus what its shots were
   worth at league rates, over its last 5 games. A team that's run hot gets priced up; fade it. Totals: both teams
   hot -> under; both cold -> over.
3. HIDDEN FATIGUE (spreads). The team's last game went to overtime, or its top player played 40+ minutes, and
   tonight is a back-to-back -> bet the opponent.
4. BLOWOUT OVERREACTION (spreads). The team's last game was decided by 25+.
Every result at the OPEN and at the CLOSE, per season. Only what wins in both seasons counts.
Run: python -m engine.measure_ideas
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import backtest_open as BO
from . import personnel as P
from .measure_minutes_spots import load
from .prop_model import ZONES, shot_list
from .teams import code


def rec(xs):
    w = sum(x > 0 for x in xs); l = sum(x < 0 for x in xs)
    return f"{w}-{l} ({w / (w + l):.1%})" if w + l else "-"


def officials(js):
    return [o.get("fullName") or (o.get("displayName")) for o in (js.get("gameInfo") or {}).get("officials") or []
            if (o.get("fullName") or o.get("displayName"))]


def team_box(js):
    """team -> (minutes of the top player, team minutes total)."""
    out = {}
    for t in (js.get("boxscore") or {}).get("players", []):
        team = code(t["team"]["abbreviation"])
        st = t["statistics"][0]
        keys = st["keys"]
        mins = []
        for a in st.get("athletes", []):
            d = dict(zip(keys, a.get("stats") or []))
            try:
                mins.append(0 if a.get("didNotPlay") else int(str(d.get("minutes") or "0").split(":")[0] or 0))
            except ValueError:
                mins.append(0)
        out[team] = (max(mins) if mins else 0, sum(mins))
    return out


def season_rows(season):
    games, sums, lines = load(season)
    totals = json.loads((P.STATIC / f"odds_totals_{season.replace('-', '_')}.json").read_text())
    ref_hist = defaultdict(list)            # referee -> [actual total - closing total]
    luck = defaultdict(list)                # team -> [FG points above expected] per game
    last = {}                               # team -> {"date", "ot", "top_min", "margin"}
    zl = {z: [0, 0] for z in ZONES}         # league zone [attempts, points], running
    out = []
    for g in games:
        js = sums.get(g.id) or {}
        k = f"{g.game_date.isoformat()}|{g.away}|{g.home}"
        ln, tt = lines.get(k) or {}, totals.get(k) or {}
        refs = officials(js)
        shots = shot_list(js)
        tb = team_box(js)
        row = {"season": season, "date": g.game_date.isoformat(), "home": g.home, "away": g.away,
               "margin": g.home_score - g.away_score, "pts": g.home_score + g.away_score,
               "open": ln.get("open"), "close": ln.get("close"), "t_open": tt.get("open"), "t_close": tt.get("close")}
        # 1. referees (before tonight)
        vals = []
        for r in refs:
            h = ref_hist[r]
            if len(h) >= 5:
                vals.append(sum(h) / (len(h) + 10))
        row["crew"] = sum(vals) / len(vals) if len(vals) >= 2 else None
        # 2. shooting luck over the last 5 games (before tonight)
        for side, t in (("h", g.home), ("a", g.away)):
            l5 = luck[t][-5:]
            row[f"luck_{side}"] = sum(l5) / len(l5) if len(l5) >= 3 else None
            p = last.get(t)
            row[f"b2b_{side}"] = bool(p and (g.game_date - p["date"]).days == 1)
            row[f"ot_{side}"] = bool(p and p["ot"])
            row[f"heavy_{side}"] = bool(p and p["top_min"] >= 40)
            row[f"prev_margin_{side}"] = p["margin"] if p else None
        out.append(row)
        # ---- update with tonight
        if row["t_close"] is not None:
            for r in refs:
                ref_hist[r].append(row["pts"] - row["t_close"])
        L = {z: (v[1] / v[0] if v[0] else 0) for z, v in zl.items()}
        per = defaultdict(lambda: [0.0, 0.0])
        for team, _, z, pts in shots:
            per[team][0] += pts
            per[team][1] += L[z]
        for team, (act, exp) in per.items():
            if sum(v[0] for v in zl.values()) > 2000:
                luck[team].append(act - exp)
        for team, _, z, pts in shots:
            zl[z][0] += 1; zl[z][1] += pts
        for t in (g.home, g.away):
            top, tot = tb.get(t, (0, 240))
            mg = row["margin"] if t == g.home else -row["margin"]
            last[t] = {"date": g.game_date, "ot": tot > 245 or (g.periods or 4) > 4, "top_min": top, "margin": mg}
    return out


def ats(rows, pick, when):
    """pick(row) -> 'home' / 'away' / None. Result of that side against the open or close."""
    xs = []
    for r in rows:
        s = pick(r)
        line = r[when]
        if s is None or line is None:
            continue
        m = r["margin"] + line
        xs.append(m if s == "home" else -m)
    return xs


def ou(rows, pick, when):
    xs = []
    for r in rows:
        s = pick(r)
        t = r["t_" + when]
        if s is None or t is None:
            continue
        d = r["pts"] - t
        xs.append(d if s == "over" else -d)
    return xs


def main():
    data = {s: season_rows(s) for s in BO.SEASONS}
    tests = []
    for cut in (1.5, 2.5, 3.5):
        tests.append((f"1. referee crew {cut}+ pts over-leaning -> over", "ou",
                      lambda r, c=cut: "over" if r["crew"] is not None and r["crew"] >= c else None))
        tests.append((f"1. referee crew {cut}+ pts under-leaning -> under", "ou",
                      lambda r, c=cut: "under" if r["crew"] is not None and r["crew"] <= -c else None))
    for cut in (4, 6, 8):
        tests.append((f"2. fade the team that shot {cut}+ pts/game hotter than its shots (last 5)", "ats",
                      lambda r, c=cut: ("away" if (r["luck_h"] or 0) - (r["luck_a"] or 0) >= c else
                                        "home" if (r["luck_a"] or 0) - (r["luck_h"] or 0) >= c else None)
                      if r["luck_h"] is not None and r["luck_a"] is not None else None))
        tests.append((f"2. both teams {cut / 2:g}+ hot (last 5) -> under", "ou",
                      lambda r, c=cut: "under" if r["luck_h"] is not None and r["luck_a"] is not None
                      and r["luck_h"] >= c / 2 and r["luck_a"] >= c / 2 else None))
        tests.append((f"2. both teams {cut / 2:g}+ cold (last 5) -> over", "ou",
                      lambda r, c=cut: "over" if r["luck_h"] is not None and r["luck_a"] is not None
                      and r["luck_h"] <= -c / 2 and r["luck_a"] <= -c / 2 else None))
    tests += [
        ("3. back-to-back after an OVERTIME game -> bet the opponent", "ats",
         lambda r: "away" if r["b2b_h"] and r["ot_h"] and not (r["b2b_a"] and r["ot_a"]) else
         "home" if r["b2b_a"] and r["ot_a"] and not (r["b2b_h"] and r["ot_h"]) else None),
        ("3. back-to-back after its top player played 40+ -> bet the opponent", "ats",
         lambda r: "away" if r["b2b_h"] and r["heavy_h"] and not (r["b2b_a"] and r["heavy_a"]) else
         "home" if r["b2b_a"] and r["heavy_a"] and not (r["b2b_h"] and r["heavy_h"]) else None),
        ("3. any game after an OVERTIME game -> bet the opponent", "ats",
         lambda r: "away" if r["ot_h"] and not r["ot_a"] else "home" if r["ot_a"] and not r["ot_h"] else None),
        ("4. team LOST its last game by 25+ -> bet that team", "ats",
         lambda r: "home" if (r["prev_margin_h"] or 0) <= -25 else "away" if (r["prev_margin_a"] or 0) <= -25 else None),
        ("4. team WON its last game by 25+ -> bet against it", "ats",
         lambda r: "away" if (r["prev_margin_h"] or 0) >= 25 else "home" if (r["prev_margin_a"] or 0) >= 25 else None),
    ]
    print(f"{'idea':74} {'season':8} {'at the open':>18} {'at the close':>18}")
    for name, kind, pick in tests:
        f = ats if kind == "ats" else ou
        for s in list(BO.SEASONS) + ["both"]:
            rows = data[s] if s != "both" else [r for v in data.values() for r in v]
            o, c = f(rows, pick, "open" if kind == "ats" else "open"), f(rows, pick, "close")
            print(f"{name if s == list(BO.SEASONS)[0] else '':74} {s:8} {rec(o):>18} {rec(c):>18}")
    # how many refs we saw (sanity)
    n_crew = sum(1 for v in data.values() for r in v if r["crew"] is not None)
    print(f"\ngames with a referee crew rating: {n_crew}; with shooting luck: "
          f"{sum(1 for v in data.values() for r in v if r['luck_h'] is not None)}")


if __name__ == "__main__":
    main()
