"""Player-based TOTALS model, replayed on 2024-25 and 2025-26 and graded at the opening total.

Every input follows the player, never last season's team:
  offense / defense   each player's OBPM / DBPM from the season before (small samples pulled toward
                      bench level, measured), updated in-season from his box impact
  pace                each player's on-court pace: possessions per 48 of the teams he played for,
                      in the minutes he was on the floor (season before, from box scores), updated
                      in-season the same way
  scoring level       league-wide points per 100 possessions, running this season (prior = last season)
Team = top-down minutes over the players who actually played. Fair total =
  possessions/100 x (2 x league level + home offense - away defense + away offense - home defense)
Graded like the sides: calibrated to each day's opening totals, side = over/under the model likes,
record vs the open, CLV to the close, and whether the market moves toward the model.
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from . import backtest as BT
from . import backtest_open as BO
from . import boxscore, sources
from . import personnel as P

SEASONS = {
    "2024-25": {"start": date(2024, 10, 22), "end": date(2025, 4, 13), "od": "players_od_2023_24.csv",
                "pace_season": (date(2023, 10, 24), date(2024, 4, 14)),
                "measure": ("drafts_2023.csv", "2023"), "rookies": ("drafts_2024_2025.csv", "2024")},
    "2025-26": {"start": date(2025, 10, 21), "end": date(2026, 4, 12), "od": "players_od_2024_25.csv",
                "pace_season": (date(2024, 10, 22), date(2025, 4, 13)),
                "measure": ("drafts_2024_2025.csv", "2024"), "rookies": ("drafts_2024_2025.csv", "2025")},
}
PULL = P.PULL
PACE_PRIOR_MIN = 1000     # prior pace counts as this many minutes vs this season's
LG_PRIOR_GAMES = 150      # last season's league scoring level counts as this many games
WINDOWS = BO.WINDOWS


def read_od(fname):
    out = {}
    with open(P.STATIC / fname, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            try:
                out[P.norm(r["name"])] = {"name": r["name"], "g": int(r["g"] or 0), "mp": int(r["mp"] or 0),
                                          "obpm": float(r["obpm"] or 0), "dbpm": float(r["dbpm"] or 0)}
            except ValueError:
                continue
    return out


def season_boxes(start, end):
    days = [start + timedelta(i) for i in range((end - start).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        games = [g for day in ex.map(lambda d: BT._safe(sources.espn_day, d) or [], days) for g, _ in day if g.final]
    def one(g):
        js = BT._safe(sources.get_json, BT.SUM.format(g.id))
        return g, (boxscore.parse_summary(js, g.id, g.game_date.isoformat()) if js else [])
    with ThreadPoolExecutor(12) as ex:
        return list(ex.map(one, games)), days


def pace_and_level(boxes):
    """Per player: on-court possessions per 48 and minutes. League: points per 100 possessions."""
    acc = defaultdict(lambda: [0.0, 0.0])          # espn_id -> [poss*min sum, min]
    names = {}
    pts = poss = 0.0
    for g, rows in boxes:
        teams = defaultdict(list)
        for r in rows:
            teams[r["team"]].append(r)
        for t, rs in teams.items():
            tp, gm = rs[0]["team_poss"], rs[0]["game_min"] or 48
            pts += sum(r["pts"] for r in rs)
            poss += tp
            for r in rs:
                acc[r["espn_id"]][0] += tp * 48 / gm * r["min"]
                acc[r["espn_id"]][1] += r["min"]
                names[r["espn_id"]] = r["name"]
    lg_pace = sum(a for a, _ in acc.values()) / max(sum(m for _, m in acc.values()), 1)
    by_name = {}
    for pid, (a, m) in acc.items():
        if m > 0:
            by_name[P.norm(names[pid])] = {"pace": (a + lg_pace * 300) / (m + 300), "min": m}
    return by_name, lg_pace, (pts / poss * 100 if poss else 112.0)


def priors(season):
    cfg = SEASONS[season]
    od = read_od(cfg["od"])
    small = [r for r in od.values() if 100 <= r["mp"] < 500]
    w = sum(r["mp"] for r in small) or 1
    o_base = sum(r["obpm"] * r["mp"] for r in small) / w
    d_base = sum(r["dbpm"] * r["mp"] for r in small) / w
    out = {}
    for k, r in od.items():
        mp, g = r["mp"], max(r["g"], 1)
        out[k] = {"o": (r["obpm"] * mp + o_base * PULL) / (mp + PULL), "d": (r["dbpm"] * mp + d_base * PULL) / (mp + PULL),
                  "role": min(mp / g, P.MIN_CAP) * min(1.0, g / P.ROLE_GAMES), "kind": "veteran"}
    def rows(fname, year):
        return [r for r in csv.DictReader(open(P.STATIC / fname, encoding="utf-8"), delimiter=";") if r["year"] == year]
    tiers = {}
    for lo, hi in P.PICK_TIERS:
        t = [r for r in rows(*cfg["measure"]) if lo <= int(r["pick"]) <= hi]
        recs = [od.get(P.norm(r["name"])) or P.find(od, r["name"]) for r in t]
        played = [x for x in recs if x and x["mp"] >= 100]
        mins = sum(x["mp"] for x in played) or 1
        tiers[(lo, hi)] = {"o": sum(x["obpm"] * x["mp"] for x in played) / mins if played else o_base,
                           "d": sum(x["dbpm"] * x["mp"] for x in played) / mins if played else d_base,
                           "role": sum(x["mp"] for x in recs if x) / 82 / max(len(t), 1)}
    for r in rows(*cfg["rookies"]):
        for (lo, hi), v in tiers.items():
            if lo <= int(r["pick"]) <= hi:
                out[P.norm(r["name"])] = {**v, "kind": "rookie"}
    return out, (o_base, d_base)


def fetch_totals(season, days, key):
    cache = P.STATIC / f"odds_totals_{season.replace('-', '_')}.json"
    if cache.exists():
        return json.loads(cache.read_text()), "cached"
    times = []
    for d in days:
        times += [((d - timedelta(1)).isoformat() + "T23:30:00Z", "eve", d), (d.isoformat() + "T14:00:00Z", "morn", d),
                  (d.isoformat() + "T22:30:00Z", "close", d)]
    def snap(t):
        try:
            return t, sources.odds_api_historical(key, t[0], markets="totals")
        except Exception as e:
            return t, ({}, {"error": str(e)})
    out, left = {}, None
    with ThreadPoolExecutor(6) as ex:
        for (iso, kind, d), (lines, meta) in ex.map(snap, times):
            left = meta.get("remaining") or left
            for (gd, away, home), ln in lines.items():
                if ln.get("total") is None or gd != d:
                    continue
                rec = out.setdefault(f"{gd.isoformat()}|{away}|{home}", {})
                if kind == "close":
                    rec["close"] = ln["total"]
                else:
                    rec.setdefault(kind, ln["total"])
    for rec in out.values():
        rec["open"] = rec.get("eve", rec.get("morn", rec.get("close")))
    cache.write_text(json.dumps(out))
    return out, f"fetched now, credits left {left}"


def team_line(players, prior, base, pace_prior, lg_pace, live, live_pace):
    rows = []
    for pid, name in players:
        pr = prior.get(P.norm(name)) or BT._fuzzy(prior, name)
        kind = pr["kind"] if pr else "none"
        o0, d0 = (pr["o"], pr["d"]) if pr else base
        role0 = pr["role"] if pr else 0.0
        pp = pace_prior.get(P.norm(name))
        pace0 = pp["pace"] if pp else lg_pace
        lv = live.get(pid)
        if lv and lv["min"] > 0:
            w = P.PRIOR_MIN[kind]
            tot0 = o0 + d0
            tot = (tot0 * w + lv["bpm_live"] * lv["min"]) / (w + lv["min"])
            o, d = o0 + (tot - tot0) / 2, d0 + (tot - tot0) / 2
            role = min((role0 * 3 + lv["w_min"]) / (3 + lv["w_games"]), P.MIN_CAP)
        else:
            o, d, role = o0, d0, role0
        lp = live_pace.get(pid)
        pace = (pace0 * PACE_PRIOR_MIN + lp[0]) / (PACE_PRIOR_MIN + lp[1]) if lp else pace0
        rows.append((o, d, pace, role))
    left, O, D, PACE = 240.0, 0.0, 0.0, 0.0
    for o, d, pace, role in sorted(rows, key=lambda r: -r[3]):
        m = min(role, left)
        left -= m
        O += o * m / 48
        D += d * m / 48
        PACE += pace * m / 240
    if left > 0:
        O += base[0] * left / 48
        D += base[1] * left / 48
        PACE += lg_pace * left / 240
    return O, D, PACE


def replay(season, games, lines, pace_boxes):
    prior, base = priors(season)
    pace_prior, lg_pace, lg_level0 = pace_and_level(pace_boxes)
    start = SEASONS[season]["start"]
    data = sorted([(g, r) for g, r in games if r], key=lambda d: (d[0].game_date, d[0].id))
    by_date = defaultdict(list)
    for d in data:
        by_date[d[0].game_date].append(d)
    hist, out = [], []
    live_pace = defaultdict(lambda: [0.0, 0.0])
    pts = poss = 0.0
    ng = 0
    for day in sorted(by_date):
        live = boxscore.season_impact(hist) if hist else {}
        level = (lg_level0 * LG_PRIOR_GAMES + (pts / poss * 100 if poss else lg_level0) * ng) / (LG_PRIOR_GAMES + ng)
        for g, rows in by_date[day]:
            ln = lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
            ppl = defaultdict(list)
            for r in rows:
                ppl[r["team"]].append((r["espn_id"], r["name"]))
            Oh, Dh, Ph = team_line(ppl[g.home], prior, base, pace_prior, lg_pace, live, live_pace)
            Oa, Da, Pa = team_line(ppl[g.away], prior, base, pace_prior, lg_pace, live, live_pace)
            possn = (Ph + Pa) / 2
            pred = possn / 100 * (2 * level + Oh - Da + Oa - Dh)
            out.append({"day": (day - start).days, "date": day, "pred": pred, "open": ln.get("open"),
                        "close": ln.get("close"), "actual": g.home_score + g.away_score})
        for g, rows in by_date[day]:
            hist += rows
            ng += 1
            teams = defaultdict(list)
            for r in rows:
                teams[r["team"]].append(r)
            for t, rs in teams.items():
                tp, gm = rs[0]["team_poss"], rs[0]["game_min"] or 48
                pts += sum(r["pts"] for r in rs)
                poss += tp
                for r in rs:
                    live_pace[r["espn_id"]][0] += tp * 48 / gm * r["min"]
                    live_pace[r["espn_id"]][1] += r["min"]
    return out, {"lg_pace": lg_pace, "level0": lg_level0, "o_base": base[0], "d_base": base[1]}


def calibrate(rows):
    by = defaultdict(list)
    for r in rows:
        if r["open"] is not None and r["close"] is not None:
            by[r["date"]].append(r)
    out = []
    for day, rs in by.items():
        if len(rs) < 6:
            continue
        a, b, _ = BT.ols([r["pred"] for r in rs], [r["open"] for r in rs])
        for r in rs:
            out.append({**r, "gap": a + b * r["pred"] - r["open"]})    # >0 = model says over
    return out


def grade(rows, lo):
    w = l = wc = lc = 0
    clv = []
    for r in rows:
        g = r["gap"]
        if abs(g) < lo or g == 0:
            continue
        over = g > 0
        ro = r["actual"] - r["open"]
        if ro:
            w, l = (w + 1, l) if (ro > 0) == over else (w, l + 1)
        rc = r["actual"] - r["close"]
        if rc:
            wc, lc = (wc + 1, lc) if (rc > 0) == over else (wc, lc + 1)
        clv.append((r["close"] - r["open"]) if over else (r["open"] - r["close"]))
    return {"w": w, "l": l, "wc": wc, "lc": lc, "n": len(clv), "clv": sum(clv) / len(clv) if clv else None,
            "clv_pos": sum(c > 0 for c in clv), "clv_neg": sum(c < 0 for c in clv)}


def report(cal, label):
    import math
    if len(cal) < 10:
        print(f"  {label}: only {len(cal)} games with lines — nothing to grade")
        return {}
    xs = [r["gap"] for r in cal]
    _, bm, tm = BT.ols(xs, [r["close"] - r["open"] for r in cal])
    _, bi, ti = BT.ols(xs, [r["actual"] - r["open"] for r in cal])
    rm = math.sqrt(sum((r["actual"] - r["open"]) ** 2 for r in cal) / len(cal))
    print(f"  {label}: {len(cal)} games | market total moves {bm:+.3f} toward model per pt of gap (t {tm:.1f}) | "
          f"result beats the open by {bi:+.3f}/pt (t {ti:.1f}) | open-line error {rm:.1f}")
    blob = {}
    for wname, lo_d, hi_d in WINDOWS + [("whole season", 0, 999)]:
        ws = [r for r in cal if lo_d <= r["day"] <= hi_d]
        blob[wname] = {}
        print(f"    {wname}")
        for t in (0, 2, 3, 4, 5, 6):
            gr = grade(ws, t)
            blob[wname][str(t)] = gr
            print(f"        {t}+: {BO.fmt(gr)}")
    return blob


def main():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    allcal, blobs = [], {}
    for season, cfg in SEASONS.items():
        games, days = season_boxes(cfg["start"], cfg["end"])
        pace_boxes, _ = season_boxes(*cfg["pace_season"])
        lines, how = fetch_totals(season, days, key)
        rows, info = replay(season, games, lines, pace_boxes)
        print(f"=== {season}: {len(games)} games; totals lines {how}; {sum(1 for r in rows if r['open'])} with an opener")
        print(f"    priors: league pace {info['lg_pace']:.1f}, scoring {info['level0']:.1f}/100, "
              f"bench-level OBPM {info['o_base']:+.2f}, DBPM {info['d_base']:+.2f}")
        ok = [r for r in rows if r["open"]]
        bias = sum(r["pred"] - r["open"] for r in ok) / max(len(ok), 1)
        print(f"    raw model minus opener, average: {bias:+.1f} pts")
        cal = calibrate(rows)
        allcal += cal
        blobs[season] = report(cal, "calibrated to each day's openers")
        print()
    print("=== BOTH SEASONS")
    blobs["both"] = report(allcal, "calibrated to each day's openers")
    (P.STATIC / "backtest_totals.json").write_text(json.dumps(blobs))


if __name__ == "__main__":
    main()
