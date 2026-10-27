"""Walk-forward test of the mined systems (T21-T25) and S4 with a season-average total.

Caden 2026-10-27: test T21-T25 honestly, and test S4 with "above this season's average total" in
place of the fixed 220.

PART 1 — would we have found T21-T25 without seeing the last two seasons?
  Re-run the same search (engine/mine.py rules) on 2020-21..2023-24 ONLY, then grade on 2024-25 and
  2025-26, which the search never saw. Reported at the close (6 seasons) and at the open (last 2).
PART 2 — how much does a mined record shrink out of sample? Every rule the 4-season search finds,
  graded on the 2 unseen seasons. shrink = (unseen win% − 50%) / (found win% − 50%). This is the
  measured number the bet pricer should use instead of a mined record at face value.
PART 3 — S4 variants, every season, at the close (6 seasons) and at the open (last 2):
  current (total > 220), total > this season's average so far, no total filter.
All "this season so far" numbers use only games already played (no look-ahead).

Run: python -m engine.measure_walkforward
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import mine as M
from .personnel import STATIC

TRAIN = ["2020-21", "2021-22", "2022-23", "2023-24"]
TEST = ["2024-25", "2025-26"]


def fmt(w, l):
    return f"{w}-{l} ({w / max(w + l, 1):.1%}, {w - 1.1 * l:+.1f}u)" if w + l else "0-0"


def opens(season):
    tag = season.replace("-", "_")
    sp, tt = STATIC / f"odds_openclose_{tag}.json", STATIC / f"odds_totals_{tag}.json"
    if not sp.exists():
        return {}, {}
    return ({k: v.get("open") for k, v in json.loads(sp.read_text()).items()},
            {k: v.get("open") for k, v in json.loads(tt.read_text()).items()})


def match(row, flags):
    return all(row.get(f) for f in flags)


# the live rules, written as miner flags
MINED = {
    "T21 late-season mismatch over": ("total", ["G:last21", "G:mismatch"], "bet"),
    "T22 late-season low total over (season so far)": ("total", ["G:last21", "G:tot_low_sofar"], "bet"),
    "T22 as mined (whole-season quartile, looks ahead)": ("total", ["G:last21", "G:tot_low"], "bet"),
    "T23 post-ASB mismatch, home 4-in-6 over": ("total", ["G:post_asb", "G:mismatch", "H:4in6"], "bet"),
    "T24 fade OT winner on 4-in-6": ("spread", ["O:4in6", "O:won_last", "O:ot_last"], "bet"),
    "T25 fade the tanker, last 3 weeks": ("spread", ["G:last21", "O:tank35"], "bet"),
}


def grade_close(rows, flags, side, extra=None):
    out = defaultdict(lambda: [0, 0])
    for r, won, season in rows:
        if match(r, flags) and (extra is None or extra(r)):
            ok = won if side == "bet" else not won
            out[season][0 if ok else 1] += 1
    return out


def grade_open(rows, kind, flags, side, op_sp, op_tt, extra=None):
    """Same rule, graded at the opening number (2024-25 and 2025-26 only)."""
    out = defaultdict(lambda: [0, 0])
    for r, _, season in rows:
        if season not in TEST or not match(r, flags) or (extra is not None and not extra(r)):
            continue
        if kind == "total":
            o = op_tt[season].get(r["_key"])
            if o is None or r["_pts"] == o:
                continue
            ok = (r["_pts"] > o) == (side == "bet")
        else:
            o = op_sp[season].get(r["_key"])
            if o is None:
                continue
            line = o if r["_home"] else -o
            res = (r["_margin"] if r["_home"] else -r["_margin"]) + line
            if res == 0:
                continue
            ok = (res > 0) == (side == "bet")
        out[season][0 if ok else 1] += 1
    return out


def show(name, close, open_):
    per = " | ".join(f"{s}: {fmt(*close[s])}" for s in M.SEASONS)
    tr = [sum(close[s][i] for s in TRAIN) for i in (0, 1)]
    te = [sum(close[s][i] for s in TEST) for i in (0, 1)]
    to = [sum(open_[s][i] for s in TEST) for i in (0, 1)]
    print(f"  {name}\n      2020-24 (found on): {fmt(*tr)}   2024-26 unseen, close: {fmt(*te)}   "
          f"2024-26 unseen, OPEN: {fmt(*to)}\n      by season (close): {per}")


def main():
    spread_rows, total_rows = [], []
    for season in M.SEASONS:
        games, start, end, days = M.games_for(season)
        lines, how = M.closing_lines(season, days, "")
        sr, tr = M.build(season, games, lines, start, end)
        spread_rows += sr
        total_rows += tr
        print(f"{season}: {len(games)} games, lines {how}; {len(sr)} spread rows, {len(tr)} totals rows")
    op_sp, op_tt = {}, {}
    for s in TEST:
        op_sp[s], op_tt[s] = opens(s)
    rows_of = {"spread": spread_rows, "total": total_rows}

    print("\n" + "=" * 100)
    print("PART 1 — T21-T25: found on 2020-24, graded on 2024-26 (never seen)")
    print("=" * 100)
    for name, (kind, flags, side) in MINED.items():
        rows = rows_of[kind]
        show(name, grade_close(rows, flags, side), grade_open(rows, kind, flags, side, op_sp, op_tt))

    # re-run the search on the 4 training seasons only (same rules, minimum games scaled to 4 seasons)
    all_seasons, all_min = M.SEASONS, M.MIN_TOTAL_N
    M.SEASONS = {s: all_seasons[s] for s in TRAIN}
    M.MIN_TOTAL_N = round(all_min * 4 / 6)
    found = {}
    for kind, rows in rows_of.items():
        train = [r for r in rows if r[2] in TRAIN]
        found[kind] = M.search(train, kind)
    M.SEASONS, M.MIN_TOTAL_N = all_seasons, all_min
    print("\n  Would the 4-season search have found them? (same flags, any extra flags allowed)")
    for name, (kind, flags, side) in MINED.items():
        hits = [f for f in found[kind] if f["side"] == side and set(flags) <= set(f["flags"])]
        exact = any(set(f["flags"]) == set(flags) for f in hits)
        print(f"    {name:52} {'FOUND exactly' if exact else 'found a narrower version' if hits else 'NOT found'}")

    print("\n" + "=" * 100)
    print("PART 2 — how much a mined record holds up on seasons it never saw")
    print("=" * 100)
    for kind, rows in rows_of.items():
        fs = found[kind]
        test_rows = [r for r in rows if r[2] in TEST]
        ins_w = ins_n = out_w = out_n = 0
        per_rule = []
        for f in fs:
            g = grade_close(test_rows, f["flags"], f["side"])
            w = sum(g[s][0] for s in TEST); l = sum(g[s][1] for s in TEST)
            ins_w += f["w"]; ins_n += f["w"] + f["l"]; out_w += w; out_n += w + l
            per_rule.append((f["pct"], w / (w + l) if w + l else None, w + l))
        if not fs:
            print(f"  {kind}: the 4-season search found nothing")
            continue
        ip, op = ins_w / ins_n, out_w / max(out_n, 1)
        print(f"  {kind}: {len(fs)} rules found on 2020-24. Found at {ip:.1%} (bet-weighted); on 2024-26 they went "
              f"{out_w}-{out_n - out_w} ({op:.1%}).  shrink = {(op - 0.5) / (ip - 0.5):.2f} "
              f"(share of the edge that survives)")
        better = sum(1 for _, o, n in per_rule if o is not None and o > 0.524)
        print(f"      {better} of {len(per_rule)} rules were still winners after the vig on the unseen seasons")
    print("\n  (Note: rules overlap heavily, so the bet-weighted average counts the same games many times.)")

    print("\n" + "=" * 100)
    print("PART 3 — S4 heavy favorite over: which total filter")
    print("=" * 100)
    def s4(r, tot_rule):
        hs, tot = r["_hs"], r["_tot"]
        if hs is None or abs(hs) <= 9:
            return False
        fav, dog = ("H", "A") if hs < 0 else ("A", "H")
        if not (r.get(f"{fav}:won_last") and r.get(f"{dog}:lost_last")):
            return False
        return tot_rule(r)
    variants = {
        "S4 now: total > 220": lambda r: r["_tot"] > 220,
        "S4: total > this season's average so far": lambda r: bool(r.get("G:tot_above_avg")),
        "S4: no total filter": lambda r: True,
        "S4: total at or below this season's average": lambda r: r.get("G:tot_above_avg") is False,
    }
    for name, rule in variants.items():
        ex = lambda r, rule=rule: s4(r, rule)
        show(name, grade_close(total_rows, [], "bet", ex), grade_open(total_rows, "total", [], "bet", op_sp, op_tt, ex))
    print("\n  League average closing total by season (how far 220 has drifted):")
    for s in M.SEASONS:
        ts = [r["_tot"] for r, _, ss in total_rows if ss == s]
        print(f"    {s}: average {sum(ts) / len(ts):.1f}, share of games above 220: {sum(t > 220 for t in ts) / len(ts):.0%}")


if __name__ == "__main__":
    main()
