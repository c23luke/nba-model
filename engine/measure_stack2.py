"""STACK, ROUND 2 (Caden 2026-11-11: "try those ... more thinking on shot quality, alone and with stacks ... branch out
and test everything, get creative"). Two seasons, free (ESPN summaries + saved lines). Builds on
engine/measure_stack_flags.py (same 15 flags, same sides) and adds:

  A. SHOT-QUALITY FLAGS, each alone and inside stacks. From every field-goal attempt's location, valued at
     league rates for that zone (rim / short / mid / corner 3 / above-the-break 3), before tonight:
       sq_better      our shot-quality margin (what our shots were worth minus what we allowed, last 10) beats theirs
                      by a top-15% amount
       sq_unlucky     our real margins ran a top-15% amount BELOW our shot-quality margins (last 10): due to bounce
       opp_sq_lucky   their real margins ran a top-15% amount ABOVE theirs: due to fall
       unlucky_loss   we lost our last game but won it on the shots by 4+
       opp_lucky_win  they won their last game but lost it on the shots by 4+
       opp_def_lucky  teams have shot a top-15% amount BELOW their shot quality against them (last 10): their
                      defense has been lucky
       we_def_unlucky teams have shot a top-15% amount ABOVE their shot quality against us
       opp_3_hot      they made 3s a top-15% amount above what their 3s were worth (last 5)
       three_match    we take a top-30% share of 3s and they allow a top-30% share of 3s
       rim_match      same at the rim
       x5_real / x5_luck  the 25+ blowout win, split by whether the shots backed it (won the shots by 12+)
     plus three ideas that failed alone, as stack ingredients: opp_heavy_b2b (their top player played 40+ and
     they're on a back-to-back), opp_ft_lucky (1.5+ more free throws a game than the league rate, last 10),
     we_rest2 (2+ more days of rest than them, home OR away).
  B. MARGINAL VALUE: for every flag, sides that already have 4+ OTHER flags, with vs without it.
  C. STACK v2: count with every flag (old + new).
  D. OPENING-LINE STACK: only flags known in the morning (no line moves), graded at the OPENING line.
  E. NET STACK: our flags minus the other side's flags.
  F. TOTALS STACK: game flags for overs / unders. Each flag's direction is chosen on 2024-25 ONLY, then the stack
     (count of flags pointing the same way) is graded on 2025-26 - a clean test, no peeking.
Percentile cut-offs (top 15% etc.) come from both seasons pooled: the flag definitions see the whole sample,
the results don't.
Run: python -m engine.measure_stack2
"""
from __future__ import annotations

import itertools
import json
from collections import defaultdict

from . import backtest_open as BO
from . import measure_stack_flags as MSF
from . import personnel as P
from .measure_minutes_spots import load
from .prop_model import ZONES, shot_list

THREES = ("corner3", "above3")


def rec(xs):
    w = sum(x > 0 for x in xs); l = sum(x < 0 for x in xs)
    return (w, l), (f"{w}-{l} ({w / (w + l):.1%})" if w + l else "-")


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def sq_season(season):
    """(date|away|home, team) -> shot-quality features BEFORE tonight; plus the game rows for totals."""
    games, sums, _ = load(season)
    zl = {z: [0, 0] for z in ZONES}
    hist = defaultdict(list)
    feats = {}
    for g in games:
        js = sums.get(g.id) or {}
        shots = shot_list(js)
        k = f"{g.game_date.isoformat()}|{g.away}|{g.home}"
        L = {z: (v[1] / v[0] if v[0] else 0.0) for z, v in zl.items()}
        ready = sum(v[0] for v in zl.values()) > 2000
        for team in (g.home, g.away):
            h = hist[team][-10:]
            if len(h) < 5:
                continue
            h5 = h[-5:]
            att = lambda key, zs: sum(sum(x[key][z] for z in zs) for x in h)
            tot_f, tot_a = att("zf", ZONES) or 1, att("za", ZONES) or 1
            feats[(k, team)] = {
                "xnet10": mean([x["xf"] - x["xa"] for x in h]),
                "luck_net10": mean([(x["af"] - x["xf"]) - (x["aa"] - x["xa"]) for x in h]),
                "def_luck10": mean([x["aa"] - x["xa"] for x in h]),
                "three_luck5": mean([x["t3"] for x in h5]),
                "r3": att("zf", THREES) / tot_f, "rrim": att("zf", ("rim",)) / tot_f,
                "d3": att("za", THREES) / tot_a, "drim": att("za", ("rim",)) / tot_a,
                "last_margin": h[-1]["margin"], "last_xmargin": h[-1]["xmargin"],
                "xpts10": mean([x["xf"] + x["ft"] for x in h]), "xallow10": mean([x["xa"] + x["fta"] for x in h]),
            }
        per = {t: {"xf": 0.0, "af": 0.0, "z": {z: 0 for z in ZONES}, "t3": 0.0} for t in (g.home, g.away)}
        for team, _, z, pts in shots:
            if team not in per:
                continue
            per[team]["xf"] += L[z]; per[team]["af"] += pts; per[team]["z"][z] += 1
            if z in THREES:
                per[team]["t3"] += pts - L[z]
        if ready and all(sum(per[t]["z"].values()) >= 50 for t in per):
            score = {g.home: g.home_score, g.away: g.away_score}
            for team, opp in ((g.home, g.away), (g.away, g.home)):
                a, b = per[team], per[opp]
                ft, fta = score[team] - a["af"], score[opp] - b["af"]
                hist[team].append({"xf": a["xf"], "xa": b["xf"], "af": a["af"], "aa": b["af"], "ft": ft, "fta": fta,
                                   "margin": score[team] - score[opp], "xmargin": (a["xf"] + ft) - (b["xf"] + fta),
                                   "zf": a["z"], "za": b["z"], "t3": a["t3"]})
        for team, _, z, pts in shots:
            zl[z][0] += 1; zl[z][1] += pts
    print(f"{season}: shot-quality features for {len(feats)} team-games", flush=True)
    return feats


def pct(vals, q):
    vs = sorted(v for v in vals if v is not None)
    return vs[min(len(vs) - 1, int(q * len(vs)))] if vs else None


NEW = ["sq_better", "sq_unlucky", "opp_sq_lucky", "unlucky_loss", "opp_lucky_win", "opp_def_lucky", "we_def_unlucky",
       "opp_3_hot", "three_match", "rim_match", "x5_real", "x5_luck", "opp_heavy_b2b", "opp_ft_lucky", "we_rest2"]
MOVES = {"move1", "move2"}


def add_flags(rows, feats, cut):
    for r in rows:
        f, o = feats.get((r["key"], r["side"])), feats.get((r["key"], r["opp"]))
        new = set()
        if f and o:
            if f["xnet10"] - o["xnet10"] >= cut["sqdiff"]:
                new.add("sq_better")
            if f["luck_net10"] <= cut["luck_lo"]:
                new.add("sq_unlucky")
            if o["luck_net10"] >= cut["luck_hi"]:
                new.add("opp_sq_lucky")
            if f["last_margin"] < 0 and f["last_xmargin"] >= 4:
                new.add("unlucky_loss")
            if o["last_margin"] > 0 and o["last_xmargin"] <= -4:
                new.add("opp_lucky_win")
            if o["def_luck10"] <= cut["dl_lo"]:
                new.add("opp_def_lucky")
            if f["def_luck10"] >= cut["dl_hi"]:
                new.add("we_def_unlucky")
            if o["three_luck5"] >= cut["t3_hi"]:
                new.add("opp_3_hot")
            if f["r3"] >= cut["r3"] and o["d3"] >= cut["d3"]:
                new.add("three_match")
            if f["rrim"] >= cut["rrim"] and o["drim"] >= cut["drim"]:
                new.add("rim_match")
            if "x5" in r["flags"]:
                new.add("x5_real" if f["last_xmargin"] >= 12 else "x5_luck")
        i, i2 = r.get("mi") or {}, r.get("mi2") or {}
        s, so = ("h", "a") if r["side"] == r["home"] else ("a", "h")
        if i.get(f"b2b_{so}") and i.get(f"heavy_{so}") and not i.get(f"b2b_{s}"):
            new.add("opp_heavy_b2b")
        if (i2.get(f"ftluck_{so}") or 0) >= 1.5:
            new.add("opp_ft_lucky")
        if i2.get(f"rest_{s}") is not None and i2.get(f"rest_{so}") is not None and i2[f"rest_{s}"] - i2[f"rest_{so}"] >= 2:
            new.add("we_rest2")
        r["new"] = new
        r["all"] = r["flags"] | new


def line(label, per, seasons, key="close", width=44):
    out = f"  {label:{width}}"
    tot = []
    for s in seasons:
        xs = [x for x in per[s] if x is not None]
        tot += xs
        out += f"  {s} {rec(xs)[1]:>17}"
    return out + f"   both {rec(tot)[1]}"


def main():
    seasons = list(BO.SEASONS)
    data = {s: MSF.season(s) for s in seasons}
    feats = {}
    for s in seasons:
        feats.update(sq_season(s))
    fv = list(feats.values())
    # side-level differences need pairs: collect from the rows
    diffs = [feats[(r["key"], r["side"])]["xnet10"] - feats[(r["key"], r["opp"])]["xnet10"]
             for s in seasons for r in data[s] if (r["key"], r["side"]) in feats and (r["key"], r["opp"]) in feats]
    cut = {"sqdiff": pct(diffs, 0.85), "luck_lo": pct([x["luck_net10"] for x in fv], 0.15),
           "luck_hi": pct([x["luck_net10"] for x in fv], 0.85), "dl_lo": pct([x["def_luck10"] for x in fv], 0.15),
           "dl_hi": pct([x["def_luck10"] for x in fv], 0.85), "t3_hi": pct([x["three_luck5"] for x in fv], 0.85),
           "r3": pct([x["r3"] for x in fv], 0.70), "d3": pct([x["d3"] for x in fv], 0.70),
           "rrim": pct([x["rrim"] for x in fv], 0.70), "drim": pct([x["drim"] for x in fv], 0.70)}
    print("cut-offs: " + ", ".join(f"{k} {v:+.3f}" for k, v in cut.items()))
    for s in seasons:
        add_flags(data[s], feats, cut)
    C = lambda r: r["res"]["close"]
    O = lambda r: r["res"]["open"]

    print("\n=== A. NEW FLAGS ALONE (bet the side the flag points to)  [close | open]")
    for fl in NEW:
        per = {s: [C(r) for r in data[s] if fl in r["new"]] for s in seasons}
        pero = {s: [O(r) for r in data[s] if fl in r["new"]] for s in seasons}
        print(line(fl + " (close)", per, seasons) + "\n" + line("    at the open", pero, seasons))

    print("\n=== A2. NEW FLAG + ONE OLD FLAG: pairs with 40+ games that won BOTH seasons at 55%+ (close)")
    tested = hits = 0
    found = []
    for a in NEW:
        for b in MSF.FLAGS:
            per = {s: [C(r) for r in data[s] if a in r["new"] and b in r["flags"]] for s in seasons}
            n = sum(len(v) for v in per.values())
            if n < 40:
                continue
            tested += 1
            (w1, l1), _ = rec(per[seasons[0]]); (w2, l2), _ = rec(per[seasons[1]])
            if w1 > l1 and w2 > l2 and (w1 + w2) / max(1, w1 + w2 + l1 + l2) >= 0.55:
                hits += 1
                found.append(((w1 + w2) / (w1 + w2 + l1 + l2), f"{a} + {b}", per))
    for _, nm, per in sorted(found, key=lambda x: -x[0]):
        print(line(nm, per, seasons))
    print(f"  ({tested} pairs tested; {hits} won both seasons at 55%+; by luck alone about {max(1, round(tested * 0.06))})")

    print("\n=== B. MARGINAL VALUE: sides with 4+ OTHER flags (old + new), WITH this flag vs WITHOUT it (close)")
    for fl in MSF.FLAGS + NEW:
        w_ = {s: [C(r) for r in data[s] if fl in r["all"] and len(r["all"] - {fl}) >= 4] for s in seasons}
        wo = {s: [C(r) for r in data[s] if fl not in r["all"] and len(r["all"]) >= 4] for s in seasons}
        a, b = rec([x for v in w_.values() for x in v])[0], rec([x for v in wo.values() for x in v])[0]
        pa = a[0] / max(1, sum(a)); pb = b[0] / max(1, sum(b))
        print(line(f"{fl}: with", w_, seasons, width=22) + f"   | without {rec([x for v in wo.values() for x in v])[1]}"
              f"   adds {100 * (pa - pb):+.1f} pts")

    print("\n=== C. STACK v2: how many flags (old 15 + new 15) on one side  [close]")
    for n in range(0, 9):
        keep = (lambda r, n=n: len(r["all"]) >= n) if n == 8 else (lambda r, n=n: len(r["all"]) == n)
        print(line(f"{n}{'+' if n == 8 else ''} flags", {s: [C(r) for r in data[s] if keep(r)] for s in seasons}, seasons))
    print("  -- old flags only, for comparison --")
    for n in (4, 5, 6):
        keep = (lambda r, n=n: len(r["flags"]) >= n) if n == 6 else (lambda r, n=n: len(r["flags"]) == n)
        print(line(f"old {n}{'+' if n == 6 else ''}", {s: [C(r) for r in data[s] if keep(r)] for s in seasons}, seasons))
    print("  -- the shot-quality flags only (sq_better, sq_unlucky, opp_sq_lucky, unlucky_loss, opp_lucky_win, "
          "opp_def_lucky, we_def_unlucky, opp_3_hot) --")
    SQ = {"sq_better", "sq_unlucky", "opp_sq_lucky", "unlucky_loss", "opp_lucky_win", "opp_def_lucky", "we_def_unlucky", "opp_3_hot"}
    for n in (1, 2, 3):
        keep = (lambda r, n=n: len(r["new"] & SQ) >= n) if n == 3 else (lambda r, n=n: len(r["new"] & SQ) == n)
        print(line(f"{n}{'+' if n == 3 else ''} shot-quality flags", {s: [C(r) for r in data[s] if keep(r)] for s in seasons}, seasons))
    print("  -- today's STACK (5+ old flags), split by shot-quality flags on the same side --")
    for nm, keep in (("STACK 5+ and 1+ shot-quality flag", lambda r: len(r["flags"]) >= 5 and r["new"] & SQ),
                     ("STACK 5+ and no shot-quality flag", lambda r: len(r["flags"]) >= 5 and not r["new"] & SQ),
                     ("4 old flags + 1+ shot-quality flag", lambda r: len(r["flags"]) == 4 and r["new"] & SQ)):
        print(line(nm, {s: [C(r) for r in data[s] if keep(r)] for s in seasons}, seasons))

    print("\n=== D. OPENING-LINE STACK: only flags known in the morning (no line moves), graded at the OPEN")
    for label, fl in (("old flags minus moves", lambda r: r["flags"] - MOVES), ("old + new minus moves", lambda r: r["all"] - MOVES)):
        print(f"  [{label}]")
        for n in range(2, 8):
            keep = (lambda r, n=n: len(fl(r)) >= n) if n == 7 else (lambda r, n=n: len(fl(r)) == n)
            per = {s: [O(r) for r in data[s] if keep(r)] for s in seasons}
            perc = {s: [C(r) for r in data[s] if keep(r)] for s in seasons}
            print(line(f"{n}{'+' if n == 7 else ''} flags at the open", per, seasons) + "\n" + line("    same bets at the close", perc, seasons))

    print("\n=== E. NET STACK: our flags minus the other side's flags (old 15)  [close]")
    by_game = defaultdict(dict)
    for s in seasons:
        for r in data[s]:
            by_game[(s, r["key"])][r["side"]] = r
    for s in seasons:
        for r in data[s]:
            other = next((x for sd, x in by_game[(s, r["key"])].items() if sd != r["side"]), None)
            r["against"] = other["flags"] if other else set()
            r["against_all"] = other["all"] if other else set()
    for n in range(2, 7):
        keep = (lambda r, n=n: len(r["flags"]) - len(r["against"]) >= n) if n == 6 else \
               (lambda r, n=n: len(r["flags"]) - len(r["against"]) == n)
        print(line(f"net {n}{'+' if n == 6 else ''}", {s: [C(r) for r in data[s] if keep(r)] for s in seasons}, seasons))
    for nm, keep in (("STACK 5+, 0 flags against", lambda r: len(r["flags"]) >= 5 and not r["against"]),
                     ("STACK 5+, 1 flag against", lambda r: len(r["flags"]) >= 5 and len(r["against"]) == 1),
                     ("STACK 5+, 2+ flags against", lambda r: len(r["flags"]) >= 5 and len(r["against"]) >= 2),
                     ("4 flags, 0 against", lambda r: len(r["flags"]) == 4 and not r["against"]),
                     ("old+new: net 5+", lambda r: len(r["all"]) - len(r["against_all"]) >= 5),
                     ("old+new: net 6+", lambda r: len(r["all"]) - len(r["against_all"]) >= 6)):
        print(line(nm, {s: [C(r) for r in data[s] if keep(r)] for s in seasons}, seasons))

    totals(data, feats, seasons)


def totals(data, feats, seasons):
    """F. Game-level flags for totals. Direction per flag picked on the FIRST season only; the stack is graded on
    the SECOND season."""
    games = {}
    for s in seasons:
        for r in data[s]:
            if r["side"] != r["home"]:
                continue
            i = r.get("mi") or {}
            if i.get("t_close") is None:
                continue
            h, a = r["home"], r["opp"]
            fh, fa = feats.get((r["key"], h)), feats.get((r["key"], a))
            outs = r.get("outs") or {}
            th = r.get("th") or {}
            i2 = r.get("mi2") or {}
            f = set()
            lh, la = i.get("luck_h"), i.get("luck_a")
            if lh is not None and la is not None:
                if lh <= -2 and la <= -2:
                    f.add("both_cold")
                if lh >= 2 and la >= 2:
                    f.add("both_hot")
            if fh and fa:
                if fh["def_luck10"] <= -2 and fa["def_luck10"] <= -2:
                    f.add("both_def_lucky")        # both defenses allowed less than the shots were worth
                if fh["def_luck10"] >= 2 and fa["def_luck10"] >= 2:
                    f.add("both_def_unlucky")
                if fh["r3"] >= 0.42 and fa["r3"] >= 0.42:
                    f.add("both_3_heavy")
                if fh["rrim"] >= 0.33 and fa["rrim"] >= 0.33:
                    f.add("both_rim_heavy")
                sq_total = (fh["xpts10"] + fa["xallow10"] + fa["xpts10"] + fh["xallow10"]) / 2
                if sq_total - i["t_close"] >= 4:
                    f.add("shots_say_more")
                if i["t_close"] - sq_total >= 4:
                    f.add("shots_say_less")
            if i.get("b2b_h") and i.get("b2b_a"):
                f.add("both_b2b")
            if i.get("b2b_h") != i.get("b2b_a"):
                f.add("one_b2b")
            if (i2.get("rest_h") or 0) >= 3 and (i2.get("rest_a") or 0) >= 3:
                f.add("both_rested")
            nh, na = len(outs.get(h) or []), len(outs.get(a) or [])
            if nh >= 2 or na >= 2:
                f.add("missing_2plus")
            if nh >= 2 and na >= 2:
                f.add("both_missing_2plus")
            if th and th.get(h, 0) >= 0.15 and th.get(a, 0) >= 0.15:
                f.add("both_thin")
            if i.get("ot_h") or i.get("ot_a"):
                f.add("ot_last")
            if (i.get("crew") or 0) >= 1.5:
                f.add("over_crew")
            if (i.get("crew") or 0) <= -1.5:
                f.add("under_crew")
            if i.get("t_open") is not None and i["t_close"] - i["t_open"] >= 2:
                f.add("total_up2")
            if i.get("t_open") is not None and i["t_open"] - i["t_close"] >= 2:
                f.add("total_down2")
            if abs(r["mi2"].get("close") or 0) >= 10 if r.get("mi2") else False:
                f.add("big_spread")
            ou = {w: (i["pts"] - i[f"t_{w}"]) if i.get(f"t_{w}") is not None else None for w in ("open", "close")}
            games[(s, r["key"])] = {"season": s, "flags": f, "ou": ou}
    G = list(games.values())
    TF = sorted({x for g in G for x in g["flags"]})
    print("\n=== F. TOTALS: each game flag alone, betting the OVER (an under is the mirror)  [close | open]")
    direction = {}
    for fl in TF:
        per = {s: [g["ou"]["close"] for g in G if g["season"] == s and fl in g["flags"]] for s in seasons}
        pero = {s: [g["ou"]["open"] for g in G if g["season"] == s and fl in g["flags"] and g["ou"]["open"] is not None] for s in seasons}
        (w1, l1), _ = rec(per[seasons[0]])
        direction[fl] = "over" if w1 > l1 else "under"
        print(line(f"{fl} -> over", per, seasons) + "\n" + line("    at the open", pero, seasons))
    print(f"\n  directions picked on {seasons[0]} only: " + ", ".join(f"{k} {v}" for k, v in direction.items()))
    print(f"  stack graded on {seasons[1]} (the clean test) and, for reference, {seasons[0]} (where directions were picked)")
    for want in ("over", "under"):
        sgn = 1 if want == "over" else -1
        for n in (1, 2, 3, 4):
            def keep(g, n=n):
                pro = sum(1 for x in g["flags"] if direction.get(x) == want)
                con = sum(1 for x in g["flags"] if direction.get(x) != want)
                return pro - con >= n if n == 4 else pro - con == n
            per = {s: [sgn * g["ou"]["close"] for g in G if g["season"] == s and keep(g)] for s in seasons}
            print(line(f"{want}: net {n}{'+' if n == 4 else ''} flags its way", per, seasons))
    print("\n  pairs of totals flags (40+ games) that won BOTH seasons at 55%+ for one direction (close)")
    tested = hits = 0
    for a, b in itertools.combinations(TF, 2):
        for want, sgn in (("over", 1), ("under", -1)):
            per = {s: [sgn * g["ou"]["close"] for g in G if g["season"] == s and {a, b} <= g["flags"]] for s in seasons}
            if sum(len(v) for v in per.values()) < 40:
                continue
            tested += 1
            (w1, l1), _ = rec(per[seasons[0]]); (w2, l2), _ = rec(per[seasons[1]])
            if w1 > l1 and w2 > l2 and (w1 + w2) / max(1, w1 + w2 + l1 + l2) >= 0.55:
                hits += 1
                print(line(f"{a} + {b} -> {want}", per, seasons))
    print(f"  ({tested} tested; {hits} won both seasons at 55%+; by luck alone about {max(1, round(tested * 0.06))})")


if __name__ == "__main__":
    main()
