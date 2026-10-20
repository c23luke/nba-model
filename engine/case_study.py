"""One-off: how sensitive is each personnel gap to the model's two biggest judgement calls?

  A. base (what the board uses)
  B. top-down minutes: rotation players get their full projected role, the end of the bench
     loses minutes first (instead of shrinking everyone by the same %)
  C. no injury-return penalty for the RETURNS list (aging only)
  D. B + C
Prints every game's raw and slate-calibrated gap under each, the market correlation under
each, and the full rotation tables for the requested games.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from . import personnel as P
from . import sources


def topdown(tr):
    avail = [p for p in tr.players if p.wanted > 0 and p.bpm_used is not None]
    left, mins = 240.0, {}
    for p in sorted(avail, key=lambda p: -p.wanted):
        m = min(p.wanted, left)
        mins[id(p)] = m
        left -= m
    return sum(p.bpm_used * mins.get(id(p), 0) / 48 for p in avail), mins


def no_return_penalty(p):
    if p.last and p.last.get("missed_last") and P.norm(p.name) in P.RETURNS:
        base = p.last["bpm_blend"] + p.last.get("age_delta", 0.0)
        injury = P.RETURNS[P.norm(p.name)]["injury"]
        return base, 1 / P.INJURY_MINUTES[injury]
    return p.bpm_used, 1.0


def variant(tr, minutes_mode, returns_mode):
    saved = [(p, p.bpm_used, p.wanted) for p in tr.players]
    if returns_mode:
        for p in tr.players:
            if p.bpm_used is None:
                continue
            b, mfac = no_return_penalty(p)
            p.bpm_used, p.wanted = b, min(p.wanted * mfac, P.MIN_CAP)
    if minutes_mode:
        r, _ = topdown(tr)
    else:
        tot = sum(p.wanted for p in tr.players if p.bpm_used is not None and p.wanted > 0)
        sc = 240 / tot if tot > 240 else 1.0
        r = sum(p.bpm_used * p.wanted * sc / 48 for p in tr.players if p.bpm_used is not None and p.wanted > 0)
    for p, b, w in saved:
        p.bpm_used, p.wanted = b, w
    return r


def corr(pairs):
    n = len(pairs)
    mx = sum(m for m, _ in pairs) / n; fx = sum(f for _, f in pairs) / n
    cov = sum((m - mx) * (f - fx) for m, f in pairs)
    vm = sum((m - mx) ** 2 for m, _ in pairs); vf = sum((f - fx) ** 2 for _, f in pairs)
    return cov / (vm * vf) ** 0.5


def main(focus):
    now = datetime.now(timezone.utc)
    today = now.astimezone(sources.ET).date()
    games, espn = [], {}
    for d in (today, today + timedelta(1)):
        for g, line in sources.espn_day(d):
            if not g.final:
                games.append(g)
                if line:
                    espn[g.id] = line
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    odds = sources.odds_api_lines(key)[0] if key else {}
    reads = P.read_all()
    rows = []
    for g in games:
        ln = odds.get((g.game_date, g.away, g.home)) or espn.get(g.id) or {}
        if ln.get("home_spread") is not None:
            rows.append((g.away, g.home, ln["home_spread"]))
    names = {"A": (False, False), "B": (True, False), "C": (False, True), "D": (True, True)}
    print("A = base (board) | B = top-down minutes | C = no injury-return penalty | D = B + C\n")
    fairs = {}
    for k, (mm, rm) in names.items():
        rat = {t: variant(tr, mm, rm) for t, tr in reads.items()}
        f = {(a, h): -(rat[h] - rat[a] + P.HOME_COURT) for a, h, _ in rows}
        pairs = [(m, f[(a, h)]) for a, h, m in rows]
        cal = P.calibrate(pairs)
        fairs[k] = (f, cal, rat)
        print(f"{k}: market correlation {corr(pairs):.2f}, calibration market = {cal[0]:+.2f} + {cal[1]:.2f} x personnel")
    print()
    for a, h, m in rows:
        cells = []
        for k in names:
            f, cal, _ = fairs[k]
            fc = cal[0] + cal[1] * f[(a, h)]
            cells.append(f"{k}: raw {f[(a, h)]:+5.1f} cal {fc:+5.1f} gap {m - fc:+5.1f}")
        print(f"{a:>3} @ {h:<3} mkt {h} {m:+5.1f} | " + " | ".join(cells))
    print()
    for t in focus:
        tr = reads[t]
        _, td = topdown(tr)
        print(f"{t} rotation  (base rating {tr.rating:+.2f}; top-down {fairs['B'][2][t]:+.2f}; no-return-penalty {fairs['C'][2][t]:+.2f})")
        print(f"  {'player':26} {'status':11} {'role':>5} {'base min':>8} {'top-down':>8} {'BPM used':>8} {'pts/100':>7}  source")
        for p in sorted(tr.players, key=lambda p: -p.wanted):
            if p.wanted <= 0 and p.status != "out":
                continue
            src = ("rookie prior" if p.prior else "returner" if (p.last and p.last.get("missed_last"))
                   else ("new: " + p.last["team"]) if (p.last and p.last["team"] != t) else "same team" if p.last else "unknown")
            bu = p.bpm_used if p.bpm_used is not None else float("nan")
            print(f"  {p.name:26} {p.status:11} {p.wanted:5.1f} {p.minutes:8.1f} {td.get(id(p), 0):8.1f} {bu:+8.2f} "
                  f"{(p.bpm_used or 0) * p.minutes / 48:+7.2f}  {src}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:] or ["IND", "NOP"])
