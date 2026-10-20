"""Replay the 2025-26 season through the personnel model and grade it against the closing line.

No peeking at the season being predicted:
  player priors   = 2024-25 only (BPM with the small-sample pull, role mpg)        [no 2025-26 numbers]
  rookie prior    = measured from the 2024 draft class's rookie year only
  in-season       = each player's box impact from games BEFORE the game being priced
  who plays       = the players who actually played that night (= day-to-day statuses resolved)
Known small leaks, stated: the box-score→BPM formula was fit on 2025-26 per-100 stats.

For every game it prices several versions of the model and reports, for each:
  - margin error (RMSE) of the model alone, and of the closing line
  - INFO BEYOND THE MARKET: regress (actual margin - market margin) on (model - market).
    w > 0 with a real t-stat means the model knows something the line doesn't.
    Fit on games before Jan 1, tested on games after (out of sample).
  - ATS record by size of disagreement, out of sample, using the blended edge
"""
from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from . import boxscore, sources
from . import personnel as P

SUM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={}"
START, END, SPLIT = date(2025, 10, 21), date(2026, 4, 12), date(2026, 1, 1)


# ---------------------------------------------------------------- data
def fetch_season():
    days = [START + timedelta(i) for i in range((END - START).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        games = [g for day in ex.map(lambda d: _safe(sources.espn_day, d) or [], days) for g, _ in day if g.final]

    def one(g):
        js = _safe(sources.get_json, SUM.format(g.id))
        if not js:
            return g, None, []
        spread = None
        for pc in js.get("pickcenter") or []:
            if pc.get("spread") is not None:
                spread = float(pc["spread"])
                break
        return g, spread, boxscore.parse_summary(js, g.id, g.game_date.isoformat())
    with ThreadPoolExecutor(12) as ex:
        return list(ex.map(one, games))


def _safe(f, *a):
    try:
        return f(*a)
    except Exception:
        return None


def priors():
    prev = P._read(P.DATA_PREV)                       # 2024-25 only
    out = {}
    for k, r in prev.items():
        mp, g = r["mp"], max(r["g"], 1)
        out[k] = {"bpm": (r["bpm"] * mp + P.BASELINE * P.PULL) / (mp + P.PULL),
                  "role": min(mp / g, P.MIN_CAP) * min(1.0, g / P.ROLE_GAMES), "kind": "veteran"}
    # rookie prior from the 2024 class's rookie year (2024-25), by pick tier
    rows = [r for r in csv.DictReader(open(P.DRAFTS, encoding="utf-8"), delimiter=";")]
    tiers = {}
    for lo, hi in P.PICK_TIERS:
        t = [r for r in rows if r["year"] == "2024" and lo <= int(r["pick"]) <= hi]
        recs = [prev.get(P.norm(r["name"])) for r in t]
        played = [x for x in recs if x and x["mp"] >= 100]
        mins = sum(x["mp"] for x in played)
        bpm = sum(x["bpm"] * x["mp"] for x in played) / mins if mins else P.BASELINE
        tiers[(lo, hi)] = {"bpm": bpm, "role": sum(x["mp"] for x in recs if x) / 82 / max(len(t), 1)}
    for r in rows:
        if r["year"] == "2025":
            for (lo, hi), v in tiers.items():
                if lo <= int(r["pick"]) <= hi:
                    out[P.norm(r["name"])] = {**v, "kind": "rookie"}
    return out, tiers


# ---------------------------------------------------------------- model
def team_rating(players, prior, live, cfg):
    """players: [(espn_id, name)] who played tonight."""
    rows = []
    for pid, name in players:
        pr = prior.get(P.norm(name)) or _fuzzy(prior, name)
        kind = pr["kind"] if pr else "none"
        b0 = pr["bpm"] if pr else P.BASELINE
        role0 = pr["role"] if pr else 0.0
        lv = live.get(pid)
        w = P.PRIOR_MIN[kind] * cfg["prior_scale"]
        if lv and lv["min"] > 0:
            b = (b0 * w + lv["bpm_live"] * lv["min"]) / (w + lv["min"])
            if cfg["recent"]:
                m, gms = lv["w_min"], lv["w_games"]
            else:
                m, gms = lv["min"], lv["games"]
            role = min((role0 * cfg["prior_games"] + m) / (cfg["prior_games"] + gms), P.MIN_CAP)
        else:
            b, role = b0, role0
        rows.append((b, role))
    if cfg["minutes"] == "topdown":
        left, tot = 240.0, 0.0
        for b, role in sorted(rows, key=lambda r: -r[1]):
            m = min(role, left)
            left -= m
            tot += b * m / 48
        return tot + (left * cfg["fill"] / 48 if left > 0 else 0)
    total = sum(r for _, r in rows)
    sc = 240 / total if total > 240 else 1.0
    left = max(0.0, 240 - total * sc)
    return sum(b * r * sc / 48 for b, r in rows) + left * cfg["fill"] / 48


_FZ = {}
def _fuzzy(prior, name):
    if name not in _FZ:
        _FZ[name] = P.find(prior, name)
    return _FZ[name]


def run(cfgs, data):
    prior, tiers = priors()
    data = sorted([d for d in data if d[2]], key=lambda d: (d[0].game_date, d[0].id))
    hist = []                              # box rows seen so far
    last_played = {}
    out = {name: [] for name in cfgs}
    by_date = defaultdict(list)
    for d in data:
        by_date[d[0].game_date].append(d)
    for day in sorted(by_date):
        live = boxscore.season_impact(hist) if hist else {}
        for g, spread, rows in by_date[day]:
            ppl = defaultdict(list)
            for r in rows:
                ppl[r["team"]].append((r["espn_id"], r["name"]))
            rest = {t: (day - last_played[t]).days - 1 if t in last_played else None for t in (g.home, g.away)}
            for name, cfg in cfgs.items():
                h = team_rating(ppl[g.home], prior, live, cfg)
                a = team_rating(ppl[g.away], prior, live, cfg)
                out[name].append({"date": day, "pred": h - a + cfg["hc"], "spread": spread,
                                  "actual": g.home_score - g.away_score,
                                  "b2b_home": rest[g.home] == 0, "b2b_away": rest[g.away] == 0})
        for g, spread, rows in by_date[day]:
            last_played[g.home] = last_played[g.away] = day
            hist += rows
    return out, tiers


# ---------------------------------------------------------------- grading
def ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return 0, 0, 0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = [y - a - b * x for x, y in zip(xs, ys)]
    se = math.sqrt(sum(r * r for r in resid) / (n - 2) / sxx)
    return a, b, b / se if se else 0


def grade(rows, b2b_coef=0.0):
    rows = [r for r in rows if r["spread"] is not None]
    def mkt(r):
        return -r["spread"]
    def model(r):
        return r["pred"] - b2b_coef * (r["b2b_home"] - r["b2b_away"])
    rmse = lambda f, rs: math.sqrt(sum((r["actual"] - f(r)) ** 2 for r in rs) / len(rs))
    train = [r for r in rows if r["date"] < SPLIT]
    test = [r for r in rows if r["date"] >= SPLIT]
    out = {"n": len(rows), "n_train": len(train), "n_test": len(test),
           "rmse_model": rmse(model, rows), "rmse_market": rmse(mkt, rows)}
    for label, rs in (("all", rows), ("train", train), ("test", test)):
        a, w, t = ols([model(r) - mkt(r) for r in rs], [r["actual"] - mkt(r) for r in rs])
        out[f"w_{label}"], out[f"t_{label}"] = w, t
    # out of sample ATS: blend weight from train, graded on test
    _, w, _ = ols([model(r) - mkt(r) for r in train], [r["actual"] - mkt(r) for r in train])
    buckets = defaultdict(lambda: [0, 0, 0])
    for r in test:
        raw = model(r) - mkt(r)
        edge = w * raw
        res = r["actual"] - mkt(r)          # >0 home covered
        if res == 0:
            continue
        won = (res > 0) == (edge > 0)
        for lo in (0, 1, 2, 3, 4, 5):
            if abs(raw) >= lo:
                buckets[lo][0 if won else 1] += 1
    out["ats_test_by_raw_gap"] = {k: v[:2] for k, v in sorted(buckets.items())}
    return out


PERIODS = [("Oct-Nov", date(2025, 10, 1), date(2025, 12, 1)), ("Dec", date(2025, 12, 1), date(2026, 1, 1)),
           ("Jan-Feb", date(2026, 1, 1), date(2026, 3, 1)), ("Mar-Apr", date(2026, 3, 1), date(2026, 5, 1))]


def calibrated(rows):
    """Exactly what the board does: each day, fit market = a + b*model over that day's games (6+),
    gap = market line vs calibrated model line."""
    by = defaultdict(list)
    for r in rows:
        if r["spread"] is not None:
            by[r["date"]].append(r)
    out = []
    for day, rs in by.items():
        if len(rs) < 6:
            continue
        a, b, _ = ols([r["pred"] for r in rs], [-r["spread"] for r in rs])
        for r in rs:
            out.append({**r, "cal_gap": (a + b * r["pred"]) - (-r["spread"])})
    return out


def ats_table(rows, key):
    lines = []
    for name, lo_d, hi_d in PERIODS:
        rs = [r for r in rows if lo_d <= r["date"] < hi_d]
        cells = []
        for lo in (0, 2, 3, 4, 5):
            w = l = 0
            for r in rs:
                g = key(r)
                res = r["actual"] + r["spread"]
                if res == 0 or abs(g) < lo or g == 0:
                    continue
                if (res > 0) == (g > 0):
                    w += 1
                else:
                    l += 1
            cells.append(f"{lo}+: {w}-{l}" + (f" ({w/(w+l):.0%})" if w + l else ""))
        lines.append(f"    {name:8} " + "  ".join(cells))
    return lines


def main():
    data = fetch_season()
    base = {"minutes": "prop", "prior_scale": 1.0, "recent": True, "prior_games": 3, "hc": 2.0, "fill": 0.0}
    cfgs = {
        "board (prop minutes)": base,
        "top-down minutes": {**base, "minutes": "topdown"},
        "top-down, bench fill": {**base, "minutes": "topdown", "fill": P.BASELINE},
        "prior worth half": {**base, "prior_scale": 0.5},
        "prior worth double": {**base, "prior_scale": 2.0},
        "top-down + prior half": {**base, "minutes": "topdown", "prior_scale": 0.5},
        "top-down + prior double": {**base, "minutes": "topdown", "prior_scale": 2.0},
        "no recent weighting": {**base, "recent": False},
        "prior only (no in-season)": {**base, "prior_scale": 1e9},
    }
    preds, tiers = run(cfgs, data)
    n_box = sum(1 for d in data if d[2])
    n_sp = sum(1 for d in data if d[1] is not None)
    print(f"2025-26 games replayed: {n_box} with box scores, {n_sp} with a closing spread")
    print("rookie prior (2024 class): " + " | ".join(f"{lo}-{hi}: BPM {v['bpm']:+.1f}, {v['role']:.0f} mpg"
                                                    for (lo, hi), v in tiers.items()))
    hm = [r["actual"] for r in next(iter(preds.values()))]
    print(f"home margin, all games: mean {sum(hm)/len(hm):+.2f}")
    # measure the back-to-back effect the model doesn't see: residual vs market by rest (train half)
    rows0 = [r for r in preds["board (prop minutes)"] if r["spread"] is not None and r["date"] < SPLIT]
    xs = [r["b2b_home"] - r["b2b_away"] for r in rows0]
    ys = [r["actual"] - r["pred"] for r in rows0]
    _, b2b, tb = ols(xs, ys)
    b2b = -b2b
    print(f"back-to-back effect the model misses (train half, actual - model on B2B diff): {b2b:+.2f} pts (t {tb:.1f})")
    print()
    print(f"{'version':28} {'RMSE model':>10} {'RMSE mkt':>9} {'w all':>6} {'t':>5} {'w train':>8} {'t':>5} {'w test':>7} {'t test':>6}   ATS out of sample (test half) by raw gap: W-L")
    for name, rows in preds.items():
        for tag, coef in (("", 0.0), (" +B2B", b2b)):
            gr = grade(rows, coef)
            ats = "  ".join(f"{k}+: {w}-{l} ({w/(w+l):.1%})" if w + l else f"{k}+: -" for k, (w, l) in gr["ats_test_by_raw_gap"].items())
            print(f"{(name + tag):28} {gr['rmse_model']:10.2f} {gr['rmse_market']:9.2f} {gr['w_all']:6.2f} {gr['t_all']:5.1f} "
                  f"{gr['w_train']:8.2f} {gr['t_train']:5.1f} {gr['w_test']:7.2f} {gr['t_test']:6.1f}   {ats}")
    print()
    print("ATS by month, betting the side the model likes (no fitting needed: sign of the gap only)")
    for name in ("board (prop minutes)", "top-down, bench fill", "top-down + prior half", "prior only (no in-season)"):
        rows = [r for r in preds[name] if r["spread"] is not None]
        print(f"  {name} — raw gap (model margin vs market margin)")
        for ln in ats_table(rows, lambda r: r["pred"] + r["spread"]):
            print(ln)
        cal = calibrated(rows)
        print(f"  {name} — calibrated gap, exactly like the board's T13 ({len(cal)} games on 6+ game days)")
        for ln in ats_table(cal, lambda r: r["cal_gap"]):
            print(ln)


if __name__ == "__main__":
    main()
