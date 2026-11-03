"""Is the edge real or did the replay peek? Same replay as engine.measure_stacks (picks chosen at the OPENING
line), graded twice: at the opening line and at the CLOSING line. The replay knows who actually played each game,
and injury news after the open moves the line. If an edge is mostly that news, it shows at the open and vanishes
at the close (where the news is priced in). An edge that holds at the close is the model's own.
Run: python -m engine.measure_leak"""
from __future__ import annotations

import json
from collections import defaultdict

from . import backtest_open as BO
from . import personnel as P
from .measure_moneyball import corrected, fetch, luck_table
from .measure_personnel_upgrades import LIVE
from .state import team_state
from .systems import evaluate, evaluate_early, evaluate_tests, group, label


def season_rows_close(season):
    games, days = fetch(season)
    lines, _ = BO.fetch_lines(season, days, "")
    totals = json.loads((P.STATIC / f"odds_totals_{season.replace('-', '_')}.json").read_text())
    preds, _ = BO.replay(season, [(g, r) for g, r, _ in games], lines)
    rows = corrected(preds[LIVE], luck_table(games), K=5, opp3=True)
    cal = {(r["date"], r["away"], r["home"]): r["gap"] for r in BO.calibrate_open(rows)}
    start = BO.SEASONS[season]["start"]
    gl = sorted([g for g, _, _ in games], key=lambda g: (g.game_date, str(g.id)))
    by_day = defaultdict(list)
    for g in gl:
        by_day[g.game_date].append(g)
    finals, out, played_tot = [], [], []
    for day in sorted(by_day):
        tot_avg = sum(played_tot) / len(played_tot) if len(played_tot) >= 30 else None     # S4's bar, as live
        for g in by_day[day]:
            k = f"{day.isoformat()}|{g.away}|{g.home}"
            op = (lines.get(k) or {}).get("open")
            cl = (lines.get(k) or {}).get("close")
            ct = (totals.get(k) or {}).get("close")
            ot = (totals.get(k) or {}).get("open")
            if op is None and ot is None:
                continue
            hs, as_ = team_state(g.home, finals, day), team_state(g.away, finals, day)
            picks = (evaluate(g, hs, as_, op, ot, tot_avg) + evaluate_tests(g, hs, as_, op, ot)
                     + evaluate_early(g, hs, as_, op, ot, (day - start).days))
            gap = cal.get((day, g.away, g.home))
            if gap is not None and op is not None and abs(gap) >= 3:
                from .systems import Pick
                picks.append(Pick(113, g.id, "spread", g.home if gap > 0 else g.away,
                                  op if gap > 0 else -op))
            for p in picks:
                if p.line is None or p.system >= 300:
                    continue
                rc = None
                if p.bet == "spread":
                    m = g.home_score - g.away_score
                    r = (m + p.line) if p.side == g.home else (-m + p.line)
                    if cl is not None:
                        rc = (m + cl) if p.side == g.home else (-m - cl)
                    gos = None if gap is None else (gap if p.side == g.home else -gap)
                else:
                    t = g.home_score + g.away_score
                    r = (t - p.line) if p.side == "OVER" else (p.line - t)
                    gos = None
                    if ct is not None:
                        rc = (t - ct) if p.side == "OVER" else (ct - t)
                res = "W" if r > 0 else "L" if r < 0 else "P"
                out.append({"game": g.id, "bet": p.bet, "side": p.side, "system": p.system, "res": res, "gap": gos,
                            "resc": None if rc is None else "W" if rc > 0 else "L" if rc < 0 else "P"})
            if gap is not None and op is not None:
                m = g.home_score - g.away_score
                side_home = gap > 0
                r = (m + op) if side_home else (-m - op)
                rc = None if cl is None else ((m + cl) if side_home else (-m - cl))
                out.append({"game": g.id, "bet": "x1", "side": None, "system": 301,
                            "res": "W" if r > 0 else "L" if r < 0 else "P", "gap": abs(gap),
                            "resc": None if rc is None else "W" if rc > 0 else "L" if rc < 0 else "P"})
        finals += by_day[day]
        played_tot += [(totals.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}).get("close") for g in by_day[day]]
        played_tot = [x for x in played_tot if x is not None]
    return out




def rec(rs):
    rs = [r for r in rs if r]
    w, l = rs.count("W"), rs.count("L")
    return f"{w}-{l} ({w / (w + l):.1%})" if w + l else "-"


allrows: list = []


def main():
    for season in list(BO.SEASONS) + ["both"]:
        if season == "both":
            rows = allrows
        else:
            rows = season_rows_close(season)
            allrows.extend(rows)
        cats = defaultdict(lambda: ([], []))
        def add(k, r):
            cats[k][0].append(r["res"]); cats[k][1].append(r["resc"])
        stacks = defaultdict(list)
        for r in rows:
            if r["system"] == 301:
                if 3 <= r["gap"] < 4: add("players model gap 3-4", r)
                if r["gap"] >= 4: add("players model gap 4+ (T13)", r)
                continue
            if r["system"] == 113:
                continue
            if r["system"] == 4: add("S4 (total above season avg)", r)
            if r["bet"] == "spread":
                add("any spread system, all", r)
                if r["gap"] is not None:
                    stacks[(r["game"], r["side"])].append(r)
        for ps in stacks.values():
            n = len({p["system"] for p in ps})
            g = ps[0]["gap"]
            k = ("MONEYBALL (2+ systems + players 3+)" if n >= 2 else "1 system + players 3+") if g >= 3 else \
                "system(s) without players 3+"
            add(k, ps[0])
        print(f"\n=== {season}   (record at the OPEN  |  same bets at the CLOSE)")
        for k in ("S4 (total above season avg)", "players model gap 3-4", "players model gap 4+ (T13)",
                  "1 system + players 3+", "MONEYBALL (2+ systems + players 3+)", "system(s) without players 3+",
                  "any spread system, all"):
            o, c = cats[k]
            print(f"  {k:40} open {rec(o):18} | close {rec(c)}")


if __name__ == "__main__":
    main()
