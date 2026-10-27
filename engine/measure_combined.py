"""One verdict per game: combine every system and the players model, instead of each betting $20 alone.

Two seasons (2024-25, 2025-26), spreads, everything at the OPENING line (what we'd actually bet).
For every game:
  - the players model's gap (live version + this season's results correction, calibrated to the
    day's openers), from the home side
  - every system that fired at the opener, and on which side (OG S1-S3, FAV T2/T12, EARLY E2-E7, TEST)

TODAY'S WAY ("separate"): every card system bets its own side, 1 unit each — OG, FAV, T13 (players
model gap 3+, not a bottom-10 team), EARLY when the players model agrees by 3+. Conflicts bet both sides.

COMBINED: one number per game — the chance the home side covers the opener:
    logit P(home covers) = a + b × players gap + w_OG × OG votes + w_FAV × FAV votes
                           + w_EARLY × EARLY votes + w_TEST × TEST votes
  (a vote = +1 for each system on the home side, −1 on the away side). Six numbers, fitted on 2024-25
  only, then frozen and tested on 2025-26. Bet the side it favours only when its chance clears a bar,
  and size by how far past the bar it is. Units at −110: win +1, loss −1.1 (per unit staked).

Run: python -m engine.measure_combined
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict

from . import backtest_open as BO
from . import personnel as P
from .measure_personnel_upgrades import LIVE, market_rank, with_correction
from .state import team_state
from .systems import evaluate, evaluate_tests, evaluate_early, group

GROUPS = ["OG", "FAV", "EARLY", "TEST"]
BREAK_EVEN = 110 / 210


def build(season):
    games, days = BO.fetch_games(season)
    lines, _ = BO.fetch_lines(season, days, "")
    preds, _ = BO.replay(season, games, lines)
    rows = with_correction(preds[LIVE], 5, 1.0)
    ranks = market_rank(rows)
    cal = {(r["date"], r["away"], r["home"]): r for r in BO.calibrate_open(rows)}
    start = BO.SEASONS[season]["start"]
    gl = [g for g, _ in games]
    by_day = defaultdict(list)
    for g in gl:
        by_day[g.game_date].append(g)
    finals, out = [], []
    for day in sorted(by_day):
        for g in by_day[day]:
            ln = lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
            op = ln.get("open")
            c = cal.get((day, g.away, g.home))
            if op is None or c is None:
                continue
            hs, as_ = team_state(g.home, finals, day), team_state(g.away, finals, day)
            picks = (evaluate(g, hs, as_, op, None) + evaluate_tests(g, hs, as_, op, None)
                     + evaluate_early(g, hs, as_, op, None, (day - start).days))
            votes = defaultdict(int)
            fired = []
            for p in picks:
                if p.bet != "spread" or p.line is None or p.system == 113:
                    continue
                gr = group(p.system)
                if gr == "SHADOW":
                    continue
                v = 1 if p.side == g.home else -1
                votes[gr] += v
                fired.append((p.system, gr, v))
            hr, ar, n = ranks.get((day, g.home, g.away), (None, None, 0))
            res = g.home_score - g.away_score + op            # > 0 home covered the opener
            out.append({"season": season, "date": day, "home": g.home, "away": g.away, "gap": c["gap"],
                        "votes": dict(votes), "fired": fired, "res": res,
                        "home_rank": hr, "away_rank": ar, "nteams": n, "day": (day - start).days})
        finals += by_day[day]
    return out


def feats(r):
    return [1.0, r["gap"]] + [float(r["votes"].get(g, 0)) for g in GROUPS]


def fit(rows, l2=1.0, iters=400, lr=0.05):
    """Plain logistic regression (no libraries), small ridge penalty so rare groups don't run wild."""
    data = [(feats(r), 1.0 if r["res"] > 0 else 0.0) for r in rows if r["res"] != 0]
    w = [0.0] * len(data[0][0])
    for _ in range(iters):
        g = [0.0] * len(w)
        for x, y in data:
            z = sum(a * b for a, b in zip(w, x))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            for i, xi in enumerate(x):
                g[i] += (p - y) * xi
        for i in range(len(w)):
            g[i] = g[i] / len(data) + (l2 * w[i] / len(data) if i else 0.0)
            w[i] -= lr * g[i] * 20
    return w


def prob(w, r):
    z = sum(a * b for a, b in zip(w, feats(r)))
    return 1 / (1 + math.exp(-z))


def units(won, stake):
    return stake if won else -1.1 * stake


def separate(rows):
    """Today's way: every card system bets its own side, 1 unit each."""
    w = l = 0
    u = 0.0
    conflicts = 0
    for r in rows:
        sides = []
        for sid, gr, v in r["fired"]:
            if gr in ("OG", "FAV"):
                sides.append(v)
            elif gr == "EARLY" and (r["gap"] if v > 0 else -r["gap"]) >= 3:
                sides.append(v)
        if abs(r["gap"]) >= 3:
            side_rank = r["home_rank"] if r["gap"] > 0 else r["away_rank"]
            if not (r["nteams"] >= 30 and side_rank and side_rank > 20):
                sides.append(1 if r["gap"] > 0 else -1)
        if 1 in sides and -1 in sides:
            conflicts += 1
        for v in sides:
            if r["res"] == 0:
                continue
            won = (r["res"] > 0) == (v > 0)
            w += won; l += not won; u += units(won, 1)
    return w, l, u, conflicts


def combined(rows, wts, bar, tiers=((0.0, 1),)):
    w = l = 0
    u = staked = 0.0
    for r in rows:
        p = prob(wts, r)
        side, q = (1, p) if p >= 0.5 else (-1, 1 - p)
        if q < bar or r["res"] == 0:
            continue
        stake = max(s for t, s in tiers if q >= bar + t)
        won = (r["res"] > 0) == (side > 0)
        w += won; l += not won; u += units(won, stake); staked += stake
    return w, l, u, staked


def show(name, w, l, u, extra=""):
    print(f"    {name:52} {w}-{l} ({w / max(w + l, 1):.1%})  {u:+.1f}u{extra}")


def main():
    data = {s: build(s) for s in BO.SEASONS}
    for s, rows in data.items():
        print(f"{s}: {len(rows)} games with an opener and a players-model gap")
    train, test = data["2024-25"], data["2025-26"]
    wts = fit(train)
    print("\nweights fitted on 2024-25 (log-odds per unit):")
    for name, v in zip(["intercept", "players gap (per pt)"] + [f"{g} vote" for g in GROUPS], wts):
        print(f"    {name:22} {v:+.4f}")
    for label_, rows in (("2024-25 (fitted here)", train), ("2025-26 (OUT OF SAMPLE)", test)):
        print(f"\n=== {label_}")
        w, l, u, c = separate(rows)
        show("TODAY'S WAY: every system bets alone, 1u each", w, l, u, f"  ({c} games with bets on both sides)")
        for bar in (0.53, 0.54, 0.55, 0.56, 0.58):
            w, l, u, st = combined(rows, wts, bar)
            show(f"COMBINED, flat 1u, bet when chance ≥ {bar:.0%}", w, l, u, f"  ({st:.0f}u staked)")
        for bar in (0.53, 0.54):
            tiers = ((0.0, 1), (0.03, 2), (0.06, 3))
            w, l, u, st = combined(rows, wts, bar, tiers)
            show(f"COMBINED, ≥{bar:.0%}: 1u, +3 pts 2u, +6 pts 3u", w, l, u, f"  ({st:.0f}u staked, {u / max(st, 1):+.1%} per unit)")
    # calibration check out of sample: does a 56% call win 56%?
    print("\n=== CALIBRATION, 2025-26 (does the combined chance mean what it says?)")
    b = defaultdict(lambda: [0, 0])
    for r in test:
        if r["res"] == 0:
            continue
        p = prob(wts, r)
        q, won = (p, r["res"] > 0) if p >= 0.5 else (1 - p, r["res"] < 0)
        k = "50-52%" if q < .52 else "52-54%" if q < .54 else "54-56%" if q < .56 else "56-58%" if q < .58 else "58%+"
        b[k][0] += won; b[k][1] += 1
    for k in ("50-52%", "52-54%", "54-56%", "56-58%", "58%+"):
        wn, n = b[k]
        print(f"    model says {k:7} → won {wn}/{n} ({wn / max(n, 1):.1%})")
    (P.STATIC / "combined_weights.json").write_text(json.dumps(dict(zip(
        ["intercept", "gap"] + GROUPS, wts))))


if __name__ == "__main__":
    main()
