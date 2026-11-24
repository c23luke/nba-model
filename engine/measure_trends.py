"""TRENDS (Caden 2026-11-24): check Trends Center-style NBA trends on our own data, 6 seasons at the closing line.

First trend (Trends Center, Nov 23, claimed 182-127-5 ATS over 31 years, "active on Bucks +10.5 at Raptors"):
  away team on an 8+ game losing streak vs an opponent under .500 for the season at the time of the game.
Also the same idea at other streak lengths, home vs away, any opponent, and as a big underdog, so we can see whether
the 8+ cut is the real shape or a lucky slice. Graded vs the closing line (Odds API consensus, -110), one row per
team per game, each season shown. Only earlier games count toward a streak or a record.
Run: python -m engine.measure_trends
"""
from __future__ import annotations

import os
from collections import defaultdict

from . import mine as M


def rows_for(season, key):
    games, start, end, days = M.games_for(season)
    lines, _ = M.closing_lines(season, days, key)
    hist = defaultdict(list)                     # team -> [won, ...] in date order
    out = []
    by_day = defaultdict(list)
    for g in games:
        by_day[g.game_date].append(g)
    for day in sorted(by_day):
        for g in by_day[day]:
            hs = (lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}).get("spread")
            if hs is None:
                continue
            margin = g.home_score - g.away_score
            for team, opp, home in ((g.home, g.away, True), (g.away, g.home, False)):
                line = hs if home else -hs
                res = (margin if home else -margin) + line
                if res == 0:
                    continue
                h, o = hist[team], hist[opp]
                ls = 0
                for w in reversed(h):
                    if w:
                        break
                    ls += 1
                ws = 0
                for w in reversed(h):
                    if not w:
                        break
                    ws += 1
                opp_wp = sum(o) / len(o) if o else None
                out.append({"season": season, "home": home, "lstreak": ls, "wstreak": ws, "line": line,
                            "opp_wp": opp_wp, "opp_n": len(o), "win": res > 0})
        for g in by_day[day]:
            m = g.home_score - g.away_score
            hist[g.home].append(m > 0)
            hist[g.away].append(m < 0)
    return out


def rec(rs):
    w = sum(r["win"] for r in rs)
    n = len(rs)
    return f"{w}-{n - w}" + (f" ({w / n:.1%}, {w - 1.1 * (n - w):+.1f}u)" if n else "")


def main():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    rows = []
    for s in M.SEASONS:
        r = rows_for(s, key)
        rows += r
        print(f"{s}: {len(r)} team-games with a closing spread")
    seasons = list(M.SEASONS)

    def show(label, keep):
        sub = [r for r in rows if keep(r)]
        per = "  ".join(f"{s[2:]}: {sum(r['win'] for r in sub if r['season'] == s)}-"
                        f"{sum(not r['win'] for r in sub if r['season'] == s)}" for s in seasons)
        print(f"  {label:66} ALL: {rec(sub):>26}   {per}")

    sub500 = lambda r: r["opp_wp"] is not None and r["opp_n"] >= 1 and r["opp_wp"] < 0.5
    print("\n=== TRENDS CENTER: away team on an 8+ game losing streak vs a sub-.500 opponent (their claim 182-127-5)")
    show("away, lost 8+ in a row, opponent under .500", lambda r: not r["home"] and r["lstreak"] >= 8 and sub500(r))
    print("\n=== Same idea, other cuts (is 8+ the real shape or a lucky slice?)")
    for k in (3, 4, 5, 6, 7, 8, 10):
        show(f"away, lost {k}+ in a row, opponent under .500", lambda r, k=k: not r["home"] and r["lstreak"] >= k and sub500(r))
    for k in (5, 8):
        show(f"home, lost {k}+ in a row, opponent under .500", lambda r, k=k: r["home"] and r["lstreak"] >= k and sub500(r))
        show(f"any, lost {k}+ in a row, any opponent", lambda r, k=k: r["lstreak"] >= k)
        show(f"away, lost {k}+ in a row, opponent .500 or better", lambda r, k=k: not r["home"] and r["lstreak"] >= k
             and r["opp_wp"] is not None and r["opp_wp"] >= 0.5)
        show(f"away, lost {k}+ in a row, opponent under .500, getting 10+", lambda r, k=k: not r["home"] and r["lstreak"] >= k
             and sub500(r) and r["line"] >= 10)
        show(f"away, lost {k}+ in a row, opponent under .500, getting under 10", lambda r, k=k: not r["home"] and r["lstreak"] >= k
             and sub500(r) and r["line"] < 10)
    print("\nPer season, for the Trends Center trend:")
    tc = [r for r in rows if not r["home"] and r["lstreak"] >= 8 and sub500(r)]
    for s in seasons:
        print(f"  {s}: {rec([r for r in tc if r['season'] == s])}")


if __name__ == "__main__":
    main()
