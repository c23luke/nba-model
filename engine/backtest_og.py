"""Every system on the board (OG, test, early) replayed on 2024-25 and 2025-26, rule for rule.

Graded twice: against the opening line and against the closing line (Odds API consensus, cached).
Card records for the OG systems are shown next to them for comparison. No credits used.
"""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from . import backtest as BT
from . import personnel as P
from . import sources
from .state import team_state
from .systems import (SYSTEMS, TEST_SYSTEMS, EARLY_SYSTEMS, evaluate, evaluate_tests, evaluate_early,
                      grade, label, group)

SEASONS = {"2024-25": ("2024-10-22", "2025-04-13"), "2025-26": ("2025-10-21", "2026-04-12")}


def season_games(start, end):
    from datetime import date
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    days = [s + timedelta(i) for i in range((e - s).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        return sorted([g for day in ex.map(lambda d: BT._safe(sources.espn_day, d) or [], days)
                       for g, _ in day if g.final], key=lambda g: (g.game_date, g.id)), s


AGREE = [("players model disagrees", -99, 0), ("agrees by 0-3", 0, 3), ("agrees by 3-5", 3, 5),
         ("agrees by 5+", 5, 99)]


def agree_bucket(gap_on_side: float) -> str:
    for name, lo, hi in AGREE:
        if lo <= gap_on_side < hi:
            return name
    return AGREE[-1][0]


def main():
    names = {**SYSTEMS, **TEST_SYSTEMS, **EARLY_SYSTEMS}
    rec = defaultdict(lambda: {"open": [0, 0, 0], "close": [0, 0, 0]})
    gp = P.STATIC / "personnel_gaps.json"
    pgaps = json.loads(gp.read_text()) if gp.exists() else {}
    combo = defaultdict(lambda: {"open": [0, 0, 0], "close": [0, 0, 0]})        # (group or system, bucket)
    per_season = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for season, (start, end) in SEASONS.items():
        games, s0 = season_games(start, end)
        tag = season.replace("-", "_")
        spreads = json.loads((P.STATIC / f"odds_openclose_{tag}.json").read_text())
        totals = json.loads((P.STATIC / f"odds_totals_{tag}.json").read_text())
        finals = []
        by_day = defaultdict(list)
        for g in games:
            by_day[g.game_date].append(g)
        for day in sorted(by_day):
            for g in by_day[day]:
                k = f"{day.isoformat()}|{g.away}|{g.home}"
                sp, tt = spreads.get(k) or {}, totals.get(k) or {}
                hs, as_ = team_state(g.home, finals, day), team_state(g.away, finals, day)
                for when in ("open", "close"):
                    h_line, t_line = sp.get(when), tt.get(when)
                    if h_line is None and t_line is None:
                        continue
                    picks = (evaluate(g, hs, as_, h_line, t_line) + evaluate_tests(g, hs, as_, h_line, t_line)
                             + evaluate_early(g, hs, as_, h_line, t_line, (day - s0).days))
                    for p in picks:
                        if p.line is None:
                            continue
                        r = grade(p, g)
                        i = {"W": 0, "L": 1, "P": 2}.get(r)
                        if i is None:
                            continue
                        rec[p.system][when][i] += 1
                        pg = (pgaps.get(k) or {}).get("gap")
                        if p.bet == "spread" and pg is not None:
                            b = agree_bucket(pg if p.side == g.home else -pg)
                            for who in (group(p.system), label(p.system)):
                                combo[(who, b)][when][i] += 1
                        if when == "close":
                            per_season[p.system][season][i] += 1
            finals += by_day[day]
        print(f"{season}: {len(games)} games replayed")
    print()
    fmt = lambda w, l, p: (f"{w}-{l}" + (f"-{p}" if p else "") + (f" ({w/(w+l):.1%}, {w - 1.1 * l:+.1f}u)" if w + l else ""))
    print(f"{'system':44} {'vs CLOSE (2 seasons)':28} {'vs OPEN':28} by season (close)")
    for sid in sorted(rec):
        r = rec[sid]
        card = SYSTEMS[sid]["card"] if sid in SYSTEMS else ""
        ss = " | ".join(f"{s}: {fmt(*per_season[sid][s])}" for s in SEASONS)
        print(f"{label(sid) + ' ' + names[sid]['name']:44} {fmt(*r['close']):28} {fmt(*r['open']):28} {ss}"
              + (f"   CARD: {card}" if card else ""))
    never = [label(s) for s in names if s not in rec]
    print(f"\nnever fired: {', '.join(never) or 'none'}")
    if not pgaps:
        print("\n(no personnel_gaps.json yet: run the opening-line backtest first)")
        return
    print("\n=== SYSTEM + PLAYERS MODEL (spread systems only): does it help when the personnel line agrees?")
    print(f"{'':10} {'':26} {'vs OPEN':28} {'vs CLOSE':28}")
    out = {}
    whos = ["OG", "FAV", "TEST", "EARLY"] + [label(s) for s in sorted(rec)]
    for who in whos:
        rows = [(b, combo[(who, b)]) for b, _, _ in AGREE if (who, b) in combo]
        if not rows:
            continue
        out[who] = {b: {"open": r["open"], "close": r["close"]} for b, r in rows}
        for b, r in rows:
            print(f"{who:10} {b:26} {fmt(*r['open']):28} {fmt(*r['close']):28}")
    (P.STATIC / "og_personnel.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main()
