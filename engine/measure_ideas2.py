"""THREE MORE IDEAS (Caden 2026-11-11: "since we're starting now, should we try more things"). Two seasons, free.
1. LINE MOVEMENT: the spread moved 2+ / 3+ points from the evening line to the close. Follow the move (bet the side
   the line moved toward) or fade it? Graded at the CLOSE (the price you'd get after the move).
2. OPPONENTS' FREE-THROW LUCK: a defense can't control the other team's free-throw percentage. Each team's
   opponents' FT% over its last 10 games vs the league; a team whose opponents shot lucky from the line looks
   worse than it is -> bet it. Graded at the open and close.
3. REST EDGE: home team with 2+ more days of rest than the visitor (back-to-back visitor included) -> home.
A result counts only if it wins in BOTH seasons.
Run: python -m engine.measure_ideas2
"""
from __future__ import annotations

from collections import defaultdict

from . import backtest_open as BO
from .measure_ideas import ats, rec
from .measure_minutes_spots import load
from .teams import code


def team_ft(js):
    """team -> (FTM, FTA)."""
    out = {}
    for t in (js.get("boxscore") or {}).get("players", []):
        team = code(t["team"]["abbreviation"])
        st = t["statistics"][0]
        keys = st["keys"]
        m = a = 0
        for ath in st.get("athletes", []):
            d = dict(zip(keys, ath.get("stats") or []))
            v = str(d.get("freeThrowsMade-freeThrowsAttempted") or "0-0")
            try:
                x, y = v.split("-")
                m += int(x); a += int(y)
            except ValueError:
                pass
        out[team] = (m, a)
    return out


def season_rows(season):
    games, sums, lines = load(season)
    allowed = defaultdict(list)             # team -> [(opp FTM, opp FTA)] per game
    league = [0, 0]
    last = {}
    out = []
    for g in games:
        js = sums.get(g.id) or {}
        k = f"{g.game_date.isoformat()}|{g.away}|{g.home}"
        ln = lines.get(k) or {}
        row = {"season": season, "margin": g.home_score - g.away_score, "open": ln.get("open"),
               "close": ln.get("close"), "eve": ln.get("eve"), "morn": ln.get("morn")}
        lg = league[0] / league[1] if league[1] > 500 else None
        for side, t in (("h", g.home), ("a", g.away)):
            l10 = allowed[t][-10:]
            m, a = sum(x[0] for x in l10), sum(x[1] for x in l10)
            # free throws above what the league rate would make, per game (opponents' luck vs this team)
            row[f"ftluck_{side}"] = ((m - a * lg) / len(l10)) if lg and len(l10) >= 5 else None
            row[f"rest_{side}"] = (g.game_date - last[t]).days if t in last else None
        out.append(row)
        ft = team_ft(js)
        for t, o in ((g.home, g.away), (g.away, g.home)):
            if o in ft:
                allowed[t].append(ft[o])
                league[0] += ft[o][0]; league[1] += ft[o][1]
            last[t] = g.game_date
    return out


def main():
    data = {s: season_rows(s) for s in BO.SEASONS}

    def first(r):
        return r["eve"] if r.get("eve") is not None else r["open"]
    tests = []
    for cut in (2, 3):
        tests.append((f"1. line moved {cut}+ pts: FOLLOW the move (graded at the close)",
                      lambda r, c=cut: None if first(r) is None or r["close"] is None else
                      ("home" if first(r) - r["close"] >= c else "away" if r["close"] - first(r) >= c else None)))
        tests.append((f"1. line moved {cut}+ pts: FADE the move (graded at the close)",
                      lambda r, c=cut: None if first(r) is None or r["close"] is None else
                      ("away" if first(r) - r["close"] >= c else "home" if r["close"] - first(r) >= c else None)))
    for cut in (1.0, 1.5, 2.0):
        tests.append((f"2. opponents made {cut}+ more FTs a game than league rate (last 10): bet that team",
                      lambda r, c=cut: None if r["ftluck_h"] is None or r["ftluck_a"] is None else
                      ("home" if r["ftluck_h"] - r["ftluck_a"] >= c else "away" if r["ftluck_a"] - r["ftluck_h"] >= c else None)))
    tests.append(("3. home team 2+ more days of rest than the visitor -> home",
                  lambda r: "home" if r["rest_h"] is not None and r["rest_a"] is not None and r["rest_h"] - r["rest_a"] >= 2 else None))
    tests.append(("3. visitor 2+ more days of rest than the home team -> visitor",
                  lambda r: "away" if r["rest_h"] is not None and r["rest_a"] is not None and r["rest_a"] - r["rest_h"] >= 2 else None))
    print(f"{'idea':84} {'season':8} {'at the open':>18} {'at the close':>18}")
    for name, pick in tests:
        for s in list(BO.SEASONS) + ["both"]:
            rows = data[s] if s != "both" else [r for v in data.values() for r in v]
            print(f"{name if s == list(BO.SEASONS)[0] else '':84} {s:8} {rec(ats(rows, pick, 'open')):>18} {rec(ats(rows, pick, 'close')):>18}")


if __name__ == "__main__":
    main()
