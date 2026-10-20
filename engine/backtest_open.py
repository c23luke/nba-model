"""Grade the personnel model the way it is actually bet: at the FIRST line the board would see.

Two seasons, 2024-25 and 2025-26, each replayed with only what was known before it:
  priors = the season before only; rookie prior = the previous draft class's rookie year;
  in-season = each player's box impact from earlier games; who plays = who actually played.

Lines (Odds API consensus = median of US books), per game:
  open  = earliest of: 7:30pm ET the night before, 10am ET game day   (when the board first sees it)
  close = 6:30pm ET game day
For each game the model's gap is calibrated to that day's opening lines (like the board), and
the side it likes is graded:
  - against the opening line (what we'd actually bet)
  - CLV: how many points the line moved our way from open to close
  - against the close (for reference)
plus: does the market MOVE toward the model? (regress open→close move on model-minus-open)
"""
from __future__ import annotations

import csv
import json
import math
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from . import backtest as BT
from . import boxscore, sources
from . import personnel as P

SEASONS = {
    "2024-25": {"start": date(2024, 10, 22), "end": date(2025, 4, 13), "prior": "players_2023_24.csv",
                "measure": ("drafts_2023.csv", "2023"), "rookies": ("drafts_2024_2025.csv", "2024")},
    "2025-26": {"start": date(2025, 10, 21), "end": date(2026, 4, 12), "prior": "players_2024_25.csv",
                "measure": ("drafts_2024_2025.csv", "2024"), "rookies": ("drafts_2024_2025.csv", "2025")},
}
VERSIONS = {
    "live (top-down, bench fill, B2B)": {"minutes": "topdown", "prior_scale": 1.0, "recent": True,
                                         "prior_games": 3, "hc": P.HOME_COURT, "fill": P.BASELINE, "b2b": P.B2B},
    "old board (even shrink)": {"minutes": "prop", "prior_scale": 1.0, "recent": True,
                                "prior_games": 3, "hc": 2.0, "fill": 0.0, "b2b": 0.0},
}
WINDOWS = [("days 0-30", 0, 30), ("days 31-71 (to ~Dec 31)", 31, 71), ("days 72-130", 72, 130),
           ("days 131+", 131, 999)]


def priors(season):
    cfg = SEASONS[season]
    prev = P._read(P.STATIC / cfg["prior"])
    out = {}
    for k, r in prev.items():
        mp, g = r["mp"], max(r["g"], 1)
        out[k] = {"bpm": (r["bpm"] * mp + P.BASELINE * P.PULL) / (mp + P.PULL),
                  "role": min(mp / g, P.MIN_CAP) * min(1.0, g / P.ROLE_GAMES), "kind": "veteran"}
    def rows(fname, year):
        return [r for r in csv.DictReader(open(P.STATIC / fname, encoding="utf-8"), delimiter=";")
                if r["year"] == year]
    meas = rows(*cfg["measure"])
    tiers = {}
    for lo, hi in P.PICK_TIERS:
        t = [r for r in meas if lo <= int(r["pick"]) <= hi]
        recs = [prev.get(P.norm(r["name"])) or P.find(prev, r["name"]) for r in t]
        played = [x for x in recs if x and x["mp"] >= 100]
        mins = sum(x["mp"] for x in played)
        tiers[(lo, hi)] = {"bpm": sum(x["bpm"] * x["mp"] for x in played) / mins if mins else P.BASELINE,
                           "role": sum(x["mp"] for x in recs if x) / 82 / max(len(t), 1)}
    for r in rows(*cfg["rookies"]):
        for (lo, hi), v in tiers.items():
            if lo <= int(r["pick"]) <= hi:
                out[P.norm(r["name"])] = {**v, "kind": "rookie"}
    return out, tiers


def fetch_games(season):
    cfg = SEASONS[season]
    days = [cfg["start"] + timedelta(i) for i in range((cfg["end"] - cfg["start"]).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        games = [g for day in ex.map(lambda d: BT._safe(sources.espn_day, d) or [], days)
                 for g, _ in day if g.final]
    def one(g):
        js = BT._safe(sources.get_json, BT.SUM.format(g.id))
        return g, (boxscore.parse_summary(js, g.id, g.game_date.isoformat()) if js else [])
    with ThreadPoolExecutor(12) as ex:
        return list(ex.map(one, games)), days


def fetch_lines(season, days, key):
    cache = P.STATIC / f"odds_openclose_{season.replace('-', '_')}.json"
    if cache.exists():
        return json.loads(cache.read_text()), "cached"
    times = []
    for d in days:
        times += [((d - timedelta(1)).isoformat() + "T23:30:00Z", "eve", d),
                  (d.isoformat() + "T14:00:00Z", "morn", d),
                  (d.isoformat() + "T22:30:00Z", "close", d)]
    def snap(t):
        try:
            return t, sources.odds_api_historical(key, t[0])
        except Exception as e:
            return t, ({}, {"error": str(e)})
    out, left, errs = {}, None, 0
    with ThreadPoolExecutor(6) as ex:
        for (iso, kind, d), (lines, meta) in ex.map(snap, times):
            left = meta.get("remaining") or left
            errs += "error" in meta
            for (gd, away, home), ln in lines.items():
                if ln.get("home_spread") is None:
                    continue
                k = f"{gd.isoformat()}|{away}|{home}"
                rec = out.setdefault(k, {})
                # only snapshots on/just before the game day count (no week-old lines)
                if kind in ("eve", "morn") and gd == d:
                    rec.setdefault(kind, ln["home_spread"])
                elif kind == "close" and gd == d:
                    rec["close"] = ln["home_spread"]
    for rec in out.values():
        rec["open"] = rec.get("eve", rec.get("morn", rec.get("close")))
        rec["open_at"] = "eve" if "eve" in rec else "morn" if "morn" in rec else "close"
    cache.write_text(json.dumps(out))
    return out, f"fetched now ({len(times)} snapshots, {errs} errors, credits left {left})"


def replay(season, games, lines):
    prior, tiers = priors(season)
    start = SEASONS[season]["start"]
    data = sorted([(g, rows) for g, rows in games if rows], key=lambda d: (d[0].game_date, d[0].id))
    by_date = defaultdict(list)
    for d in data:
        by_date[d[0].game_date].append(d)
    hist, last, out = [], {}, {v: [] for v in VERSIONS}
    for day in sorted(by_date):
        live = boxscore.season_impact(hist) if hist else {}
        for g, rows in by_date[day]:
            ln = lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
            ppl = defaultdict(list)
            for r in rows:
                ppl[r["team"]].append((r["espn_id"], r["name"]))
            hb = last.get(g.home) == day - timedelta(1)
            ab = last.get(g.away) == day - timedelta(1)
            for vname, cfg in VERSIONS.items():
                h = BT.team_rating(ppl[g.home], prior, live, cfg)
                a = BT.team_rating(ppl[g.away], prior, live, cfg)
                out[vname].append({"day": (day - start).days, "date": day, "season": season,
                                   "away": g.away, "home": g.home,
                                   "pred": h - a + cfg["hc"] - cfg["b2b"] * hb + cfg["b2b"] * ab,
                                   "open": ln.get("open"), "close": ln.get("close"), "open_at": ln.get("open_at"),
                                   "actual": g.home_score - g.away_score})
        for g, rows in by_date[day]:
            last[g.home] = last[g.away] = day
            hist += rows
    return out, tiers


def calibrate_open(rows):
    """Like the board: each day, market = a + b*model on that day's opening lines (6+ games)."""
    by = defaultdict(list)
    for r in rows:
        if r["open"] is not None and r["close"] is not None:
            by[r["date"]].append(r)
    out = []
    for day, rs in by.items():
        if len(rs) < 6:
            continue
        a, b, _ = BT.ols([r["pred"] for r in rs], [-r["open"] for r in rs])
        for r in rs:
            out.append({**r, "gap": (a + b * r["pred"]) + r["open"]})   # >0 = model likes home vs open
    return out


def grade(rows, lo_gap):
    w = l = 0
    wc = lc = 0
    clv = []
    for r in rows:
        g = r["gap"]
        if abs(g) < lo_gap or g == 0:
            continue
        home = g > 0
        res_open = r["actual"] + r["open"]
        if res_open != 0:
            w, l = (w + 1, l) if (res_open > 0) == home else (w, l + 1)
        res_close = r["actual"] + r["close"]
        if res_close != 0:
            wc, lc = (wc + 1, lc) if (res_close > 0) == home else (wc, lc + 1)
        # line moved our way: betting home at open -3, close -5 → +2 for us
        clv.append((r["open"] - r["close"]) if home else (r["close"] - r["open"]))
    pos = sum(c > 0 for c in clv)
    neg = sum(c < 0 for c in clv)
    return {"w": w, "l": l, "wc": wc, "lc": lc, "n": len(clv),
            "clv": sum(clv) / len(clv) if clv else None, "clv_pos": pos, "clv_neg": neg}


def fmt(g):
    if not g["n"]:
        return "-"
    pct = f"{g['w']/(g['w']+g['l']):.0%}" if g["w"] + g["l"] else "-"
    return (f"{g['w']}-{g['l']} ({pct}) vs open | CLV {g['clv']:+.2f} pts, moved our way {g['clv_pos']}"
            f" / against {g['clv_neg']} | vs close {g['wc']}-{g['lc']}")


def main():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    allrows = {v: [] for v in VERSIONS}
    for season in SEASONS:
        games, days = fetch_games(season)
        lines, how = fetch_lines(season, days, key)
        preds, tiers = replay(season, games, lines)
        n_open = sum(1 for r in next(iter(preds.values())) if r["open"] is not None)
        eve = sum(1 for v in lines.values() if v.get("open_at") == "eve")
        print(f"=== {season}: {len(games)} games, {n_open} with an opening line ({eve} posted the night before); lines {how}")
        print("    rookie prior: " + " | ".join(f"{lo}-{hi}: {v['bpm']:+.1f}, {v['role']:.0f} mpg" for (lo, hi), v in tiers.items()))
        for vname, rows in preds.items():
            allrows[vname] += rows
            cal = calibrate_open(rows)
            # does the market move toward the model? (open→close move on model-minus-open, all games)
            xs = [r["gap"] for r in cal]
            ys = [(-r["close"]) - (-r["open"]) for r in cal]       # move in home margin terms
            _, bmove, tmove = BT.ols(xs, ys)
            print(f"  {vname}: market moves {bmove:+.3f} pts toward the model per 1 pt of gap (t {tmove:.1f}, {len(cal)} games)")
            for wname, lo_d, hi_d in WINDOWS:
                ws = [r for r in cal if lo_d <= r["day"] <= hi_d]
                print(f"    {wname:24} " + "   ".join(f"{t}+: {fmt(grade(ws, t))}" for t in (3, 4)))
        print()
    print("=== BOTH SEASONS")
    blob = {}
    for vname, rows in allrows.items():
        cal = calibrate_open(rows)
        xs = [r["gap"] for r in cal]
        ys = [(-r["close"]) - (-r["open"]) for r in cal]
        _, bmove, tmove = BT.ols(xs, ys)
        _, binfo, tinfo = BT.ols(xs, [r["actual"] + r["open"] for r in cal])
        print(f"  {vname}: market moves {bmove:+.3f}/pt toward model (t {tmove:.1f}); "
              f"result beats the open by {binfo:+.3f}/pt of gap (t {tinfo:.1f}); {len(cal)} games")
        blob[vname] = {}
        for wname, lo_d, hi_d in WINDOWS + [("whole season", 0, 999)]:
            ws = [r for r in cal if lo_d <= r["day"] <= hi_d]
            blob[vname][wname] = {}
            cells = []
            for t in (0, 2, 3, 4, 5):
                g = grade(ws, t)
                blob[vname][wname][str(t)] = g
                cells.append(f"{t}+: {fmt(g)}")
            print(f"    {wname}")
            for c in cells:
                print(f"        {c}")
    # every game's personnel gap (live version, calibrated to that day's openers) for other replays to join on
    gaps = {f"{r['date'].isoformat()}|{r['away']}|{r['home']}": {"gap": round(r["gap"], 2), "day": r["day"]}
            for r in calibrate_open(allrows["live (top-down, bench fill, B2B)"])}
    (P.STATIC / "personnel_gaps.json").write_text(json.dumps(gaps))
    print(f"\nsaved personnel gaps for {len(gaps)} games")
    blob["confidence"] = by_confidence(allrows)
    blob["buckets"] = by_bucket(allrows["live (top-down, bench fill, B2B)"])
    (P.STATIC / "backtest_open.json").write_text(json.dumps(blob))


BUCKETS = [("0-2", 0, 2), ("2-3", 2, 3), ("3-4", 3, 4), ("4-5", 4, 5), ("5+", 5, 99)]


def by_bucket(rows):
    """Gap size as separate buckets (not 'or more'), per stage of the season."""
    cal = calibrate_open(rows)
    out = {}
    print("\n=== BY GAP SIZE (separate buckets), live version, vs the opening line")
    for wname, lo_d, hi_d in WINDOWS + [("whole season", 0, 999)]:
        ws = [r for r in cal if lo_d <= r["day"] <= hi_d]
        out[wname] = {}
        print(f"    {wname}")
        for name, lo, hi in BUCKETS:
            g = grade([r for r in ws if lo <= abs(r["gap"]) < hi], 0)
            out[wname][name] = g
            print(f"        {name:4} {fmt(g)}")
    return out


def by_confidence(allrows):
    """The board's confidence check, replayed: gap 3+ in the live version, then re-priced with bench
    minutes spread evenly (the stress test that most often drops a bet to Low).
      High   = both versions 4.5+ on the same side
      Medium = both 3+ on the same side
      Low    = live 3+, but the even-shrink version under 3 (or on the other side)
    The live board also stress-tests the injury penalty; history can't (box scores show who played)."""
    live = calibrate_open(allrows["live (top-down, bench fill, B2B)"])
    alt = calibrate_open(allrows["old board (even shrink)"])
    groups = {"High": [], "Medium": [], "Low": []}
    paired = 0
    for a, b in zip(live, alt):
        if (a["date"], a["actual"], a["open"]) != (b["date"], b["actual"], b["open"]):
            continue
        paired += 1
        if abs(a["gap"]) < 3:
            continue
        same = (a["gap"] > 0) == (b["gap"] > 0)
        low = min(abs(a["gap"]), abs(b["gap"]) if same else 0.0)
        groups["High" if low >= 4.5 else "Medium" if low >= 3 else "Low"].append(a)
    print(f"\n=== BY CONFIDENCE (gap 3+ in the live version; {paired} games paired), vs the opening line")
    out = {}
    for wname, lo_d, hi_d in WINDOWS + [("whole season", 0, 999)]:
        out[wname] = {}
        print(f"    {wname}")
        for k, rs in groups.items():
            g = grade([r for r in rs if lo_d <= r["day"] <= hi_d], 0)
            out[wname][k] = g
            print(f"        {k:6} {fmt(g)}")
    return out


if __name__ == "__main__":
    main()
