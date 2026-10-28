"""Caden 2026-10-28: when a team plays its 3rd game in 4 nights, do stars sit late, so the line moves toward
the rested side after the open? For T2 (and T12, the other rest system) on 2024-25 and 2025-26: how far the
spread moved our way from the open to the close, and the record at the open vs at the close.
Run: python -m engine.measure_tired_clv"""
from __future__ import annotations

from collections import defaultdict

from . import backtest_open as BO
from .measure_moneyball import fetch
from .state import team_state
from .systems import evaluate_tests, label


def main():
    out = defaultdict(lambda: {"moves": [], "open": [0, 0], "close": [0, 0]})
    for season in BO.SEASONS:
        games, days = fetch(season)
        lines, _ = BO.fetch_lines(season, days, "")
        gl = sorted([g for g, _, _ in games], key=lambda g: (g.game_date, str(g.id)))
        finals, by_day = [], defaultdict(list)
        for g in gl:
            by_day[g.game_date].append(g)
        for day in sorted(by_day):
            for g in by_day[day]:
                ln = lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
                op, cl = ln.get("open"), ln.get("close")
                if op is None or cl is None:
                    continue
                hs, as_ = team_state(g.home, finals, day), team_state(g.away, finals, day)
                m = g.home_score - g.away_score
                for p in evaluate_tests(g, hs, as_, op, None):
                    if p.bet != "spread" or p.system not in (102, 112, 101, 103, 104):
                        continue
                    home = p.side == g.home
                    o, c = (op, cl) if home else (-op, -cl)
                    k = (label(p.system), season)
                    out[k]["moves"].append(c - o if False else o - c)    # + = the line moved toward our side
                    for key, ln_ in (("open", o), ("close", c)):
                        r = (m if home else -m) + ln_
                        if r:
                            out[k][key][0 if r > 0 else 1] += 1
            finals += by_day[day]
    for tag in ("T2", "T12", "T1", "T3", "T4"):
        for season in BO.SEASONS:
            d = out.get((tag, season))
            if not d or not d["moves"]:
                continue
            mv = d["moves"]
            toward = sum(1 for x in mv if x > 0); against = sum(1 for x in mv if x < 0)
            o, c = d["open"], d["close"]
            print(f"{tag:4} {season}: {len(mv)} picks | line moved our way {sum(mv)/len(mv):+.2f} pts on average "
                  f"({toward} toward us, {against} against, {len(mv)-toward-against} no move) | "
                  f"at the open {o[0]}-{o[1]} ({o[0]/max(sum(o),1):.1%}) vs at the close {c[0]}-{c[1]} ({c[0]/max(sum(c),1):.1%})")


if __name__ == "__main__":
    main()
