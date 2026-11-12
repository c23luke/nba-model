"""STACK THE FLAGS (Caden 2026-11-11: "we don't look at one thing, we can look at multiple ... find even more single
and test them together"). Two seasons, free. For every game SIDE (the team we'd bet), these flags:
  pm3      the players model likes this side by 3+ (live model, opening-line calibration)
  sys      at least one card system (T / S) on this side;   sys2  two or more
  x2       opponent missing 2+ rotation players (more than us, 1+ fresh)
  x3       ... 2+ of them fresh;   x4  ... all at different positions
  x5       we won our last game by 25+
  x6       opponent's last game went to overtime
  move2    the spread moved 2+ toward us (evening line -> close);  move1  1+
  x9       we're home with 2+ more days of rest
  thin     the opponent leans on players the model barely knows (5+ points more of its minutes than us)
  opp_hot  the opponent shot 3+ a game ABOVE its shot quality (last 5);  we_cold  we shot 3+ BELOW ours
  opp_b2b  the opponent is on a back-to-back and we aren't
Reported: records by NUMBER of flags on one side; then every pair and triple with enough games, at the close
(and the open), per season. Only combinations that win in BOTH seasons count; with this many combinations some
will look good by luck, so the report says how many to expect by chance.
Run: python -m engine.measure_stack_flags
"""
from __future__ import annotations

import itertools
from collections import defaultdict

from . import backtest_open as BO
from . import measure_cluster as MC
from . import measure_ideas as MI
from . import measure_ideas2 as MI2
from . import measure_stacks as MS
from .measure_minutes_spots import load
from .measure_unknowns import thin_shares

FLAGS = ["pm3", "sys", "sys2", "x2", "x3", "x4", "x5", "x6", "move2", "move1", "x9", "thin", "opp_hot", "we_cold", "opp_b2b"]


def season(season):
    games, _, _ = load(season)
    key_of = {str(g.id): f"{g.game_date.isoformat()}|{g.away}|{g.home}" for g in games}
    # the players-model replay keeps its own game list: key its games by date|away|home too
    for item in MS.fetch(season)[0]:
        g0 = item[0] if isinstance(item, tuple) else item
        key_of[str(g0.id)] = f"{g0.game_date.isoformat()}|{g0.away}|{g0.home}"
    gap, systems = {}, defaultdict(set)
    for r in MS.season_rows(season):
        k = key_of.get(str(r["game"]))
        if not k:
            continue
        if r["system"] == 301 and r["gap"] is not None and r.get("side"):
            gap[(k, r["side"])] = r["gap"]          # the side the players model likes, by how much
            continue
        if r["bet"] != "spread":
            continue
        if r["system"] < 300 and r["system"] != 113:
            systems[(k, r["side"])].add(r["system"])
    print(f"{season}: players-model gaps matched for {len(gap)} game sides; system sides {len(systems)}", flush=True)
    clus = {f"{r['date']}|{r['away']}|{r['home']}": r for r in MC.season_rows(season)}
    ideas = {f"{r['date']}|{r['away']}|{r['home']}": r for r in MI.season_rows(season)}
    ideas2 = {f"{r['date']}|{r['away']}|{r['home']}": r for r in MI2.season_rows(season)}
    thin = thin_shares(season)
    out = []
    for k, r in ideas2.items():
        d, away, home = k.split("|")
        c, i = clus.get(k), ideas.get(k)
        if r.get("close") is None:
            continue
        th = thin.get((__import__("datetime").date.fromisoformat(d), home, away)) or {}
        for side, opp, s in ((home, away, "h"), (away, home, "a")):
            o = "a" if s == "h" else "h"
            f = set()
            g_ = gap.get((k, side))
            if g_ is None and gap.get((k, opp)) is not None:
                g_ = -gap[(k, opp)]
            if g_ is not None and g_ >= 3:
                f.add("pm3")
            ns = len(systems.get((k, side)) or ())
            if ns >= 1:
                f.add("sys")
            if ns >= 2:
                f.add("sys2")
            if c:
                oo, mo = c["outs"].get(opp) or [], c["outs"].get(side) or []
                fresh = sum(1 for x in oo if x[3])
                if len(oo) >= 2 and len(oo) > len(mo) and fresh >= 1:
                    f.add("x2")
                    if fresh >= 2:
                        f.add("x3")
                    if len({x[2] for x in oo}) == len(oo):
                        f.add("x4")
            if i:
                if (i.get(f"prev_margin_{s}") or 0) >= 25:
                    f.add("x5")
                if i.get(f"ot_{o}"):
                    f.add("x6")
                if (i.get(f"luck_{o}") or 0) >= 3:
                    f.add("opp_hot")
                if (i.get(f"luck_{s}") if i.get(f"luck_{s}") is not None else 0) <= -3:
                    f.add("we_cold")
                if i.get(f"b2b_{o}") and not i.get(f"b2b_{s}"):
                    f.add("opp_b2b")
            first = r["eve"] if r.get("eve") is not None else r["open"]
            if first is not None:
                mv = (first - r["close"]) if side == home else (r["close"] - first)      # + = toward this side
                if mv >= 2:
                    f.add("move2")
                if mv >= 1:
                    f.add("move1")
            if side == home and r.get("rest_h") is not None and r.get("rest_a") is not None and r["rest_h"] - r["rest_a"] >= 2:
                f.add("x9")
            if th and th.get(opp, 0) > th.get(side, 0) + 0.05:
                f.add("thin")
            m = r["margin"] if side == home else -r["margin"]
            res = {w: (m + (r[w] if side == home else -r[w])) if r.get(w) is not None else None for w in ("open", "close")}
            out.append({"season": season, "flags": f, "res": res, "key": k, "side": side, "opp": opp, "home": home,
                        # raw inputs, for the follow-up studies (measure_stack2)
                        "mi": i, "mi2": r, "outs": (c or {}).get("outs") or {}, "th": th, "gap": g_})
    return out


def rec(xs):
    w = sum(x > 0 for x in xs); l = sum(x < 0 for x in xs)
    return (w, l), (f"{w}-{l} ({w / (w + l):.1%})" if w + l else "-")


def main():
    data = {s: season(s) for s in BO.SEASONS}
    seasons = list(BO.SEASONS)
    print("=== records by HOW MANY flags are on one side (the meta flags move1/sys count too)")
    for n in range(0, 6):
        line = f"  {n}{'+' if n == 5 else ' '} flags"
        for s in seasons:
            xs = [r for r in data[s] if (len(r["flags"]) >= n if n == 5 else len(r["flags"]) == n)]
            line += f"   {s}: open {rec([r['res']['open'] for r in xs if r['res']['open'] is not None])[1]:>17}  close {rec([r['res']['close'] for r in xs])[1]:>17}"
        print(line)
    print("\n=== 5+ flags, split by whether the players model (3+) is one of them (Caden 2026-11-11)")
    for nm, keep in (("5+ WITH players model 3+", lambda r: len(r["flags"]) >= 5 and "pm3" in r["flags"]),
                     ("5+ WITHOUT players model 3+", lambda r: len(r["flags"]) >= 5 and "pm3" not in r["flags"]),
                     ("5 exactly, with players 3+", lambda r: len(r["flags"]) == 5 and "pm3" in r["flags"]),
                     ("6+ with players 3+", lambda r: len(r["flags"]) >= 6 and "pm3" in r["flags"]),
                     ("5+ with players 3+ AND 1+ system", lambda r: len(r["flags"]) >= 5 and {"pm3", "sys"} <= r["flags"]),
                     ("5+ with players 3+, NO system", lambda r: len(r["flags"]) >= 5 and "pm3" in r["flags"] and "sys" not in r["flags"])):
        line = f"  {nm:36}"
        allc, allo = [], []
        for s in seasons:
            xs = [r for r in data[s] if keep(r)]
            o = [r['res']['open'] for r in xs if r['res']['open'] is not None]; c = [r['res']['close'] for r in xs]
            allo += o; allc += c
            line += f"   {s}: open {rec(o)[1]:>17}  close {rec(c)[1]:>17}"
        print(line + f"   BOTH: open {rec(allo)[1]}  close {rec(allc)[1]}")
    print("\n=== single flags")
    for fl in FLAGS:
        line = f"  {fl:9}"
        for s in seasons:
            xs = [r for r in data[s] if fl in r["flags"]]
            line += f"   {s}: open {rec([r['res']['open'] for r in xs if r['res']['open'] is not None])[1]:>17}  close {rec([r['res']['close'] for r in xs])[1]:>17}"
        print(line)
    for size, need in ((2, 40), (3, 25)):
        print(f"\n=== every {size}-flag combination with {need}+ games over both seasons: the ones that won BOTH seasons at the close (55%+ overall)")
        tested = hits = 0
        rows_out = []
        for combo in itertools.combinations(FLAGS, size):
            cs = set(combo)
            if {"move1", "move2"} <= cs or {"sys", "sys2"} <= cs or len(cs & {"x2", "x3", "x4"}) > 1:
                continue
            per = {s: [r for r in data[s] if cs <= r["flags"]] for s in seasons}
            n = sum(len(v) for v in per.values())
            if n < need:
                continue
            tested += 1
            (w1, l1), _ = rec([r["res"]["close"] for r in per[seasons[0]]])
            (w2, l2), _ = rec([r["res"]["close"] for r in per[seasons[1]]])
            if w1 > l1 and w2 > l2 and (w1 + w2) / max(1, w1 + w2 + l1 + l2) >= 0.55:
                hits += 1
                (wo, lo), so = rec([r["res"]["open"] for s in seasons for r in per[s] if r["res"]["open"] is not None])
                rows_out.append(((w1 + w2) / (w1 + w2 + l1 + l2), " + ".join(combo), f"{w1}-{l1}", f"{w2}-{l2}",
                                 f"{w1 + w2}-{l1 + l2}", so))
        for pct, nm, a, b, t, so in sorted(rows_out, reverse=True):
            print(f"  {nm:34} {seasons[0]} {a:>8}  {seasons[1]} {b:>8}  both {t:>9} ({pct:.1%})   at the open {so}")
        print(f"  ({tested} combinations tested; {hits} won both seasons at 55%+. By luck alone, roughly "
              f"{max(1, round(tested * 0.06))} would.)")


if __name__ == "__main__":
    main()
