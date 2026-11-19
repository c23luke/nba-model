"""FAVORITE vs UNDERDOG, by spread size, for every bet type we place (Caden 2026-11-19).

Live after 30 bets: underdogs 18-9, favorites 5-5; MONEYBALL 0-2 as a big favorite (DET -9.5, DEN -11.5). Is that a
real pattern or noise? Replays 2024-25 and 2025-26 (the same rows as engine.measure_stack_flags: one row per game side,
graded at the OPENING line at -110; MOVE+THIN at the close, since it needs the move) and splits each bet type by the
spread we would have held.

A pattern counts only if it holds in BOTH seasons. Not covered here: the shot-quality pairs (RIM+PM, SQ+X3, SQ+THIN,
UNLUCKY+X4), which need engine.measure_stack2's shot data.
Run: python -m engine.measure_fav_dog
"""
from __future__ import annotations

from collections import defaultdict

from . import backtest_open as BO
from . import measure_stack_flags as MSF

TIRED_SYS = {1, 3, 101, 102, 103, 104, 112, 124}
BANDS = ["dog 10+", "dog 5 to 9.5", "dog 0.5 to 4.5", "fav 0 to 4.5", "fav 5 to 9.5", "fav 10+"]


def band(line):
    if line >= 10:
        return "dog 10+"
    if line >= 5:
        return "dog 5 to 9.5"
    if line > 0:
        return "dog 0.5 to 4.5"
    if line > -5:
        return "fav 0 to 4.5"
    if line > -10:
        return "fav 5 to 9.5"
    return "fav 10+"


def facts_open(r):
    """STACK's separate facts known before the line moves (engine.situations.stack_facts, no line move)."""
    fl, ids = r["flags"], set(r.get("sys_ids") or ())
    g = set()
    if "pm3" in fl:
        g.add("players model")
    if ids - TIRED_SYS:
        g.add("systems")
    if ids & TIRED_SYS or {"opp_b2b", "x6", "x9"} & fl:
        g.add("tired opponent")
    if {"x2", "x3", "x4"} & fl:
        g.add("injuries")
    for x in ("x5", "thin", "opp_hot", "we_cold"):
        if x in fl:
            g.add(x)
    return g


def gap(r):
    return r.get("gap") if r.get("gap") is not None else -99


BETS = [
    ("STACK (4+ separate facts)", lambda r: len(facts_open(r)) >= 4, "open"),
    ("MONEYBALL (2+ systems + players 3+)", lambda r: "pm3" in r["flags"] and len(r.get("sys_ids") or ()) >= 2, "open"),
    ("System + players 3+ (1 system)", lambda r: "pm3" in r["flags"] and len(r.get("sys_ids") or ()) == 1, "open"),
    ("T13 players model alone 4+", lambda r: gap(r) >= 4, "open"),
    ("T13 4+ vs a thin roster", lambda r: gap(r) >= 4 and "thin" in r["flags"], "open"),
    ("SYS+X4", lambda r: "sys" in r["flags"] and "x4" in r["flags"], "open"),
    ("X4+B2B", lambda r: "x4" in r["flags"] and "opp_b2b" in r["flags"], "open"),
    ("X2+B2B", lambda r: "x2" in r["flags"] and "opp_b2b" in r["flags"], "open"),
    ("MOVE+THIN (graded at the close)", lambda r: "move2" in r["flags"] and "thin" in r["flags"], "close"),
]


def rec(xs):
    w, l = sum(x > 0 for x in xs), sum(x < 0 for x in xs)
    n = w + l
    return f"{w}-{l}" + (f" ({w / n:.1%}, {w - 1.1 * l:+.1f}u)" if n else "")


def line_of(r):
    o = (r.get("mi2") or {}).get("open")
    if o is None:
        return None
    return o if r["side"] == r["home"] else -o


def main():
    data = {s: MSF.season(s) for s in BO.SEASONS}
    seasons = list(BO.SEASONS)
    for name, keep, when in BETS:
        print(f"\n=== {name}  (graded at the {when})")
        cells = defaultdict(lambda: defaultdict(list))
        for s in seasons:
            for r in data[s]:
                if not keep(r):
                    continue
                ln, res = line_of(r), r["res"].get(when)
                if ln is None or res is None:
                    continue
                for scope in (s, "both"):
                    cells[scope]["ALL"].append(res)
                    cells[scope]["UNDERDOG (any)" if ln > 0 else "FAVORITE (any)"].append(res)
                    cells[scope][band(ln)].append(res)
        for b in ["ALL", "UNDERDOG (any)", "FAVORITE (any)"] + BANDS:
            print(f"  {b:16} " + "   ".join(f"{s}: {rec(cells[s][b]):>24}" for s in seasons)
                  + f"   BOTH: {rec(cells['both'][b])}")
    # every system on its own (no players-model requirement), favorite vs underdog
    print("\n=== EACH SYSTEM ON ITS OWN (no players-model requirement), at the open")
    per = defaultdict(lambda: defaultdict(list))
    for s in seasons:
        for r in data[s]:
            ln, res = line_of(r), r["res"].get("open")
            if ln is None or res is None:
                continue
            for sid in r.get("sys_ids") or ():
                for scope in (s, "both"):
                    per[(sid, scope)]["dog" if ln > 0 else "fav"].append(res)
    for sid in sorted({k[0] for k in per}):
        line = f"  system {sid:>3}"
        for side in ("dog", "fav"):
            line += f"   {side}: " + "  ".join(f"{s[-5:]} {rec(per[(sid, s)][side]):>22}" for s in seasons + ['both'])
        print(line)


if __name__ == "__main__":
    main()
